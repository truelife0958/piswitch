import json
import core


def _settings():
    return json.loads((core.agent_dir() / "settings.json").read_text(encoding="utf-8"))


def test_apply_settings_preserves_unrelated_keys():
    core.apply_settings("deepseek", "deepseek-chat", "high")
    s = _settings()
    assert s["defaultProvider"] == "deepseek"
    assert s["defaultModel"] == "deepseek-chat"
    assert s["defaultThinkingLevel"] == "high"
    assert s["packages"] == ["npm:a", "npm:b"]          # 未被清掉
    assert s["lastChangelogVersion"] == "0.80.10"       # 未被清掉


def test_apply_settings_thinking_optional():
    core.apply_settings("nvidia", "z-ai/glm-4")          # 不传 thinking
    assert _settings()["defaultThinkingLevel"] == "medium"  # 保留原值


def test_light_backup_copies_three_files():
    d = core.light_backup("20260727-120000")
    assert (d / "settings.json").exists()
    assert (d / "models.json").exists()
    assert (d / "auth.json").exists()


def test_switch_to_builtin():
    preset = {"id": "1", "name": "DS", "kind": "builtin", "provider": "deepseek", "model": "deepseek-chat"}
    core.switch_to(preset, "20260727-120001")
    assert _settings()["defaultProvider"] == "deepseek"


def test_switch_to_custom_merges_models_and_auth():
    preset = {"id": "2", "name": "GW", "kind": "custom", "provider": "gw", "model": "m1, m2",
              "baseUrl": "https://gw/v1", "api": "openai-completions", "apiKey": "$GW"}
    core.switch_to(preset, "20260727-120002")
    models = json.loads((core.agent_dir() / "models.json").read_text(encoding="utf-8"))
    auth = json.loads((core.agent_dir() / "auth.json").read_text(encoding="utf-8"))
    assert set(m["id"] for m in models["providers"]["gw"]["models"]) == {"m1", "m2"}
    assert auth["gw"] == {"type": "api_key", "key": "$GW"}
    assert _settings()["defaultProvider"] == "gw"
    assert _settings()["defaultModel"] == "m1"
    assert core.is_active(preset, _settings()) is True


def test_switch_to_rejects_missing_target_without_backup():
    with __import__("pytest").raises(ValueError):
        core.switch_to({"name": "broken", "provider": ""}, "20260727-120003")
    assert not core.switch_backups_dir().exists()


def test_active_detection():
    presets = [
        {"id": "1", "provider": "nvidia", "model": "z-ai/glm-5.2"},
        {"id": "2", "provider": "deepseek", "model": "deepseek-chat"},
    ]
    assert core.active_preset_id(presets, core.load_settings()) == "1"  # 样例默认 nvidia/glm-5.2
    assert core.is_active(presets[1], core.load_settings()) is False


def test_preset_from_current():
    p = core.preset_from_current(core.load_settings(), core.load_custom())
    assert p["provider"] == "nvidia" and p["model"] == "z-ai/glm-5.2" and p["kind"] == "builtin"


def test_preset_from_current_rejects_missing_target():
    with __import__("pytest").raises(ValueError):
        core.preset_from_current({}, {})
