import core


def test_save_custom_provider_creates_config_and_auth():
    config = core.save_custom_provider(
        "gateway",
        "Team Gateway",
        "https://gateway.example/v1/",
        "openai-responses",
        "$GATEWAY_KEY",
        ts="20260728-100000",
    )

    assert config["baseUrl"] == "https://gateway.example/v1"
    assert core.load_custom()["providers"]["gateway"]["name"] == "Team Gateway"
    assert core.load_auth()["gateway"] == {"type": "api_key", "key": "$GATEWAY_KEY"}
    assert (core.switch_backups_dir() / "switch-20260728-100000").is_dir()


def test_save_openai_completions_provider_adds_safe_proxy_compat():
    config = core.save_custom_provider(
        "proxy", "Proxy", "https://proxy.example/v1", "openai-completions", "",
        ts="20260728-100000-compat",
    )
    assert config["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }


def test_save_openai_completions_provider_preserves_explicit_compat():
    custom = core.load_custom()
    custom["providers"]["newapi"]["compat"] = {
        "sendSessionAffinityHeaders": False,
        "supportsLongCacheRetention": True,
        "supportsUsageInStreaming": False,
    }
    core.write_json_atomic(core.models_path(), custom)

    config = core.save_custom_provider(
        "newapi", "NewAPI", "https://gw/v1", "openai-completions", "$NEWAPI_API_KEY",
        ts="20260728-100000-existing-compat",
    )

    assert config["compat"] == {
        "sendSessionAffinityHeaders": False,
        "supportsLongCacheRetention": True,
        "supportsUsageInStreaming": False,
    }


def test_save_custom_provider_preserves_models_and_can_clear_key():
    core.add_provider_models("newapi", "second-model", ts="20260728-100001")
    core.save_custom_provider(
        "newapi", "Renamed", "https://new.example/v1", "openai-completions", "",
        ts="20260728-100002",
    )

    config = core.load_custom()["providers"]["newapi"]
    assert {model["id"] for model in config["models"]} == {"gpt-4o", "second-model"}
    assert "apiKey" not in config
    assert "newapi" not in core.load_auth()


def test_save_custom_provider_can_rename_and_migrate_references(pi_env):
    settings = core.load_settings()
    settings["defaultProvider"] = "newapi"
    settings["defaultModel"] = "gpt-4o"
    core.write_json_atomic(core.settings_path(), settings)

    core.save_custom_provider(
        "renamed", "Renamed", "https://gw/v1", "openai-completions", "$NEWAPI_API_KEY",
        ts="20260728-100002-rename", original_provider="newapi",
    )

    providers = core.load_custom()["providers"]
    assert "newapi" not in providers
    assert providers["renamed"]["models"][0]["id"] == "gpt-4o"
    assert "newapi" not in core.load_auth()
    assert core.load_auth()["renamed"] == {"type": "api_key", "key": "$NEWAPI_API_KEY"}
    assert core.load_settings()["defaultProvider"] == "renamed"


def test_rename_rejects_existing_provider_without_changes():
    core.save_custom_provider(
        "other", "Other", "https://other.example/v1", "openai-completions", "",
        ts="20260728-100002-other",
    )
    with __import__("pytest").raises(ValueError, match="already exists"):
        core.save_custom_provider(
            "other", "Collision", "https://gw/v1", "openai-completions", "",
            ts="20260728-100002-collision", original_provider="newapi",
        )
    assert set(core.load_custom()["providers"]) == {"newapi", "other"}


def test_add_and_delete_provider_models():
    models = core.add_provider_models("newapi", "gpt-4o, m2, m2", ts="20260728-100003")
    assert [model["id"] for model in models] == ["gpt-4o", "m2"]
    assert core.delete_provider_model("newapi", "m2", ts="20260728-100004") is True
    assert core.delete_provider_model("newapi", "missing", ts="20260728-100005") is False


def test_delete_custom_provider_removes_auth():
    assert core.delete_custom_provider("newapi", ts="20260728-100006") is True
    assert "newapi" not in core.load_custom()["providers"]
    assert "newapi" not in core.load_auth()
    assert core.delete_custom_provider("missing", ts="20260728-100007") is False


def test_provider_crud_validates_required_fields():
    import pytest

    with pytest.raises(ValueError):
        core.save_custom_provider("", "Name", "https://example.com", "api", "", ts="x")
    with pytest.raises(ValueError, match="base URL"):
        core.save_custom_provider("provider", "Name", "https://", "api", "", ts="x")
    with pytest.raises(ValueError, match="provider ID"):
        core.save_custom_provider("bad/provider", "Name", "https://example.com", "api", "", ts="x")
    with pytest.raises(ValueError):
        core.add_provider_models("newapi", "", ts="x")
