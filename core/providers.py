"""Create, edit and delete custom providers and their models."""
from __future__ import annotations

from urllib.parse import urlsplit

from .backups import light_backup
from .catalog import MODEL_METADATA_KEYS, _provider_model, build_custom_provider_cfg, parse_model_ids
from .paths import auth_path, models_path, settings_path
from .store import load_auth, load_custom, load_settings, merge_openai_proxy_compat, write_json_atomic, write_json_bundle

def merge_custom_provider(preset: dict) -> None:
    custom = load_custom()
    custom.setdefault("providers", {})[preset["provider"]] = build_custom_provider_cfg(preset)
    write_json_atomic(models_path(), custom)


def merge_auth_key(provider: str, api_key: str) -> None:
    auth = load_auth()
    auth[provider] = {"type": "api_key", "key": api_key}
    write_json_atomic(auth_path(), auth)


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


def add_provider_models(
    provider: str,
    model_ids: str,
    *,
    ts: str,
    metadata: dict[str, dict] | None = None,
) -> list[dict]:
    """Add models to a provider. `metadata` maps model id -> real metadata to use
    instead of the placeholder defaults (see infer_model_metadata)."""
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
    metadata = metadata if isinstance(metadata, dict) else {}
    for model_id in ids:
        if model_id not in existing_ids:
            models.append(_provider_model(model_id, metadata.get(model_id)))
            existing_ids.add(model_id)

    if models == config.get("models", []):
        return models

    light_backup(ts)
    config["models"] = models
    write_json_atomic(models_path(), custom)
    return models


def update_provider_model(provider: str, model_id: str, changes: dict, *, ts: str) -> dict | None:
    """Edit one model's metadata in place. Returns the updated entry, or None if absent.

    Only MODEL_METADATA_KEYS plus `name` may be changed — `id` is the identity the rest of
    the config keys off, so renaming it here would silently orphan pi's defaultModel.
    """
    if not isinstance(changes, dict):
        raise ValueError("changes must be a dict")
    allowed = {key: changes[key] for key in (*MODEL_METADATA_KEYS, "name") if key in changes}
    if not allowed:
        return None

    custom = load_custom()
    config = custom["providers"].get(provider) if isinstance(custom.get("providers"), dict) else None
    if not isinstance(config, dict):
        return None
    models = config.get("models")
    if not isinstance(models, list):
        return None
    for model in models:
        if isinstance(model, dict) and model.get("id") == model_id:
            candidate = {**model, **allowed}
            if candidate == model:
                return model
            light_backup(ts)
            model.update(allowed)
            write_json_atomic(models_path(), custom)
            return model
    return None


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
