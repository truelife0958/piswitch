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
    assert cfg["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }
    ids = [m["id"] for m in cfg["models"]]
    assert "gpt-4o" in ids
    assert cfg["models"][0]["contextWindow"] == 128000  # 默认字段存在


def test_build_custom_provider_cfg_preserves_explicit_compat():
    cfg = core.build_custom_provider_cfg({
        "name": "Gateway",
        "provider": "gateway",
        "model": "m1",
        "baseUrl": "https://gw/v1",
        "api": "openai-completions",
        "compat": {"sendSessionAffinityHeaders": False},
    })
    assert cfg["compat"] == {
        "sendSessionAffinityHeaders": False,
        "supportsLongCacheRetention": False,
    }


def test_merge_openai_proxy_compat_preserves_all_explicit_settings():
    compat = core.merge_openai_proxy_compat({
        "sendSessionAffinityHeaders": False,
        "supportsLongCacheRetention": True,
        "supportsUsageInStreaming": False,
    })
    assert compat == {
        "sendSessionAffinityHeaders": False,
        "supportsLongCacheRetention": True,
        "supportsUsageInStreaming": False,
    }


def test_backfill_proxy_compat_adds_defaults_to_legacy_openai_providers():
    # A provider saved before the safe-default code shipped: no compat block at all.
    data = {"providers": {"elysiver": {
        "name": "elysiver", "api": "openai-completions", "baseUrl": "https://gw/v1",
    }}}
    assert core.backfill_proxy_compat(data) is True
    assert data["providers"]["elysiver"]["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }


def test_backfill_proxy_compat_partially_filled_block():
    # e.g. ark: sendSessionAffinityHeaders present but long-cache default missing.
    data = {"providers": {"ark": {
        "name": "ark", "api": "openai-completions",
        "compat": {"sendSessionAffinityHeaders": True},
    }}, "other": {"x": 1}}
    assert core.backfill_proxy_compat(data) is True
    assert data["providers"]["ark"]["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }
    assert data["other"] == {"x": 1}  # untouched global structure


def test_backfill_proxy_compat_preserves_explicit_overrides():
    # A user who opted OUT of affinity headers should not be re-enabled.
    data = {"providers": {"p": {
        "api": "openai-completions",
        "compat": {
            "sendSessionAffinityHeaders": False,
            "supportsLongCacheRetention": True,
            "supportsUsageInStreaming": False,
        },
    }}, "providers_store": {"nvidia": {}}}
    assert core.backfill_proxy_compat(data) is False
    assert data["providers"]["p"]["compat"] == {
        "sendSessionAffinityHeaders": False,
        "supportsLongCacheRetention": True,
        "supportsUsageInStreaming": False,
    }


def test_backfill_proxy_compat_skips_non_openai_providers():
    data = {"providers": {"anth": {
        "api": "anthropic-messages", "compat": {"supportsLongCacheRetention": True},
    }}, "providers_store": {"the same": {}}}
    assert core.backfill_proxy_compat(data) is False
    assert data["providers"]["anth"]["compat"] == {"supportsLongCacheRetention": True}


def test_backfill_proxy_compat_tolerates_bad_input():
    assert core.backfill_proxy_compat(None) is False
    assert core.backfill_proxy_compat("not a dict") is False
    assert core.backfill_proxy_compat({"providers": "oops"}) is False
    assert core.backfill_proxy_compat({"providers": {"p": "oops"}}) is False


def test_range_toggle_targets_forward_span_unifies_to_target():
    """Shift+click forward: rows 2..5 get unified to whatever the click toggles."""
    iids = list("0123456789")
    selected = {"2", "4"}  # row 4 already checked
    is_selected = lambda i: i in selected
    # Click row 5 (currently unchecked) → toggles to checked; range [2..5] unified to True.
    plan = core.range_toggle_targets(iids, "2", "5", is_selected)
    assert plan == [("2", True), ("3", True), ("4", True), ("5", True)]


def test_range_toggle_targets_backward_span_works():
    """Shift+click earlier row: the span is reversed but still toggles uniformly."""
    iids = list("0123456789")
    selected = set()  # anchor row 7 checked, click row 2 unchecked → unify to True
    is_selected = lambda i: i == "7"
    plan = core.range_toggle_targets(iids, "7", "2", is_selected)
    assert plan == [(iid, True) for iid in ("2", "3", "4", "5", "6", "7")]


def test_range_toggle_targets_click_clears_the_span():
    """If anchor row is checked and click row is checked, the click unchecks it;
    spanning rows get unified to unchecked."""
    iids = list("0123456789")
    selected = {"1", "2", "3"}
    plan = core.range_toggle_targets(iids, "1", "3", lambda i: i in selected)
    assert plan == [("1", False), ("2", False), ("3", False)]


def test_range_toggle_targets_anchor_equals_click_degenerate():
    """A span of one row is just that row's toggle."""
    iids = list("abcde")
    plan = core.range_toggle_targets(iids, "b", "b", lambda i: False)
    assert plan == [("b", True)]


def test_range_toggle_targets_unknown_iids_returns_empty():
    iids = list("abcde")
    assert core.range_toggle_targets(iids, "zzz", "a", lambda i: False) == []
    assert core.range_toggle_targets(iids, "a", "zzz", lambda i: False) == []
    assert core.range_toggle_targets([], "a", "b", lambda i: False) == []


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
