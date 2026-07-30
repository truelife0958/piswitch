"""Exporting and importing provider config without secrets."""
from __future__ import annotations

from typing import Any

from .backups import light_backup
from .paths import models_path
from .store import is_builtin_provider, load_custom, load_models_store, merge_openai_proxy_compat, write_json_atomic

EXPORT_KIND = "piswitch-providers"


EXPORT_VERSION = 1


def export_providers(provider_ids: list[str] | None = None) -> dict:
    """Serialise custom providers with secrets removed.

    Literal API keys are dropped entirely. `$ENV_VAR` references are kept, because the
    reference names a variable rather than containing the secret — the importer still has
    to set that variable themselves. This is what makes an export safe to commit or send.
    """
    providers = load_custom()["providers"]
    if provider_ids is None:
        wanted = list(providers)
    else:
        wanted = [pid for pid in provider_ids if pid in providers]
    exported = {}
    for provider in sorted(wanted):
        cfg = providers[provider]
        if not isinstance(cfg, dict):
            continue
        clean = {key: value for key, value in cfg.items() if key != "apiKey"}
        api_key = cfg.get("apiKey")
        if isinstance(api_key, str) and api_key.strip().startswith("$"):
            clean["apiKey"] = api_key.strip()
        exported[provider] = clean
    return {"kind": EXPORT_KIND, "version": EXPORT_VERSION, "providers": exported}


def _valid_import_config(cfg: Any) -> bool:
    if not isinstance(cfg, dict):
        return False
    base_url = cfg.get("baseUrl")
    api = cfg.get("api")
    return (
        isinstance(base_url, str) and bool(base_url.strip())
        and isinstance(api, str) and bool(api.strip())
    )


def import_providers(payload: Any, *, ts: str, overwrite: bool = False) -> dict:
    """Merge an exported bundle into models.json.

    Never touches auth.json: an export carries no secrets, so there is nothing to write
    there, and silently clearing an existing key would be a nasty surprise. Returns
    {'added': [...], 'overwritten': [...], 'skipped': [...], 'invalid': [...]}.
    """
    if not isinstance(payload, dict):
        raise ValueError("导入文件格式无效")
    if payload.get("kind") != EXPORT_KIND:
        raise ValueError("这不是 piswitch 导出的配置文件")
    version = payload.get("version")
    if not isinstance(version, int) or version > EXPORT_VERSION:
        raise ValueError(f"不支持的导出版本：{version}")
    incoming = payload.get("providers")
    if not isinstance(incoming, dict) or not incoming:
        raise ValueError("导入文件不包含任何供应商")

    custom = load_custom()
    providers = custom["providers"]
    store = load_models_store()
    result = {"added": [], "overwritten": [], "skipped": [], "invalid": []}

    for provider in sorted(incoming):
        cfg = incoming[provider]
        if not isinstance(provider, str) or not provider.strip():
            result["invalid"].append(str(provider))
            continue
        if not _valid_import_config(cfg):
            result["invalid"].append(provider)
            continue
        # Builtins are owned by pi; importing over one would shadow it silently.
        if is_builtin_provider(provider, store):
            result["skipped"].append(provider)
            continue
        exists = provider in providers
        if exists and not overwrite:
            result["skipped"].append(provider)
            continue
        merged = {key: value for key, value in cfg.items() if key != "apiKey"}
        api_key = cfg.get("apiKey")
        if isinstance(api_key, str) and api_key.strip().startswith("$"):
            merged["apiKey"] = api_key.strip()
        elif exists and isinstance(providers[provider], dict):
            # Keep the key already configured locally rather than wiping it.
            existing_key = providers[provider].get("apiKey")
            if isinstance(existing_key, str) and existing_key:
                merged["apiKey"] = existing_key
        if not isinstance(merged.get("models"), list):
            merged["models"] = []
        if merged.get("api") == "openai-completions":
            merged["compat"] = merge_openai_proxy_compat(merged.get("compat"))
        providers[provider] = merged
        result["overwritten" if exists else "added"].append(provider)

    if not result["added"] and not result["overwritten"]:
        return result
    light_backup(ts)
    write_json_atomic(models_path(), custom)
    return result
