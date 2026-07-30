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


