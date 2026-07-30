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


# --- ① set as default ------------------------------------------------------

def test_set_default_points_pi_at_the_selected_model(app):
    app.refresh_providers(select="newapi")
    row = app.model_tree.get_children()[0]
    assert app.model_tree.set(row, "id") == "gpt-4o"
    app.model_tree.selection_set(row)

    app.set_default()

    assert core.is_default_model("newapi", "gpt-4o") is True
    assert "newapi/gpt-4o" in app.status_var.get()


def test_set_default_marks_the_row_and_the_provider(app):
    app.refresh_providers(select="newapi")
    row = app.model_tree.get_children()[0]
    app.model_tree.selection_set(row)
    app.set_default()

    # ★ on the model row...
    marked = [r for r in app.model_tree.get_children() if app.model_tree.set(r, "default") == "★"]
    assert [app.model_tree.set(r, "id") for r in marked] == ["gpt-4o"]
    # ...and on the provider row
    assert app.provider_tree.set("newapi", "name").startswith("★")


def test_set_default_works_on_a_builtin_provider(app):
    """Builtins are read-only config but valid defaults."""
    app.refresh_providers(select="deepseek")
    rows = app.model_tree.get_children()
    app.model_tree.selection_set(rows[0])
    model_id = app.model_tree.set(rows[0], "id")

    app.set_default()

    assert core.is_default_model("deepseek", model_id) is True
    assert str(app._action_buttons["set_default"].cget("state")) == "normal"
    # ...while config editing stays locked
    assert str(app._action_buttons["save"].cget("state")) == "disabled"


def test_set_default_requires_a_model_selection(app, monkeypatch):
    shown = []
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda t, m, **k: shown.append(m))
    app.refresh_providers(select="newapi")
    app.model_tree.selection_remove(*app.model_tree.get_children())
    app.model_tree.focus("")

    app.set_default()

    assert shown and "模型" in shown[0]
    # nothing was written
    assert core.is_default_model("newapi", "gpt-4o") is False


def test_set_default_refuses_multiple_selection(app, monkeypatch):
    shown = []
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda t, m, **k: shown.append(m))
    core.add_provider_models("newapi", "second-model", ts="20260730-100000")
    app.refresh_providers(select="newapi")
    app.model_tree.selection_set(*app.model_tree.get_children())

    app.set_default()

    assert shown and "只选中一个" in shown[0]


def test_delete_model_still_reads_the_right_column(app, monkeypatch):
    """Regression guard: the model tree gained 默认/上下文 columns, so the old
    positional values[0] read would have deleted the wrong thing."""
    monkeypatch.setattr(piswitch.messagebox, "askyesno", lambda *a, **k: True)
    core.add_provider_models("newapi", "doomed-model", ts="20260730-100001")
    app.refresh_providers(select="newapi")
    row = next(r for r in app.model_tree.get_children()
               if app.model_tree.set(r, "id") == "doomed-model")
    app.model_tree.selection_set(row)

    app.delete_model()

    remaining = {m["id"] for m in core.load_custom()["providers"]["newapi"]["models"]}
    assert remaining == {"gpt-4o"}


def test_context_window_column_is_populated(app):
    app.refresh_providers(select="deepseek")
    rows = app.model_tree.get_children()
    # The fixture's builtin models carry no contextWindow, so they must read as unknown
    # rather than as a fabricated number.
    assert app.model_tree.set(rows[0], "context") == "—"




# --- ③ deep connection test ------------------------------------------------

def test_test_connection_also_sends_a_real_completion(app, monkeypatch):
    app.refresh_providers(select="newapi")
    monkeypatch.setattr(core, "fetch_remote_models",
                        lambda *a, **k: [{"id": "gpt-4o", "name": "gpt-4o"}])
    chatted = {}

    def fake_probe(base_url, api, model_id, api_key, **kwargs):
        chatted["model"] = model_id
        chatted["api"] = api
        return "ok"

    monkeypatch.setattr(core, "probe_chat", fake_probe)
    infos = []
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda t, m, **k: infos.append(m))

    app.test_connection()
    _drain(app)

    assert chatted["model"] == "gpt-4o"
    assert chatted["api"] == "openai-completions"
    assert infos and "对话正常" in infos[0]


def test_test_connection_warns_when_listing_passes_but_chat_fails(app, monkeypatch):
    """The exact failure the probe exists for: proxy lists models, rejects completions."""
    app.refresh_providers(select="newapi")
    monkeypatch.setattr(core, "fetch_remote_models",
                        lambda *a, **k: [{"id": "gpt-4o", "name": "gpt-4o"}])

    def rejecting(*_a, **_k):
        raise ValueError("HTTP 400: Unsupported parameter: prompt_cache_key")

    monkeypatch.setattr(core, "probe_chat", rejecting)
    warnings = []
    monkeypatch.setattr(piswitch.messagebox, "showwarning", lambda t, m, **k: warnings.append(m))

    app.test_connection()
    _drain(app)

    assert warnings and "prompt_cache_key" in warnings[0]
    assert "对话失败" in app.status_var.get()


def test_test_connection_skips_chat_probe_for_unsupported_api(app, monkeypatch):
    app.refresh_providers(select="newapi")
    app.api_var.set("bedrock-converse-stream")
    monkeypatch.setattr(core, "fetch_remote_models", lambda *a, **k: [{"id": "m", "name": "m"}])
    monkeypatch.setattr(core, "probe_chat", lambda *a, **k: pytest.fail("must not chat-probe"))
    infos = []
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda t, m, **k: infos.append(m))

    app.test_connection()
    _drain(app)

    assert infos and "不支持对话探测" in infos[0]


# --- ② model metadata editor -----------------------------------------------

def test_model_editor_opens_with_current_values_and_saves(app):
    core.update_provider_model("newapi", "gpt-4o", {"contextWindow": 4096},
                               ts="20260730-120000")
    app.refresh_providers(select="newapi")
    row = app.model_tree.get_children()[0]
    app.model_tree.selection_set(row)

    app.edit_model()
    editor = app._model_editor
    try:
        buttons = _buttons(editor)
        assert set(buttons) >= {"保存", "取消"}
        entries = [w for w in _all_widgets(editor) if w.winfo_class() == "TEntry"]
        # 名称 / 上下文 / 最大输出 / 输入价 / 输出价
        assert len(entries) == 5
        assert entries[1].get() == "4096"
        entries[1].delete(0, "end")
        entries[1].insert(0, "1000000")
        buttons["保存"].invoke()
    finally:
        if editor.winfo_exists():
            editor.destroy()

    stored = core.load_custom()["providers"]["newapi"]["models"][0]
    assert stored["contextWindow"] == 1000000
    assert app.model_tree.set(app.model_tree.get_children()[0], "context") == "1.0M"


def test_model_editor_rejects_bad_numbers_without_writing(app, monkeypatch):
    errors = []
    monkeypatch.setattr(piswitch.messagebox, "showerror", lambda t, m, **k: errors.append(m))
    app.refresh_providers(select="newapi")
    app.model_tree.selection_set(app.model_tree.get_children()[0])
    app.edit_model()
    editor = app._model_editor
    try:
        entries = [w for w in _all_widgets(editor) if w.winfo_class() == "TEntry"]
        entries[1].delete(0, "end")
        entries[1].insert(0, "not-a-number")
        _buttons(editor)["保存"].invoke()
        assert errors and "整数" in errors[0]
        assert editor.winfo_exists(), "dialog should stay open on invalid input"
    finally:
        if editor.winfo_exists():
            editor.destroy()
    assert "contextWindow" not in core.load_custom()["providers"]["newapi"]["models"][0]


def test_model_editor_refuses_builtin_providers(app, monkeypatch):
    infos = []
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda t, m, **k: infos.append(m))
    app.refresh_providers(select="deepseek")
    app.model_tree.selection_set(app.model_tree.get_children()[0])

    app.edit_model()

    assert infos and "内置" in infos[0]


def test_imported_models_inherit_builtin_metadata(app, monkeypatch):
    """A gateway reselling a builtin model id should not get placeholder numbers."""
    monkeypatch.setattr(piswitch.messagebox, "showinfo", lambda *a, **k: None)
    app.refresh_providers(select="newapi")
    # nvidia (builtin) ships z-ai/glm-5.2 with reasoning=True in the fixture store
    app._show_remote_models([{"id": "z-ai/glm-5.2", "name": "GLM"}], "newapi")
    dialog = _toplevels(app)[0]
    try:
        tree = next(w for w in _all_widgets(dialog) if w.winfo_class() == "Treeview")
        tree.selection_set("0")
        app._show_remote_selected = None
        _buttons(dialog)["全选"].invoke()
        _buttons(dialog)["导入所选"].invoke()
    finally:
        if dialog.winfo_exists():
            dialog.destroy()

    imported = next(m for m in core.load_custom()["providers"]["newapi"]["models"]
                    if m["id"] == "z-ai/glm-5.2")
    assert imported["reasoning"] is True  # inherited from the builtin store, not defaulted


