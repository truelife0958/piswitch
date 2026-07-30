"""Tests for real model metadata (②) — replacing the hardcoded placeholder values."""
import pytest

import core


def test_provider_model_still_has_placeholder_defaults_without_metadata():
    """The guesses stay as a well-formed fallback; they are just no longer the only option."""
    model = core._provider_model("m1")
    assert model["contextWindow"] == 128000
    assert model["maxTokens"] == 16384
    assert model["cost"] == {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    assert model["reasoning"] is False


def test_provider_model_metadata_overrides_field_by_field():
    model = core._provider_model("m1", {"contextWindow": 200000, "reasoning": True})
    assert model["contextWindow"] == 200000
    assert model["reasoning"] is True
    assert model["maxTokens"] == 16384  # untouched keys keep the fallback
    assert model["id"] == "m1"


def test_provider_model_ignores_unknown_and_none_metadata():
    model = core._provider_model("m1", {"bogus": 1, "contextWindow": None})
    assert "bogus" not in model
    assert model["contextWindow"] == 128000


# --- builtin store as a metadata source ------------------------------------

def test_builtin_model_metadata_copies_from_the_store():
    """A gateway reselling z-ai/glm-5.2 should inherit pi's own description of it."""
    store = {"nvidia": {"models": [
        {"id": "z-ai/glm-5.2", "name": "GLM", "reasoning": True,
         "contextWindow": 200000, "maxTokens": 32768},
    ]}}
    meta = core.builtin_model_metadata("z-ai/glm-5.2", store)
    assert meta["contextWindow"] == 200000
    assert meta["maxTokens"] == 32768
    assert meta["reasoning"] is True
    assert "name" not in meta  # names are per-provider; only metadata is inherited


def test_builtin_model_metadata_absent_returns_empty():
    assert core.builtin_model_metadata("nope", core.load_models_store()) == {}
    assert core.builtin_model_metadata("", {"p": {"models": [{"id": "x"}]}}) == {}
    assert core.builtin_model_metadata("x", None) == {}
    assert core.builtin_model_metadata("x", {"p": {"models": "bad"}}) == {}


# --- /v1/models records as a metadata source -------------------------------

def test_metadata_from_remote_openrouter_shape():
    """OpenRouter: context_length + per-token pricing strings + top_provider."""
    meta = core.metadata_from_remote({
        "id": "x/y",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "top_provider": {"max_completion_tokens": 8192},
    })
    assert meta["contextWindow"] == 200000
    assert meta["maxTokens"] == 8192
    # per-token -> per-million, which is the unit pi's cost block uses
    assert meta["cost"]["input"] == 3.0
    assert meta["cost"]["output"] == 15.0
    assert meta["cost"]["cacheRead"] == 0


def test_metadata_from_remote_alternate_field_names():
    assert core.metadata_from_remote({"context_window": 65536})["contextWindow"] == 65536
    assert core.metadata_from_remote({"max_context_length": 8192})["contextWindow"] == 8192
    assert core.metadata_from_remote({"contextWindow": 4096})["contextWindow"] == 4096
    assert core.metadata_from_remote({"max_output_tokens": 999})["maxTokens"] == 999


def test_metadata_from_remote_reports_nothing_when_it_knows_nothing():
    """Silence beats a fabricated number — callers fall back explicitly."""
    assert core.metadata_from_remote({"id": "m1", "name": "M1"}) == {}
    assert core.metadata_from_remote("not a dict") == {}
    assert core.metadata_from_remote(None) == {}


def test_metadata_from_remote_rejects_junk_values():
    assert core.metadata_from_remote({"context_length": 0}) == {}
    assert core.metadata_from_remote({"context_length": -5}) == {}
    assert core.metadata_from_remote({"context_length": True}) == {}
    assert core.metadata_from_remote({"context_length": "many"}) == {}
    assert core.metadata_from_remote({"pricing": {"prompt": "free"}}) == {}


def test_metadata_from_remote_reads_reasoning_flag():
    assert core.metadata_from_remote({"reasoning": True})["reasoning"] is True
    assert core.metadata_from_remote({"supports_reasoning": False})["reasoning"] is False
    assert "reasoning" not in core.metadata_from_remote({"reasoning": "yes"})


def test_infer_prefers_builtin_over_remote():
    """pi authored the store, so it outranks whatever the gateway claims."""
    store = {"nvidia": {"models": [{"id": "m1", "contextWindow": 200000}]}}
    meta = core.infer_model_metadata(
        "m1", store=store, remote={"context_length": 8192, "max_output_tokens": 4096},
    )
    assert meta["contextWindow"] == 200000   # builtin wins
    assert meta["maxTokens"] == 4096         # remote fills the gap
    assert core.infer_model_metadata("unknown", store=store, remote=None) == {}


# --- fetch_remote_models carries metadata through --------------------------

def test_fetch_remote_models_attaches_metadata_when_present():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            import json
            return json.dumps({"data": [
                {"id": "rich", "context_length": 200000},
                {"id": "plain", "name": "Plain"},
            ]}).encode()

    models = core.fetch_remote_models("https://gw/v1", "", opener=lambda *a, **k: Response())
    rich, plain = models
    assert rich["meta"]["contextWindow"] == 200000
    # a record with nothing to report keeps the plain {id, name} shape
    assert plain == {"id": "plain", "name": "Plain"}


# --- add_provider_models threading metadata through ------------------------

def test_add_provider_models_uses_supplied_metadata():
    core.add_provider_models(
        "newapi", "fancy", ts="20260730-110000",
        metadata={"fancy": {"contextWindow": 1_000_000, "reasoning": True}},
    )
    model = next(m for m in core.load_custom()["providers"]["newapi"]["models"]
                 if m["id"] == "fancy")
    assert model["contextWindow"] == 1_000_000
    assert model["reasoning"] is True


def test_add_provider_models_without_metadata_is_unchanged():
    core.add_provider_models("newapi", "plain", ts="20260730-110001")
    model = next(m for m in core.load_custom()["providers"]["newapi"]["models"]
                 if m["id"] == "plain")
    assert model["contextWindow"] == 128000


# --- update_provider_model -------------------------------------------------

def test_update_provider_model_edits_metadata_and_backs_up():
    updated = core.update_provider_model(
        "newapi", "gpt-4o",
        {"contextWindow": 128001, "maxTokens": 4096, "reasoning": True, "name": "GPT-4o"},
        ts="20260730-110002",
    )
    assert updated["contextWindow"] == 128001
    assert updated["name"] == "GPT-4o"
    stored = core.load_custom()["providers"]["newapi"]["models"][0]
    assert stored["contextWindow"] == 128001
    assert stored["reasoning"] is True
    assert (core.switch_backups_dir() / "switch-20260730-110002").is_dir()


def test_update_provider_model_refuses_to_rename_the_id():
    """id is the key pi's defaultModel points at; changing it here would orphan that."""
    core.update_provider_model("newapi", "gpt-4o", {"id": "something-else"},
                               ts="20260730-110003")
    ids = {m["id"] for m in core.load_custom()["providers"]["newapi"]["models"]}
    assert ids == {"gpt-4o"}


def test_update_provider_model_missing_targets_return_none():
    assert core.update_provider_model("newapi", "ghost", {"maxTokens": 1}, ts="x") is None
    assert core.update_provider_model("ghost", "gpt-4o", {"maxTokens": 1}, ts="x") is None
    assert core.update_provider_model("newapi", "gpt-4o", {}, ts="x") is None
    with pytest.raises(ValueError):
        core.update_provider_model("newapi", "gpt-4o", "nope", ts="x")


def test_update_provider_model_noop_does_not_write():
    # The fixture's gpt-4o entry carries only id/name, so use name for the no-op check.
    before = core.load_custom()["providers"]["newapi"]["models"][0]["name"]
    assert core.update_provider_model("newapi", "gpt-4o", {"name": before},
                                      ts="20260730-110004") is not None
    assert not (core.switch_backups_dir() / "switch-20260730-110004").exists()


# --- display formatting ----------------------------------------------------

def test_format_context_window():
    assert core.format_context_window(128000) == "128K"
    assert core.format_context_window(1_048_576) == "1.0M"
    assert core.format_context_window(2_000_000) == "2.0M"
    assert core.format_context_window(512) == "512"
    assert core.format_context_window(0) == "—"
    assert core.format_context_window(-1) == "—"
    assert core.format_context_window(None) == "—"
    assert core.format_context_window(True) == "—"
    assert core.format_context_window("128000") == "—"


# --- editor form validation ------------------------------------------------

def test_parse_model_edits_reads_numbers_and_flags():
    changes = core.parse_model_edits({
        "name": " GPT-4o ", "contextWindow": "200000", "maxTokens": "8192",
        "reasoning": True, "costInput": "3", "costOutput": "15",
    })
    assert changes["name"] == "GPT-4o"
    assert changes["contextWindow"] == 200000
    assert changes["maxTokens"] == 8192
    assert changes["reasoning"] is True
    assert changes["cost"] == {"input": 3.0, "output": 15.0, "cacheRead": 0, "cacheWrite": 0}


def test_parse_model_edits_blank_number_means_unknown_not_zero():
    """Clearing the field must drop it, not assert a context window of 0."""
    changes = core.parse_model_edits({"contextWindow": "", "maxTokens": "  "})
    assert "contextWindow" not in changes
    assert "maxTokens" not in changes


def test_parse_model_edits_preserves_untouched_cost_keys():
    existing = {"cost": {"input": 1, "output": 2, "cacheRead": 9, "cacheWrite": 8}}
    changes = core.parse_model_edits({"costInput": "5"}, existing=existing)
    assert changes["cost"]["input"] == 5.0
    assert changes["cost"]["cacheRead"] == 9   # not clobbered by the editor's two fields
    assert changes["cost"]["cacheWrite"] == 8


def test_parse_model_edits_rejects_bad_input():
    for raw, match in (
        ({"contextWindow": "many"}, "整数"),
        ({"contextWindow": "0"}, "大于"),
        ({"contextWindow": "-5"}, "大于"),
        ({"maxTokens": "1.5"}, "整数"),
        ({"costInput": "free"}, "数字"),
        ({"costInput": "-1"}, "负"),
    ):
        with pytest.raises(ValueError, match=match):
            core.parse_model_edits(raw)
    with pytest.raises(ValueError):
        core.parse_model_edits("not a dict")


def test_parse_model_edits_empty_form_changes_nothing():
    assert core.parse_model_edits({}) == {}
    assert core.parse_model_edits({"name": "   "}) == {}
