"""Pure derivations the GUI needs. Kept here so they are testable headless."""
from __future__ import annotations

from .auth import auth_kind, auth_login_state
from .store import is_builtin_provider


def text_matches_query(query: str, *values) -> bool:
    """Case-insensitive AND matching for compact list filters.

    Splitting the query into words lets ``open router`` match text containing both
    terms without requiring them to be adjacent or in the same field.
    """
    terms = str(query or "").casefold().split()
    if not terms:
        return True
    haystack = " ".join(str(value or "") for value in values).casefold()
    return all(term in haystack for term in terms)

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


ACTION_KEYS = (
    "save", "test", "delete_provider", "add_model", "delete_model",
    "clear_models", "fetch_models", "logout", "hide_builtin", "set_default",
)


def action_states(
    *,
    busy: bool,
    selected: bool,
    builtin: bool,
    has_oauth: bool,
) -> dict[str, bool]:
    """Which action buttons should be enabled, as one pure derivation.

    The GUI previously computed this in two places — `_set_editing_state` on selection
    change and `_set_network_busy` on network transitions — which disagreed: finishing a
    request re-enabled the mutation buttons from `selected` alone, so a request started on
    a custom provider and completing after the user had selected a read-only builtin left
    save/delete/clear enabled on that builtin. Deriving every button from the same three
    facts makes that disagreement unrepresentable.

    - `busy`     a network request is in flight; nothing that writes may run.
    - `selected` an existing provider is selected (False in new-provider mode).
    - `builtin`  the selection is shipped in models-store.json and is read-only.
    - `has_oauth` the selection has extension-managed OAuth credentials to clear.
    """
    editable = not busy and not builtin      # form-level: save the form, test its URL
    mutable = editable and selected          # needs a provider that already exists
    return {
        "save": editable,
        "test": editable,
        "delete_provider": mutable,
        "add_model": mutable,
        "delete_model": mutable,
        "clear_models": mutable,
        "fetch_models": mutable,
        # Logout clears credentials, not config, so it stays available on builtins.
        "logout": not busy and has_oauth,
        # Hiding only applies to builtins, and never depends on the form being editable.
        "hide_builtin": not busy and builtin,
        # Pointing pi at a model is independent of whether piswitch may edit that provider,
        # so builtins qualify — they are read-only config, not invalid defaults.
        "set_default": not busy and selected,
    }


def auth_label(provider: str, auth: dict, custom: dict, *, builtin: bool) -> str:
    """列表「验证」列的文案。内置供应商加前缀，但无凭据时只显示「内置」。"""
    kind = auth_kind(provider, auth, custom)
    if kind == "oauth":
        state = auth_login_state(provider, auth)
        label = "已登录" if state == "logged_in" else ("已过期" if state == "expired" else "OAuth")
    elif kind == "api_key":
        label = "API Key"
    else:
        label = "无"
    if builtin:
        label = f"内置 / {label}" if label != "无" else "内置"
    return label


def provider_rows(custom: dict, auth: dict, store: dict, *,
                  default_provider: str | None,
                  health: dict, hidden: set) -> list[dict]:
    """供应商列表的行数据。自定义条目覆盖同名内置；hidden 只作用于内置。

    `custom` 标记这一行来自自定义配置——它不等于 `not builtin`，因为自定义
    条目可以覆盖同名内置，那种行既是内置 id 又该计入自定义。
    """
    custom_providers = custom.get("providers", {})
    if not isinstance(custom_providers, dict):
        custom_providers = {}
    rows: list[dict] = []

    def _row(provider: str, config: dict, *, is_custom: bool) -> dict:
        builtin = is_builtin_provider(provider, store)
        models = config.get("models", [])
        model_count = len(models) if isinstance(models, list) else 0
        is_default = provider == default_provider
        label = config.get("name") or provider
        if is_default:
            label = f"[默认] {label}"
        return {
            "provider": provider,
            "custom": is_custom,
            "default": is_default,
            "values": (
                provider, label, model_count,
                auth_label(provider, auth, custom, builtin=builtin),
                health.get(provider, ""),
            ),
        }

    for provider, config in sorted(custom_providers.items()):
        if not isinstance(config, dict):
            continue
        rows.append(_row(provider, config, is_custom=True))

    # 再补上没有被同名自定义条目覆盖的内置供应商
    for provider, info in sorted(store.items()):
        if provider in custom_providers or not isinstance(info, dict):
            continue
        if provider in hidden:
            continue
        rows.append(_row(provider, info, is_custom=False))
    return rows
