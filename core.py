# core.py — 纯逻辑，不 import tkinter
from __future__ import annotations
import json, os, shutil, tempfile
from pathlib import Path
from typing import Any


def agent_dir() -> Path:
    return Path(os.environ.get("PI_AGENT_DIR", str(Path.home() / ".pi" / "agent")))


def data_dir() -> Path:
    return Path(os.environ.get("PISWITCH_DATA_DIR", str(Path.home() / ".local" / "share" / "piswitch")))


def settings_path() -> Path:      return agent_dir() / "settings.json"
def models_store_path() -> Path:  return agent_dir() / "models-store.json"
def models_path() -> Path:        return agent_dir() / "models.json"
def auth_path() -> Path:          return agent_dir() / "auth.json"
def presets_path() -> Path:       return data_dir() / "presets.json"
def switch_backups_dir() -> Path: return data_dir() / "backups"


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


def load_settings() -> dict:
    return read_json(settings_path(), {}) or {}


def load_models_store() -> dict:
    return read_json(models_store_path(), {}) or {}


def load_custom() -> dict:
    data = read_json(models_path(), {}) or {}
    if "providers" not in data:
        data["providers"] = {}
    return data


def load_auth() -> dict:
    return read_json(auth_path(), {}) or {}


def provider_model_map(store: dict, custom: dict) -> dict:
    result: dict[str, list[dict]] = {}
    for prov, info in store.items():
        if not isinstance(info, dict):
            continue
        for m in info.get("models", []) or []:
            if isinstance(m, dict):
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "builtin"})
    for prov, cfg in custom.get("providers", {}).items():
        if not isinstance(cfg, dict):
            continue
        for m in cfg.get("models", []) or []:
            if isinstance(m, dict):
                result.setdefault(prov, []).append(
                    {"id": m.get("id"), "name": m.get("name") or m.get("id"), "source": "custom"})
    for prov in result:
        result[prov].sort(key=lambda x: (x["source"], x["id"] or ""))
    return result


def resolve_has_key(provider: str, auth: dict, custom: dict) -> bool:
    if provider in auth and auth[provider].get("key"):
        return True
    ak = custom.get("providers", {}).get(provider, {}).get("apiKey")
    return isinstance(ak, str) and bool(ak.strip())


def model_supports_reasoning(store: dict, custom: dict, provider: str, model_id) -> bool:
    if not provider or not model_id:
        return False
    for m in store.get(provider, {}).get("models", []) or []:
        if m.get("id") == model_id:
            return bool(m.get("reasoning"))
    for m in custom.get("providers", {}).get(provider, {}).get("models", []) or []:
        if m.get("id") == model_id:
            return bool(m.get("reasoning"))
    return False
