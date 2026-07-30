"""Where pi's and piswitch's files live. Env-overridable for tests."""
from __future__ import annotations

from pathlib import Path
import os
import time

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
