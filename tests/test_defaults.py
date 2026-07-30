"""Tests for the API-key status indicator and pi default-model switching."""
import pytest

import core


# --- ⑥ api_key_status ------------------------------------------------------

def test_api_key_status_empty():
    assert core.api_key_status("") == ("empty", "")
    assert core.api_key_status("   ") == ("empty", "")
    assert core.api_key_status(None) == ("empty", "")


def test_api_key_status_literal_key_needs_no_environment():
    assert core.api_key_status("sk-abc123") == ("literal", "")


def test_api_key_status_env_reference_set():
    assert core.api_key_status("$MY_KEY", environ={"MY_KEY": "v"}) == ("env_set", "MY_KEY")
    # ${VAR} braces are accepted the same way resolve_api_key_value accepts them
    assert core.api_key_status("${MY_KEY}", environ={"MY_KEY": "v"}) == ("env_set", "MY_KEY")


def test_api_key_status_env_reference_missing():
    """The whole point of ⑥: report this in the form, not only when a fetch fails."""
    assert core.api_key_status("$NOPE", environ={}) == ("env_missing", "NOPE")
    # present but empty counts as missing, matching resolve_api_key_value
    assert core.api_key_status("$NOPE", environ={"NOPE": ""}) == ("env_missing", "NOPE")


def test_api_key_status_invalid_reference():
    assert core.api_key_status("$", environ={}) == ("invalid", "")
    assert core.api_key_status("${}", environ={}) == ("invalid", "")


def test_api_key_status_agrees_with_resolve_api_key_value():
    """The indicator must not claim a key resolves when resolving would raise."""
    environ = {"SET": "v", "EMPTY": ""}
    for value in ("$SET", "$EMPTY", "$", "sk-literal", ""):
        state, _ = core.api_key_status(value, environ=environ)
        try:
            core.resolve_api_key_value(value, environ=environ)
        except ValueError:
            assert state in {"env_missing", "invalid"}, value
        else:
            assert state in {"env_set", "literal", "empty"}, value


# --- ① set_default_model ---------------------------------------------------

def test_set_default_model_writes_settings_and_backs_up():
    settings = core.set_default_model("newapi", "gpt-4o", ts="20260730-090000")
    assert settings["defaultProvider"] == "newapi"
    assert settings["defaultModel"] == "gpt-4o"
    assert core.load_settings()["defaultProvider"] == "newapi"
    assert core.load_settings()["defaultModel"] == "gpt-4o"
    # every mutation snapshots first, like the rest of core
    assert (core.switch_backups_dir() / "switch-20260730-090000").is_dir()


def test_set_default_model_preserves_unrelated_settings():
    """settings.json holds pi's own keys; switching must not drop them."""
    before = core.load_settings()
    assert before["packages"] == ["npm:a", "npm:b"]
    core.set_default_model("newapi", "gpt-4o", ts="20260730-090001")
    after = core.load_settings()
    assert after["packages"] == ["npm:a", "npm:b"]
    assert after["lastChangelogVersion"] == before["lastChangelogVersion"]
    assert after["defaultThinkingLevel"] == before["defaultThinkingLevel"]


def test_set_default_model_can_target_a_builtin():
    """Builtins are read-only as config but are perfectly valid as the default."""
    core.set_default_model("deepseek", "deepseek-chat", ts="20260730-090002")
    assert core.is_default_model("deepseek", "deepseek-chat") is True


def test_set_default_model_rejects_empty_arguments():
    for provider, model in (("", "m"), ("p", ""), ("  ", "m"), ("p", "  ")):
        with pytest.raises(ValueError):
            core.set_default_model(provider, model, ts="x")


def test_set_default_model_is_reflected_by_is_default_helpers():
    core.set_default_model("newapi", "gpt-4o", ts="20260730-090003")
    assert core.is_default_provider("newapi") is True
    assert core.is_default_model("newapi", "gpt-4o") is True
    assert core.is_default_model("newapi", "other") is False
    # switching again moves both
    core.set_default_model("nvidia", "z-ai/glm-4", ts="20260730-090004")
    assert core.is_default_provider("newapi") is False
    assert core.is_default_model("nvidia", "z-ai/glm-4") is True
