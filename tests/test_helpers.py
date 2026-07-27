import core


def test_parse_model_ids_dedupe_and_strip():
    assert core.parse_model_ids(" a, b ,a,, c") == ["a", "b", "c"]
    assert core.parse_model_ids("") == []


def test_build_custom_provider_cfg():
    preset = {"name": "NewAPI·GPT-4o", "provider": "newapi", "model": "gpt-4o",
              "baseUrl": "https://gw/v1", "api": "openai-completions", "apiKey": "$K"}
    cfg = core.build_custom_provider_cfg(preset)
    assert cfg["name"] == "NewAPI·GPT-4o"
    assert cfg["baseUrl"] == "https://gw/v1"
    assert cfg["api"] == "openai-completions"
    assert cfg["apiKey"] == "$K"
    ids = [m["id"] for m in cfg["models"]]
    assert "gpt-4o" in ids
    assert cfg["models"][0]["contextWindow"] == 128000  # 默认字段存在


def test_fetch_models_url_normalization():
    assert core.fetch_models_url("https://gw") == "https://gw/v1/models"
    assert core.fetch_models_url("https://gw/") == "https://gw/v1/models"
    assert core.fetch_models_url("https://gw/v1") == "https://gw/v1/models"
    assert core.fetch_models_url("https://gw/v1/models") == "https://gw/v1/models"


def test_format_preset_row_marks_active():
    settings = {"defaultProvider": "newapi", "defaultModel": "gpt-4o"}
    active = {"name": "NewAPI·GPT-4o", "provider": "newapi", "model": "gpt-4o", "kind": "custom"}
    other = {"name": "DS", "provider": "deepseek", "model": "deepseek-chat", "kind": "builtin"}
    assert core.format_preset_row(active, settings).startswith("*")
    assert core.format_preset_row(other, settings).startswith(" ")
    assert "newapi/gpt-4o" in core.format_preset_row(active, settings)
