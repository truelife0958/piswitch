import core


def test_load_presets_default_empty():
    assert core.load_presets() == []


def test_add_assigns_id_and_persists():
    p = core.add_preset({"name": "A", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    assert p["id"]
    reloaded = core.load_presets()
    assert len(reloaded) == 1 and reloaded[0]["name"] == "A"


def test_update_merges_changes():
    p = core.add_preset({"name": "A", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    upd = core.update_preset(p["id"], {"name": "A2", "thinking": "high"})
    assert upd["name"] == "A2" and upd["thinking"] == "high"
    assert core.load_presets()[0]["name"] == "A2"


def test_update_missing_returns_none():
    assert core.update_preset("nope", {"name": "x"}) is None


def test_delete():
    p = core.add_preset({"name": "A", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"})
    assert core.delete_preset(p["id"]) is True
    assert core.load_presets() == []
    assert core.delete_preset(p["id"]) is False


def test_ids_unique():
    assert core.new_preset_id() != core.new_preset_id()


def test_load_presets_ignores_invalid_container_and_entries(pi_env):
    core.presets_path().write_text('["invalid"]', encoding="utf-8")
    assert core.load_presets() == []
    core.presets_path().write_text('{"presets": [null, {"name": "valid"}]}', encoding="utf-8")
    assert core.load_presets() == []


def test_add_rejects_invalid_and_duplicate_presets():
    import pytest

    with pytest.raises(ValueError):
        core.add_preset({"name": "missing target"})

    preset = {"id": "same", "name": "A", "provider": "p", "model": "m"}
    core.add_preset(preset)
    with pytest.raises(ValueError, match="duplicate"):
        core.add_preset(preset)


def test_load_presets_ignores_duplicate_ids():
    core.write_json_atomic(core.presets_path(), {"presets": [
        {"id": "same", "name": "A", "provider": "p", "model": "m1"},
        {"id": "same", "name": "B", "provider": "p", "model": "m2"},
    ]})
    assert [preset["name"] for preset in core.load_presets()] == ["A"]
