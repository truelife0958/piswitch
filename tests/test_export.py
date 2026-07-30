"""Tests for provider config export/import (⑦).

The security decision for this feature: exports never carry secrets. Literal API keys are
dropped; `$ENV_VAR` references survive because they name a variable, not a secret.
"""
import json

import pytest

import core


# --- export ----------------------------------------------------------------

def test_export_has_a_recognisable_envelope():
    payload = core.export_providers()
    assert payload["kind"] == "piswitch-providers"
    assert payload["version"] == core.EXPORT_VERSION
    assert "newapi" in payload["providers"]


def test_export_preserves_env_var_references():
    """$NEWAPI_API_KEY is the fixture's key: a reference, safe to share."""
    payload = core.export_providers()
    assert payload["providers"]["newapi"]["apiKey"] == "$NEWAPI_API_KEY"


def test_export_strips_literal_api_keys():
    core.save_custom_provider("secret", "Secret", "https://s.example/v1",
                              "openai-completions", "sk-super-secret", ts="20260730-130000")
    payload = core.export_providers()
    assert "apiKey" not in payload["providers"]["secret"]
    # and the secret appears nowhere in the serialised bundle at all
    assert "sk-super-secret" not in json.dumps(payload)


def test_export_carries_config_that_matters():
    payload = core.export_providers()
    cfg = payload["providers"]["newapi"]
    assert cfg["baseUrl"] == "https://gw/v1"
    assert cfg["api"] == "openai-completions"
    assert [m["id"] for m in cfg["models"]] == ["gpt-4o"]
    assert cfg["compat"]["supportsLongCacheRetention"] is False


def test_export_can_select_a_subset():
    core.save_custom_provider("other", "Other", "https://o.example/v1",
                              "openai-responses", "", ts="20260730-130001")
    payload = core.export_providers(["other"])
    assert set(payload["providers"]) == {"other"}
    # unknown ids are ignored rather than fabricated
    assert core.export_providers(["ghost"])["providers"] == {}


def test_export_excludes_builtins():
    """Builtins come from pi's models-store.json; exporting them would be noise."""
    payload = core.export_providers()
    assert "deepseek" not in payload["providers"]
    assert "nvidia" not in payload["providers"]


# --- import ----------------------------------------------------------------

def _bundle(providers):
    return {"kind": "piswitch-providers", "version": 1, "providers": providers}


def test_import_adds_new_providers():
    payload = _bundle({"fresh": {
        "name": "Fresh", "baseUrl": "https://fresh.example/v1",
        "api": "openai-completions", "models": [{"id": "m1", "name": "m1"}],
    }})
    result = core.import_providers(payload, ts="20260730-140000")
    assert result["added"] == ["fresh"]
    cfg = core.load_custom()["providers"]["fresh"]
    assert cfg["baseUrl"] == "https://fresh.example/v1"
    assert (core.switch_backups_dir() / "switch-20260730-140000").is_dir()


def test_import_skips_existing_unless_overwrite():
    payload = _bundle({"newapi": {
        "name": "Replaced", "baseUrl": "https://replaced/v1", "api": "openai-completions",
    }})
    result = core.import_providers(payload, ts="20260730-140001")
    assert result["skipped"] == ["newapi"]
    assert core.load_custom()["providers"]["newapi"]["name"] == "NewAPI"

    result = core.import_providers(payload, ts="20260730-140002", overwrite=True)
    assert result["overwritten"] == ["newapi"]
    assert core.load_custom()["providers"]["newapi"]["name"] == "Replaced"


def test_import_never_wipes_a_locally_configured_key():
    """The bundle has no key; overwriting must not silently clear the one on disk."""
    payload = _bundle({"newapi": {
        "name": "Renamed", "baseUrl": "https://gw/v1", "api": "openai-completions",
    }})
    core.import_providers(payload, ts="20260730-140003", overwrite=True)
    assert core.load_custom()["providers"]["newapi"]["apiKey"] == "$NEWAPI_API_KEY"


def test_import_writes_nothing_to_auth_json():
    before = core.load_auth()
    core.import_providers(_bundle({"fresh": {
        "baseUrl": "https://f/v1", "api": "openai-completions", "apiKey": "$SOME_VAR",
    }}), ts="20260730-140004")
    assert core.load_auth() == before


def test_import_refuses_to_shadow_a_builtin():
    result = core.import_providers(_bundle({"deepseek": {
        "baseUrl": "https://evil/v1", "api": "openai-completions",
    }}), ts="20260730-140005")
    assert result["skipped"] == ["deepseek"]
    assert "deepseek" not in core.load_custom()["providers"]


def test_import_reports_invalid_entries_without_aborting():
    payload = _bundle({
        "good": {"baseUrl": "https://g/v1", "api": "openai-completions"},
        "no-url": {"api": "openai-completions"},
        "no-api": {"baseUrl": "https://x/v1"},
        "not-a-dict": "oops",
    })
    result = core.import_providers(payload, ts="20260730-140006")
    assert result["added"] == ["good"]
    assert set(result["invalid"]) == {"no-url", "no-api", "not-a-dict"}
    assert "good" in core.load_custom()["providers"]


def test_import_backfills_compat_for_openai_providers():
    core.import_providers(_bundle({"proxy": {
        "baseUrl": "https://p/v1", "api": "openai-completions",
    }}), ts="20260730-140007")
    cfg = core.load_custom()["providers"]["proxy"]
    assert cfg["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }


def test_import_normalises_a_missing_model_list():
    core.import_providers(_bundle({"p": {
        "baseUrl": "https://p/v1", "api": "openai-completions", "models": "junk",
    }}), ts="20260730-140008")
    assert core.load_custom()["providers"]["p"]["models"] == []


def test_import_rejects_foreign_and_malformed_files():
    for payload, match in (
        ({"kind": "something-else", "version": 1, "providers": {}}, "piswitch"),
        ({"kind": "piswitch-providers", "version": 999, "providers": {"a": {}}}, "版本"),
        ({"kind": "piswitch-providers", "version": 1, "providers": {}}, "不包含"),
        ({"kind": "piswitch-providers", "version": 1}, "不包含"),
        ("not a dict", "格式无效"),
    ):
        with pytest.raises(ValueError, match=match):
            core.import_providers(payload, ts="x")


def test_import_makes_no_backup_when_nothing_changes():
    core.import_providers(_bundle({"newapi": {
        "baseUrl": "https://gw/v1", "api": "openai-completions",
    }}), ts="20260730-140009")
    assert not (core.switch_backups_dir() / "switch-20260730-140009").exists()


def test_export_import_roundtrip_is_faithful():
    core.save_custom_provider("trip", "Round Trip", "https://trip.example/v1",
                              "openai-completions", "$TRIP_KEY", ts="20260730-150000")
    core.add_provider_models("trip", "m1, m2", ts="20260730-150001",
                             metadata={"m1": {"contextWindow": 65536, "reasoning": True}})
    exported = core.export_providers(["trip"])

    core.delete_custom_provider("trip", ts="20260730-150002")
    assert "trip" not in core.load_custom()["providers"]

    result = core.import_providers(exported, ts="20260730-150003")
    assert result["added"] == ["trip"]
    restored = core.load_custom()["providers"]["trip"]
    assert restored["name"] == "Round Trip"
    assert restored["baseUrl"] == "https://trip.example/v1"
    assert restored["apiKey"] == "$TRIP_KEY"
    assert [m["id"] for m in restored["models"]] == ["m1", "m2"]
    # metadata survives the trip, not just the ids
    assert restored["models"][0]["contextWindow"] == 65536
    assert restored["models"][0]["reasoning"] is True
