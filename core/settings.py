"""pi's default provider/model."""
from __future__ import annotations

from .backups import light_backup
from .paths import settings_path
from .store import load_settings, write_json_atomic

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


def set_default_model(provider: str, model_id: str, *, ts: str) -> dict:
    """Point pi at this provider/model, snapshotting first.

    The GUI could previously only *warn* that a provider/model was pi's default; setting
    one required dropping to `piswitch model <query>`. This is the same operation the CLI
    performs, with the light_backup the CLI path also does. Builtins are valid targets —
    read-only means piswitch will not rewrite their config, not that pi cannot use them.
    """
    provider = (provider or "").strip()
    model_id = (model_id or "").strip()
    if not provider or not model_id:
        raise ValueError("provider and model are required")
    light_backup(ts)
    return apply_settings(provider, model_id)
