import core
from pathlib import Path


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


def test_save_custom_provider_preserves_oauth_when_renaming():
    oauth = {"access": "tok", "refresh": "ref", "expires": 9_999_999_999_999}
    core.write_json_atomic(core.auth_path(), {"newapi": oauth})

    config = core.save_custom_provider(
        "renamed", "Renamed", "https://gw/v1", "openai-completions",
        "(OAuth，已登录)", ts="20260731-100000-oauth",
        original_provider="newapi", preserve_auth=True,
    )

    assert core.load_auth() == {"renamed": oauth}
    assert config["apiKey"] == "$NEWAPI_API_KEY"
    assert config["apiKey"] != "(OAuth，已登录)"


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


def test_delete_provider_models_batch_removes_many_atomic():
    # newapi starts with one model (gpt-4o) per the shared fixture
    core.add_provider_models("newapi", "a, b, c, d", ts="20260728-100010")
    removed = core.delete_provider_models("newapi", ["a", "c", "missing"], ts="20260728-100011")
    assert removed == 2  # missing not counted
    assert [m["id"] for m in core.load_custom()["providers"]["newapi"]["models"]] == ["gpt-4o", "b", "d"]
    # preserves order of remaining models and skips non-string/empty input
    assert core.delete_provider_models("newapi", [], ts="x") == 0
    assert core.delete_provider_models("newapi", ["b", 5, None], ts="x") == 1
    # unknown provider -> 0, no write
    assert core.delete_provider_models("ghost", ["a"], ts="x") == 0


def test_clear_provider_models_empties_all():
    # newapi starts with one model (gpt-4o) per the shared fixture
    core.add_provider_models("newapi", "p, q, r", ts="20260728-100020")
    removed = core.clear_provider_models("newapi", ts="20260728-100021")
    assert removed == 4  # gpt-4o + p, q, r
    assert core.load_custom()["providers"]["newapi"]["models"] == []
    # idempotent: clearing again is 0 and does not write
    assert core.clear_provider_models("newapi", ts="20260728-100022") == 0
    # unknown provider -> 0
    assert core.clear_provider_models("ghost", ts="x") == 0


def test_delete_custom_provider_removes_auth():
    assert core.delete_custom_provider("newapi", ts="20260728-100006") is True
    assert "newapi" not in core.load_custom()["providers"]
    assert "newapi" not in core.load_auth()
    assert core.delete_custom_provider("missing", ts="20260728-100007") is False


def test_delete_provider_credentials_only_removes_auth():
    # deepseek has an api_key entry per the fixture; newapi only has an env-ref apiKey.
    assert "deepseek" in core.load_auth()
    assert core.delete_provider_credentials("deepseek", ts="20260728-100008") is True
    # auth entry is gone
    assert "deepseek" not in core.load_auth()
    # idempotent
    assert core.delete_provider_credentials("deepseek", ts="20260728-100009") is False
    # unknown provider -> False, no write
    assert core.delete_provider_credentials("ghost", ts="x") is False
    # deleting a custom provider with only an env-ref apiKey (no auth entry) is a no-op
    assert core.delete_provider_credentials("newapi", ts="x") is False


def test_delete_provider_credentials_handles_oauth_shape():
    """A logged-in OAuth provider must be logout-able, same code path."""
    import json
    auth = {"corp-x": {"access": "tok", "refresh": "r", "expires": 9_999_999_999_999}}
    (Path(core.agent_dir()) / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    assert core.delete_provider_credentials("corp-x", ts="20260728-100010") is True
    assert "corp-x" not in core.load_auth()
    assert core.delete_provider_credentials("corp-x", ts="x") is False


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
