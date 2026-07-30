"""Reading and writing the JSON config files, plus the compat backfill."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import shutil
import tempfile

from .paths import auth_path, hidden_builtins_path, models_path, models_store_path, settings_path

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
    # Atomic like every other config writer, so an interrupted write cannot truncate the file.
    write_json_atomic(hidden_builtins_path(), sorted(ids))


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
