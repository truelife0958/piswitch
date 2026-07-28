# core.py — 纯逻辑，不 import tkinter
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def _now_ms() -> int:
    """Current wall-clock time in milliseconds. Used to evaluate OAuth `expires`.
    Keep as a function (not a module constant) so tests can monkeypatch it.
    """
    return int(time.time() * 1000)


def agent_dir() -> Path:
    return Path(os.environ.get("PI_AGENT_DIR", str(Path.home() / ".pi" / "agent")))


def data_dir() -> Path:
    return Path(os.environ.get("PISWITCH_DATA_DIR", str(Path.home() / ".local" / "share" / "piswitch")))


def settings_path() -> Path:
    return agent_dir() / "settings.json"


def models_store_path() -> Path:
    return agent_dir() / "models-store.json"


def models_path() -> Path:
    return agent_dir() / "models.json"


def auth_path() -> Path:
    return agent_dir() / "auth.json"


def presets_path() -> Path:
    return data_dir() / "presets.json"


def hidden_builtins_path() -> Path:
    """Piswitch-local list of builtin providers the user hid from the provider list."""
    return data_dir() / "hidden_builtins.json"



def switch_backups_dir() -> Path:
    return data_dir() / "backups"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: {e}") from e


def write_json_atomic(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_bundle(updates: list[tuple[Path, Any]]) -> None:
    originals = {}
    for path, _data in updates:
        path = Path(path)
        originals[path] = (path.exists(), read_json(path, {}) if path.exists() else None)

    written = []
    try:
        for path, data in updates:
            path = Path(path)
            write_json_atomic(path, data)
            written.append(path)
    except Exception:
        for path in reversed(written):
            existed, original = originals[path]
            try:
                if existed:
                    write_json_atomic(path, original)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def load_settings() -> dict:
    return _dict_or_empty(read_json(settings_path(), {}))


def load_models_store() -> dict:
    return _dict_or_empty(read_json(models_store_path(), {}))


def load_custom() -> dict:
    data = _dict_or_empty(read_json(models_path(), {}))
    if not isinstance(data.get("providers"), dict):
        data["providers"] = {}
    backfill_proxy_compat(data)  # self-heal legacy openai-completions providers
    return data


def load_auth() -> dict:
    return _dict_or_empty(read_json(auth_path(), {}))


def _dict_or_empty(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def is_builtin_provider(provider: str, store: dict) -> bool:
    """True if this provider is shipped in models-store.json (pi-builtin)."""
    info = store.get(provider) if isinstance(store, dict) else None
    return isinstance(info, dict) and isinstance(info.get("models"), list)


def load_hidden_builtins() -> set[str]:
    """Builtin provider ids the user removed from the piswitch list."""
    try:
        data = json.loads(hidden_builtins_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(data, list):
        return {str(x) for x in data if isinstance(x, str) and x}
    if isinstance(data, dict):
        ids = data.get("providers")
        if isinstance(ids, list):
            return {str(x) for x in ids if isinstance(x, str) and x}
    return set()


def _write_hidden_builtins(ids: set[str]) -> None:
    ids = {x for x in ids if isinstance(x, str) and x}
    data_dir().mkdir(parents=True, exist_ok=True)
    hidden_builtins_path().write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def hide_builtin(provider: str) -> None:
    if not isinstance(provider, str) or not provider:
        return
    ids = load_hidden_builtins()
    ids.add(provider)
    _write_hidden_builtins(ids)


def unhide_builtin(provider: str) -> None:
    if not isinstance(provider, str) or not provider:
        return
    ids = load_hidden_builtins()
    ids.discard(provider)
    _write_hidden_builtins(ids)

def provider_model_map(store: dict, custom: dict) -> dict:
    result: dict[str, list[dict]] = {}
    for prov, info in store.items():
        if not isinstance(info, dict):
            continue
        models = info.get("models", [])
        for m in models if isinstance(models, list) else []:
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]:
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "builtin"})
    providers = custom.get("providers", {})
    for prov, cfg in providers.items() if isinstance(providers, dict) else []:
        if not isinstance(cfg, dict):
            continue
        models = cfg.get("models", [])
        for m in models if isinstance(models, list) else []:
            if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]:
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "custom"})
    for prov in result:
        result[prov].sort(key=lambda x: (x["source"], x["id"] or ""))
    return result


def resolve_has_key(provider: str, auth: dict, custom: dict) -> bool:
    auth_entry = auth.get(provider)
    if isinstance(auth_entry, dict):
        if auth_entry.get("key"):
            return True
        # OAuth credentials: consider the provider "has key" if an access token exists.
        if isinstance(auth_entry.get("access"), str) and auth_entry["access"]:
            return True
    providers = custom.get("providers", {})
    cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    ak = cfg.get("apiKey") if isinstance(cfg, dict) else None
    return isinstance(ak, str) and bool(ak.strip())


def auth_kind(provider: str, auth: dict, custom: dict) -> str:
    """Classify how a provider authenticates.

    Returns one of: 'api_key', 'oauth', or '' (unknown / no auth configured).
    OAuth here means the pi extension persisted credentials of the shape
    {access, refresh, expires} rather than the api-key shape {type:'api_key', key}.
    """
    auth_entry = auth.get(provider)
    if isinstance(auth_entry, dict):
        if isinstance(auth_entry.get("access"), str) and auth_entry["access"]:
            return "oauth"
        if auth_entry.get("type") == "api_key" or auth_entry.get("key"):
            return "api_key"
    providers = custom.get("providers", {})
    cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    ak = cfg.get("apiKey") if isinstance(cfg, dict) else None
    if isinstance(ak, str) and ak.strip():
        return "api_key"
    return ""


def auth_login_state(provider: str, auth: dict) -> str:
    """For OAuth entries, return the human-readable login state.

    'logged_in' - access token present and not past `expires`.
    'expired'    - credentials present but past `expires` (needs extension refresh).
    'none'      - no OAuth credentials for this provider.
    """
    entry = auth.get(provider)
    if not isinstance(entry, dict):
        return "none"
    access = entry.get("access")
    if not (isinstance(access, str) and access):
        return "none"
    expires = entry.get("expires")
    # `expires` is a ms epoch (per pi docs). Treat missing / non-numeric as not-yet-expired
    # so we don't mislead users about a freshly written cred.
    if isinstance(expires, (int, float)) and expires > 0 and expires <= _now_ms():
        return "expired"
    return "logged_in"


def delete_provider_credentials(provider: str, *, ts: str) -> bool:
    """Remove only this provider's auth entry (logout-equivalent).

    Leaves the provider's models.json configuration untouched. Returns True if an
    entry was actually removed. Used for both api_key and OAuth providers.
    """
    auth = load_auth()
    if provider not in auth:
        return False
    light_backup(ts)
    auth.pop(provider, None)
    write_json_atomic(auth_path(), auth)
    return True


def model_supports_reasoning(store: dict, custom: dict, provider: str, model_id) -> bool:
    if not provider or not model_id:
        return False
    builtin = store.get(provider, {})
    builtin_models = builtin.get("models", []) if isinstance(builtin, dict) else []
    for m in builtin_models if isinstance(builtin_models, list) else []:
        if isinstance(m, dict) and m.get("id") == model_id:
            return bool(m.get("reasoning"))
    providers = custom.get("providers", {})
    cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    custom_models = cfg.get("models", []) if isinstance(cfg, dict) else []
    for m in custom_models if isinstance(custom_models, list) else []:
        if isinstance(m, dict) and m.get("id") == model_id:
            return bool(m.get("reasoning"))
    return False


DEFAULT_INPUT_TYPES = ["text", "image"]
BACKUP_RETENTION = 20
HTTP_USER_AGENT = "piswitch/1.0"
OPENAI_PROXY_COMPAT = {
    "sendSessionAffinityHeaders": True,
    "supportsLongCacheRetention": False,
}


def merge_openai_proxy_compat(compat: Any) -> dict:
    return {
        **OPENAI_PROXY_COMPAT,
        **(compat if isinstance(compat, dict) else {}),
    }


def backfill_proxy_compat(data: Any) -> bool:
    """Field-level backfill of OPENAI_PROXY_COMPAT onto existing openai-completions
    providers that predate the safe-default code. Explicit user settings are preserved;
    only missing keys are filled in. Returns True if anything changed.

    Mutates `data` in place. Safe to call repeatedly (idempotent).
    """
    if not isinstance(data, dict):
        return False
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return False
    changed = False
    for prov in providers.values():
        if not isinstance(prov, dict) or prov.get("api") != "openai-completions":
            continue
        compat = prov.get("compat")
        compat = compat if isinstance(compat, dict) else {}
        merged = {**OPENAI_PROXY_COMPAT, **compat}
        if merged != prov.get("compat"):
            prov["compat"] = merged
            changed = True
    return changed


def range_toggle_targets(iids, anchor_iid, click_iid, is_selected):
    """Compute the (iid, target_checked) plan for a Shift+click marquee toggle.

    Given the ordered list of row iids, an anchor row, the clicked row, and a
    function `is_selected(iid) -> bool` returning the current checked state,
    returns a list of ``(iid, target)`` pairs to apply. The whole span from the
    anchor to the clicked row is unified to the state the clicked row takes
    after this click (toggled). If anchor == clicked row, only that row toggles.

    Returns [] if anchor or click is not in `iids`.
    """
    if anchor_iid not in iids or click_iid not in iids:
        return []
    start = iids.index(anchor_iid)
    end = iids.index(click_iid)
    if start > end:
        start, end = end, start
    target = not is_selected(click_iid)  # state the clicked row takes after this click
    return [(iid, target) for iid in iids[start:end + 1]]



def parse_model_ids(text: str) -> list[str]:
    out: list[str] = []
    for part in (text or "").split(","):
        s = part.strip()
        if s and s not in out:
            out.append(s)
    return out


def build_custom_provider_cfg(preset: dict) -> dict:
    ids = parse_model_ids(preset.get("model", "")) or ([preset["model"]] if preset.get("model") else [])
    models = [{
        "id": i, "name": i, "reasoning": bool(preset.get("reasoning", False)),
        "input": list(DEFAULT_INPUT_TYPES),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000, "maxTokens": 16384,
    } for i in ids]
    config = {
        "name": preset.get("name") or preset["provider"],
        "baseUrl": preset.get("baseUrl", ""),
        "api": preset.get("api", "openai-completions"),
        "apiKey": preset.get("apiKey", ""),
        "models": models,
    }
    if config["api"] == "openai-completions":
        config["compat"] = merge_openai_proxy_compat(preset.get("compat"))
    return config


def fetch_models_url(base: str) -> str:
    b = (base or "").rstrip("/")
    if b.endswith("/models"):
        return b
    if b.endswith("/v1"):
        return b + "/models"
    return b + "/v1/models"


def resolve_api_key_value(api_key: str, environ: dict[str, str] | None = None) -> str:
    value = (api_key or "").strip()
    if not value.startswith("$"):
        return value
    variable = value[1:].strip("{}")
    if not variable:
        raise ValueError("invalid API key environment variable reference")
    resolved = (environ if environ is not None else os.environ).get(variable, "")
    if not resolved:
        raise ValueError(f'environment variable "{variable}" is not set')
    return resolved


def fetch_remote_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = 20,
    opener=None,
) -> list[dict]:
    url = fetch_models_url(base_url)
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("base URL must be a valid http:// or https:// URL")

    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": HTTP_USER_AGENT,
    })
    token = resolve_api_key_value(api_key)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with (opener or urlopen)(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError(f"authentication failed (HTTP {exc.code})") from exc
        raise ValueError(f"model endpoint returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"cannot connect to model endpoint: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ValueError("model endpoint request timed out") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("model endpoint did not return valid JSON") from exc

    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list) and isinstance(payload, dict):
        records = payload.get("models")
    if not isinstance(records, list):
        raise ValueError("model endpoint response does not contain a model list")

    models = []
    seen = set()
    for record in records:
        if isinstance(record, str):
            model_id, name = record, record
        elif isinstance(record, dict):
            model_id = record.get("id") or record.get("name")
            name = record.get("name") or model_id
        else:
            continue
        if isinstance(model_id, str) and model_id.strip() and model_id not in seen:
            models.append({"id": model_id, "name": name if isinstance(name, str) else model_id})
            seen.add(model_id)
    return models


def format_preset_row(preset: dict, settings: dict) -> str:
    mark = "*" if is_active(preset, settings) else " "
    return f"{mark} {preset.get('name','?')}  [{preset.get('provider')}/{preset.get('model')}]  {preset.get('kind','')}"


def light_backup(ts: str) -> Path:
    dest = switch_backups_dir() / f"switch-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for p in (settings_path(), models_path(), auth_path()):
        if p.exists():
            shutil.copy2(p, dest / p.name)
    backups = sorted(
        path for path in switch_backups_dir().glob("switch-*")
        if path.is_dir()
    )
    for old_backup in backups[:-BACKUP_RETENTION]:
        shutil.rmtree(old_backup, ignore_errors=True)
    return dest


def list_switch_backups() -> list[Path]:
    return sorted(
        (
            path for path in switch_backups_dir().glob("switch-*")
            if path.is_dir()
        ),
        reverse=True,
    )


def restore_switch_backup(backup: Path, *, ts: str) -> list[str]:
    backup = Path(backup).resolve()
    backup_root = switch_backups_dir().resolve()
    if backup.parent != backup_root or not backup.name.startswith("switch-") or not backup.is_dir():
        raise ValueError("invalid backup directory")

    targets = {
        "settings.json": settings_path(),
        "models.json": models_path(),
        "auth.json": auth_path(),
    }
    snapshot = {}
    for name in targets:
        source = backup / name
        if source.exists():
            snapshot[name] = read_json(source, {})
    if not snapshot:
        raise ValueError("backup does not contain configuration files")

    light_backup(ts)
    write_json_bundle([(targets[name], data) for name, data in snapshot.items()])
    return list(snapshot)


def is_default_provider(provider: str, settings: dict | None = None) -> bool:
    current = settings if settings is not None else load_settings()
    return current.get("defaultProvider") == provider


def is_default_model(provider: str, model_id: str, settings: dict | None = None) -> bool:
    current = settings if settings is not None else load_settings()
    return current.get("defaultProvider") == provider and current.get("defaultModel") == model_id


def apply_settings(provider: str, model: str, thinking=None) -> dict:
    settings = load_settings()
    settings["defaultProvider"] = provider
    if model:
        settings["defaultModel"] = model
    if thinking:
        settings["defaultThinkingLevel"] = thinking
    write_json_atomic(settings_path(), settings)
    return settings


def merge_custom_provider(preset: dict) -> None:
    custom = load_custom()
    custom.setdefault("providers", {})[preset["provider"]] = build_custom_provider_cfg(preset)
    write_json_atomic(models_path(), custom)


def merge_auth_key(provider: str, api_key: str) -> None:
    auth = load_auth()
    auth[provider] = {"type": "api_key", "key": api_key}
    write_json_atomic(auth_path(), auth)


def _provider_model(model_id: str) -> dict:
    return {
        "id": model_id,
        "name": model_id,
        "reasoning": False,
        "input": list(DEFAULT_INPUT_TYPES),
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": 128000,
        "maxTokens": 16384,
    }


def save_custom_provider(
    provider: str,
    name: str,
    base_url: str,
    api: str,
    api_key: str,
    *,
    ts: str,
    original_provider: str | None = None,
) -> dict:
    provider = provider.strip()
    name = name.strip()
    base_url = base_url.strip()
    api = api.strip()
    api_key = api_key.strip()
    if not provider or not name or not base_url or not api:
        raise ValueError("provider, name, base URL, and API type are required")
    if any(character.isspace() for character in provider) or "/" in provider:
        raise ValueError("provider ID cannot contain whitespace or '/'")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("base URL must be a valid http:// or https:// URL")

    custom = load_custom()
    providers = custom["providers"]
    original = original_provider.strip() if isinstance(original_provider, str) else provider
    if original_provider is not None and original not in providers:
        raise ValueError(f'custom provider "{original}" does not exist')
    if original != provider and provider in providers:
        raise ValueError(f'custom provider "{provider}" already exists')

    existing = providers.get(original, {})
    existing = existing if isinstance(existing, dict) else {}
    config = {
        **existing,
        "name": name,
        "baseUrl": base_url.rstrip("/"),
        "api": api,
        "models": existing.get("models", []) if isinstance(existing.get("models"), list) else [],
    }
    if api == "openai-completions":
        config["compat"] = merge_openai_proxy_compat(existing.get("compat"))
    if api_key:
        config["apiKey"] = api_key
    else:
        config.pop("apiKey", None)

    auth = load_auth()
    if original != provider:
        auth.pop(original, None)
    if api_key:
        auth[provider] = {"type": "api_key", "key": api_key}
    else:
        auth.pop(provider, None)

    settings = load_settings()
    settings_changed = original != provider and settings.get("defaultProvider") == original
    if settings_changed:
        settings["defaultProvider"] = provider

    light_backup(ts)
    if original != provider:
        del providers[original]
    providers[provider] = config
    updates = [(models_path(), custom), (auth_path(), auth)]
    if settings_changed:
        updates.append((settings_path(), settings))
    write_json_bundle(updates)
    return config


def delete_custom_provider(provider: str, *, ts: str) -> bool:
    custom = load_custom()
    if provider not in custom["providers"]:
        return False

    auth = load_auth()
    light_backup(ts)
    del custom["providers"][provider]
    auth.pop(provider, None)
    write_json_bundle([(models_path(), custom), (auth_path(), auth)])
    return True


def add_provider_models(provider: str, model_ids: str, *, ts: str) -> list[dict]:
    ids = parse_model_ids(model_ids)
    if not ids:
        raise ValueError("at least one model ID is required")

    custom = load_custom()
    config = custom["providers"].get(provider)
    if not isinstance(config, dict):
        raise ValueError(f'custom provider "{provider}" does not exist')
    models = config.get("models", [])
    models = list(models) if isinstance(models, list) else []
    existing_ids = {
        model.get("id") for model in models
        if isinstance(model, dict) and isinstance(model.get("id"), str)
    }
    for model_id in ids:
        if model_id not in existing_ids:
            models.append(_provider_model(model_id))
            existing_ids.add(model_id)

    if models == config.get("models", []):
        return models

    light_backup(ts)
    config["models"] = models
    write_json_atomic(models_path(), custom)
    return models


def delete_provider_model(provider: str, model_id: str, *, ts: str) -> bool:
    custom = load_custom()
    config = custom["providers"].get(provider)
    if not isinstance(config, dict):
        return False
    models = config.get("models", [])
    if not isinstance(models, list):
        return False
    kept = [
        model for model in models
        if not isinstance(model, dict) or model.get("id") != model_id
    ]
    if len(kept) == len(models):
        return False

    light_backup(ts)
    config["models"] = kept
    write_json_atomic(models_path(), custom)
    return True


def delete_provider_models(provider: str, model_ids: list[str], *, ts: str) -> int:
    """Remove the given model ids from a provider. Returns the count actually removed.

    Atomic single backup/write, even for many ids. Preserves order of remaining models.
    """
    if not isinstance(model_ids, list):
        return 0
    target = {mid for mid in model_ids if isinstance(mid, str)}
    if not target:
        return 0

    custom = load_custom()
    config = custom["providers"].get(provider) if isinstance(custom.get("providers"), dict) else None
    if not isinstance(config, dict):
        return 0
    models = config.get("models", [])
    if not isinstance(models, list):
        return 0

    kept = [
        model for model in models
        if not (isinstance(model, dict) and model.get("id") in target)
    ]
    removed = len(models) - len(kept)
    if removed == 0:
        return 0

    light_backup(ts)
    config["models"] = kept
    write_json_atomic(models_path(), custom)
    return removed


def clear_provider_models(provider: str, *, ts: str) -> int:
    """Remove all models from a provider. Returns the count removed (0 if none)."""
    custom = load_custom()
    config = custom["providers"].get(provider) if isinstance(custom.get("providers"), dict) else None
    if not isinstance(config, dict):
        return 0
    models = config.get("models", [])
    if not isinstance(models, list) or not models:
        return 0
    n = len(models)
    light_backup(ts)
    config["models"] = []
    write_json_atomic(models_path(), custom)
    return n


def switch_to(preset: dict, ts: str) -> dict:
    provider = preset.get("provider")
    model_ids = parse_model_ids(preset.get("model", ""))
    if not isinstance(provider, str) or not provider.strip() or not model_ids:
        raise ValueError("preset requires non-empty provider and model")
    light_backup(ts)
    if preset.get("kind") == "custom":
        merge_custom_provider(preset)
        if preset.get("apiKey"):
            merge_auth_key(preset["provider"], preset["apiKey"])
    return apply_settings(provider.strip(), model_ids[0], preset.get("thinking"))


def is_active(preset, settings):
    model_ids = parse_model_ids(preset.get("model", ""))
    return (
        preset.get("provider") == settings.get("defaultProvider")
        and bool(model_ids)
        and model_ids[0] == settings.get("defaultModel")
    )


def active_preset_id(presets: list, settings: dict):
    for p in presets:
        if is_active(p, settings):
            return p.get("id")
    return None


def preset_from_current(settings: dict, custom: dict) -> dict:
    prov = settings.get("defaultProvider")
    model = settings.get("defaultModel")
    if not isinstance(prov, str) or not prov.strip() or not isinstance(model, str) or not model.strip():
        raise ValueError("current settings do not contain a default provider/model")
    cfg = custom.get("providers", {}).get(prov)
    preset = {
        "id": new_preset_id(),
        "name": f"{prov}/{model}",
        "kind": "custom" if cfg else "builtin",
        "provider": prov, "model": model,
        "thinking": settings.get("defaultThinkingLevel"),
    }
    if cfg:
        preset.update({"baseUrl": cfg.get("baseUrl", ""), "api": cfg.get("api", "openai-completions"),
                       "apiKey": cfg.get("apiKey", "")})
    return preset


def new_preset_id() -> str:
    return uuid.uuid4().hex


def _valid_preset(preset: Any, *, require_id: bool = True) -> bool:
    if not isinstance(preset, dict):
        return False
    required = ("name", "provider", "model")
    if require_id:
        required = ("id", *required)
    return all(isinstance(preset.get(key), str) and preset[key].strip() for key in required)


def load_presets() -> list:
    data = read_json(presets_path(), {}) or {}
    if not isinstance(data, dict):
        return []
    presets = data.get("presets", [])
    if not isinstance(presets, list):
        return []
    result = []
    seen_ids = set()
    for preset in presets:
        if _valid_preset(preset) and preset["id"] not in seen_ids:
            result.append(preset)
            seen_ids.add(preset["id"])
    return result


def save_presets(presets: list) -> None:
    if not isinstance(presets, list) or not all(_valid_preset(preset) for preset in presets):
        raise ValueError("every preset requires non-empty id, name, provider, and model")
    write_json_atomic(presets_path(), {"presets": presets})


def add_preset(preset: dict) -> dict:
    preset = dict(preset)
    preset.setdefault("id", new_preset_id())
    if not _valid_preset(preset):
        raise ValueError("preset requires non-empty name, provider, and model")
    presets = load_presets()
    if any(existing["id"] == preset["id"] for existing in presets):
        raise ValueError(f'duplicate preset id: {preset["id"]}')
    presets.append(preset)
    save_presets(presets)
    return preset


def update_preset(preset_id: str, changes: dict):
    presets = load_presets()
    updated = None
    for p in presets:
        if p.get("id") == preset_id:
            candidate = {**p, **changes}
            if not _valid_preset(candidate):
                raise ValueError("preset requires non-empty name, provider, and model")
            p.update(changes)
            updated = p
            break
    if updated is not None:
        save_presets(presets)
    return updated


def delete_preset(preset_id: str) -> bool:
    presets = load_presets()
    kept = [p for p in presets if p.get("id") != preset_id]
    if len(kept) == len(presets):
        return False
    save_presets(kept)
    return True


USAGE = (
    "piswitch — pi 自定义模型供应商管理工具\n"
    "  piswitch                启动供应商管理 GUI\n"
    "  piswitch --help         显示帮助\n"
    "\n兼容命令:\n"
    "  piswitch list | ls      列出旧版预设(*=当前)\n"
    "  piswitch use <名称>     按旧版预设名切换\n"
    "  piswitch model <query>  按 provider/model 子串直接切换\n"
)


def _default_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def cli_list(out=print) -> int:
    settings = load_settings()
    presets = load_presets()
    if not presets:
        out("(无预设) 用 GUI 新增，或 `piswitch model <query>` 直接切换。")
        return 0
    for p in presets:
        out(format_preset_row(p, settings))
    return 0


def _find_preset(name: str):
    presets = load_presets()
    exact = [p for p in presets if p.get("name") == name]
    if exact:
        return exact[0]
    subs = [p for p in presets if name.lower() in (p.get("name", "").lower())]
    return subs[0] if len(subs) == 1 else (None if not subs else False)  # False=歧义


def cli_use(name: str, ts: str, out=print) -> int:
    hit = _find_preset(name)
    if hit is None:
        out(f'piswitch: 没有匹配预设 "{name}"')
        return 1
    if hit is False:
        out(f'piswitch: "{name}" 匹配到多个预设，请写更精确的名称')
        return 1
    core_switch = switch_to(hit, ts)
    out(f"✓ 已切换到预设 {hit.get('name')} → {core_switch.get('defaultProvider')}/{core_switch.get('defaultModel')}")
    return 0


def cli_model(query: str, ts: str, out=print) -> int:
    store, custom = load_models_store(), load_custom()
    pm = provider_model_map(store, custom)
    matches = set()
    q = query.lower()
    for prov, models in pm.items():
        for m in models:
            key = f"{prov}/{m['id']}"
            if q in key.lower():
                matches.add((prov, m["id"]))
    if not matches:
        out(f'piswitch: 无模型匹配 "{query}"')
        return 1
    if len(matches) > 1:
        out(f'piswitch: "{query}" 匹配到 {len(matches)} 个，请写更精确：')
        for prov, mid in sorted(matches)[:20]:
            out(f"  {prov}/{mid}")
        return 1
    prov, mid = next(iter(matches))
    light_backup(ts)
    apply_settings(prov, mid)
    out(f"✓ pi 默认模型 → {prov}/{mid}")
    return 0


def dispatch(args, ts=None):
    if not args:
        return None  # 启动 GUI
    ts = ts or _default_ts()
    cmd = args[0]
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("list", "ls", "-l", "--list"):
        return cli_list()
    if cmd == "use":
        if len(args) < 2:
            print("用法: piswitch use <名称>")
            return 1
        return cli_use(" ".join(args[1:]), ts)
    if cmd == "model":
        if len(args) < 2:
            print("用法: piswitch model <query>")
            return 1
        return cli_model(" ".join(args[1:]), ts)
    print(f'piswitch: 未知命令 "{cmd}"\n\n{USAGE}')
    return 2
