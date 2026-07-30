"""How a provider authenticates, and resolving its API key."""
from __future__ import annotations

import os

from .backups import light_backup
from .paths import _now_ms, auth_path
from .store import load_auth, write_json_atomic

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


def api_key_status(api_key: str, environ: dict[str, str] | None = None) -> tuple[str, str]:
    """Classify an API-key field so the form can show it inline.

    `resolve_api_key_value` only raises at fetch time, which means a `$VAR` typo or an
    unexported variable looks fine until a request fails. This is the same decision made
    eagerly, for display. Returns `(state, variable_name)` where state is one of:

    'empty'       nothing entered
    'literal'     a key typed in directly; no environment lookup needed
    'env_set'     a `$VAR` reference whose variable is set and non-empty
    'env_missing' a `$VAR` reference that would raise on use
    'invalid'     `$` or `${}` with no variable name

    Kept in agreement with `resolve_api_key_value` by test_api_key_status_agrees_*.
    """
    value = (api_key or "").strip()
    if not value:
        return ("empty", "")
    if not value.startswith("$"):
        return ("literal", "")
    variable = value[1:].strip("{}")
    if not variable:
        return ("invalid", "")
    env = environ if environ is not None else os.environ
    return ("env_set" if env.get(variable) else "env_missing", variable)


def provider_api_key(provider: str, cfg: dict, auth: dict) -> str:
    """The provider's raw (unresolved) key. auth.json wins over models.json.

    OAuth entries carry `access`, not `key`, so they fall through to models.json here —
    an OAuth provider has no api key to probe with.
    """
    entry = auth.get(provider) if isinstance(auth, dict) else None
    if isinstance(entry, dict):
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            return key
    api_key = cfg.get("apiKey") if isinstance(cfg, dict) else None
    return api_key if isinstance(api_key, str) else ""
