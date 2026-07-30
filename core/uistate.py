"""Pure derivations the GUI needs. Kept here so they are testable headless."""
from __future__ import annotations

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
