import core


def test_loaders_read_samples():
    assert core.load_settings()["defaultProvider"] == "nvidia"
    assert "nvidia" in core.load_models_store()
    assert "newapi" in core.load_custom()["providers"]
    assert core.load_auth()["deepseek"]["key"] == "sk-abc"


def test_load_custom_ensures_providers_key(pi_env):
    (pi_env["agent"] / "models.json").write_text("{}", encoding="utf-8")
    assert core.load_custom() == {"providers": {}}


def test_provider_model_map_merges_builtin_and_custom():
    m = core.provider_model_map(core.load_models_store(), core.load_custom())
    assert {x["id"] for x in m["nvidia"]} == {"z-ai/glm-5.2", "z-ai/glm-4"}
    assert m["nvidia"][0]["source"] == "builtin"
    assert m["newapi"][0] == {"id": "gpt-4o", "name": "gpt-4o", "source": "custom"}


def test_resolve_has_key():
    auth, custom = core.load_auth(), core.load_custom()
    assert core.resolve_has_key("deepseek", auth, custom) is True   # 在 auth.json
    assert core.resolve_has_key("newapi", auth, custom) is True     # custom.apiKey 非空
    assert core.resolve_has_key("nvidia", auth, custom) is False


def test_model_supports_reasoning():
    store, custom = core.load_models_store(), core.load_custom()
    assert core.model_supports_reasoning(store, custom, "nvidia", "z-ai/glm-5.2") is True
    assert core.model_supports_reasoning(store, custom, "nvidia", "z-ai/glm-4") is False
    assert core.model_supports_reasoning(store, custom, "nvidia", None) is False


def test_catalog_helpers_ignore_malformed_entries():
    store = {"bad": {"models": [None, {}, {"id": "ok"}]}}
    custom = {"providers": {"bad": None}}
    assert core.provider_model_map(store, custom)["bad"][0]["id"] == "ok"
    assert core.resolve_has_key("bad", {"bad": "invalid"}, custom) is False
    assert core.model_supports_reasoning(store, custom, "bad", "missing") is False
