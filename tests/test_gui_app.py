"""Tests that construct a real App window.

The rest of the GUI suite only imports piswitch, which is why a dialog that built no
buttons at all (open_backup_restore) shipped unnoticed. These tests need a display;
they skip when tkinter cannot open one.
"""
import tkinter as tk

import pytest

import core
import piswitch


@pytest.fixture
def app(pi_env):
    """A real App window. Depends on pi_env explicitly so the isolated PI_AGENT_DIR /
    PISWITCH_DATA_DIR are in place before App() reads or backs up any config."""
    try:
        window = piswitch.App()
    except tk.TclError as exc:  # no display in this environment
        pytest.skip(f"no display available: {exc}")
    window.withdraw()  # keep the window off-screen during the run
    yield window
    window.destroy()


def _toplevels(window) -> list[tk.Toplevel]:
    return [child for child in window.winfo_children() if isinstance(child, tk.Toplevel)]


def _buttons(widget):
    """Every ttk/tk Button in the widget subtree, keyed by its label."""
    found = {}
    for child in widget.winfo_children():
        if child.winfo_class() in ("TButton", "Button"):
            found[str(child.cget("text"))] = child
        found.update(_buttons(child))
    return found


def _all_widgets(widget):
    """Depth-first list of every descendant, in creation order."""
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_all_widgets(child))
    return out


def _drain(app):
    """Run the queued network callback on the main thread, as the poller would."""
    callback, error = app._network_results.get(timeout=10)
    app._set_network_busy(False)
    if error is not None:
        raise error
    callback()


def test_app_starts_and_lists_providers(app):
    rows = app.provider_tree.get_children()
    # The fixture ships one custom provider (newapi) and two builtins (nvidia, deepseek).
    assert "newapi" in rows
    assert set(rows) >= {"newapi", "nvidia", "deepseek"}


def test_selecting_every_provider_row_loads_without_error(app):
    for iid in app.provider_tree.get_children():
        app._load_provider(iid)
        assert app.current_provider == iid


def test_backup_restore_dialog_has_working_buttons(app):
    """Regression: the dialog defined restore_selected() but wired it to nothing,
    leaving no way to confirm or even cancel the documented restore feature."""
    core.light_backup("20260728-120000")

    app.open_backup_restore()
    dialogs = _toplevels(app)
    assert len(dialogs) == 1, "restore dialog did not open"
    dialog = dialogs[0]
    try:
        labels = _buttons(dialog)
        assert "恢复所选" in labels, f"no restore button; found {sorted(labels)}"
        assert "取消" in labels, f"no cancel button; found {sorted(labels)}"
        # The restore button must be bound to a real callback, not left empty.
        assert labels["恢复所选"].cget("command")
    finally:
        dialog.destroy()


def test_backup_restore_button_actually_restores(app, monkeypatch):
    """Clicking 恢复所选 must run core.restore_switch_backup for the selected row."""
    core.light_backup("20260728-130000")
    monkeypatch.setattr(piswitch.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda *a, **k: None)
    called = {}

    def fake_restore(backup, *, ts):
        called["backup"] = backup
        return ["settings.json", "models.json", "auth.json"]

    monkeypatch.setattr(core, "restore_switch_backup", fake_restore)

    app.open_backup_restore()
    dialog = _toplevels(app)[0]
    _buttons(dialog)["恢复所选"].invoke()

    assert called["backup"].name == "switch-20260728-130000"
    assert not _toplevels(app), "dialog should close after a successful restore"


def test_builtin_selection_disables_mutation_buttons(app):
    app._load_provider("nvidia")  # builtin, from models-store.json
    assert app._current_is_builtin is True
    for key in ("save", "delete_provider", "add_model", "clear_models", "fetch_models"):
        assert str(app._action_buttons[key].cget("state")) == "disabled", key
    assert str(app._action_buttons["hide_builtin"].cget("state")) == "normal"


def test_custom_selection_enables_mutation_buttons(app):
    app._load_provider("newapi")  # custom, from models.json
    assert app._current_is_builtin is False
    for key in ("save", "delete_provider", "add_model", "clear_models", "fetch_models"):
        assert str(app._action_buttons[key].cget("state")) == "normal", key


def test_network_completion_does_not_unlock_a_builtin(app):
    """Regression: a request started on a custom provider and finishing after the user
    selected a builtin used to re-enable save/delete on that read-only builtin."""
    app._load_provider("newapi")
    app._set_network_busy(True)
    app._load_provider("nvidia")   # user switches to a builtin mid-flight
    app._set_network_busy(False)   # request completes
    for key in ("save", "delete_provider", "add_model", "clear_models", "fetch_models"):
        assert str(app._action_buttons[key].cget("state")) == "disabled", key


def test_new_provider_reenables_the_api_key_field(app, monkeypatch):
    """Regression: selecting an OAuth provider disabled the key entry, and new_provider
    never re-enabled it, so a fresh provider could not be given a key."""
    auth = {"corp-x": {"access": "tok", "expires": 9_999_999_999_999}}
    core.write_json_atomic(core.auth_path(), auth)
    custom = core.load_custom()
    custom["providers"]["corp-x"] = {"name": "Corp X", "api": "openai-completions", "models": []}
    core.write_json_atomic(core.models_path(), custom)

    app.refresh_providers(select="corp-x")
    assert str(app.api_key_entry.cget("state")) == "disabled"

    app.new_provider()
    assert str(app.api_key_entry.cget("state")) == "normal"
    assert str(app._action_buttons["save"].cget("state")) == "normal"


# --- ⑥ $ENV_VAR indicator --------------------------------------------------

def test_key_status_reports_missing_env_var_while_typing(app, monkeypatch):
    monkeypatch.delenv("PISWITCH_TEST_KEY", raising=False)
    app.api_key_var.set("$PISWITCH_TEST_KEY")
    assert "未设置" in app.key_status_var.get()
    assert "PISWITCH_TEST_KEY" in app.key_status_var.get()


def test_key_status_reports_set_env_var(app, monkeypatch):
    monkeypatch.setenv("PISWITCH_TEST_KEY", "resolved")
    app.api_key_var.set("$PISWITCH_TEST_KEY")
    assert "✓" in app.key_status_var.get()


def test_key_status_is_silent_for_literal_and_empty_keys(app):
    app.api_key_var.set("sk-literal-key")
    assert app.key_status_var.get() == ""
    app.api_key_var.set("")
    assert app.key_status_var.get() == ""


def test_key_status_updates_on_provider_selection(app):
    """newapi's fixture key is $NEWAPI_API_KEY, which is not exported in the test env."""
    app.refresh_providers(select="newapi")
    assert "NEWAPI_API_KEY" in app.key_status_var.get()




