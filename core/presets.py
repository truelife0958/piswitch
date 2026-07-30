"""Legacy named provider/model presets, used by the CLI."""
from __future__ import annotations

from typing import Any
import uuid

from .backups import light_backup
from .catalog import parse_model_ids
from .paths import presets_path
from .providers import merge_auth_key, merge_custom_provider
from .settings import apply_settings
from .store import read_json, write_json_atomic

def format_preset_row(preset: dict, settings: dict) -> str:
    mark = "*" if is_active(preset, settings) else " "
    return f"{mark} {preset.get('name','?')}  [{preset.get('provider')}/{preset.get('model')}]  {preset.get('kind','')}"


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
