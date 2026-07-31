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


def test_action_states_custom_provider_is_fully_editable():
    states = core.action_states(busy=False, selected=True, builtin=False, has_oauth=False)
    assert states["save"] is True
    assert states["test"] is True
    assert states["delete_provider"] is True
    assert states["add_model"] is True
    assert states["delete_model"] is True
    assert states["clear_models"] is True
    assert states["fetch_models"] is True
    assert states["logout"] is False       # no OAuth credentials to clear
    assert states["hide_builtin"] is False  # only builtins can be hidden
    assert states["set_default"] is True


def test_action_states_set_default_allowed_on_builtins():
    """Builtins are read-only config but valid pi defaults, so 设为默认 stays on."""
    builtin = core.action_states(busy=False, selected=True, builtin=True, has_oauth=False)
    assert builtin["set_default"] is True
    assert builtin["save"] is False
    # ...but there is nothing to point pi at until a provider is selected
    fresh = core.action_states(busy=False, selected=False, builtin=False, has_oauth=False)
    assert fresh["set_default"] is False


def test_action_states_builtin_provider_is_read_only():
    """Builtins live in models-store.json; piswitch must never offer to write them."""
    states = core.action_states(busy=False, selected=True, builtin=True, has_oauth=False)
    for key in ("save", "test", "delete_provider", "add_model", "delete_model",
                "clear_models", "fetch_models"):
        assert states[key] is False, key
    assert states["hide_builtin"] is True  # hiding from the list is still allowed


def test_action_states_busy_disables_everything():
    """While a request is in flight nothing that writes may be triggered."""
    states = core.action_states(busy=True, selected=True, builtin=False, has_oauth=True)
    assert not any(states.values())
    assert set(states) == set(core.ACTION_KEYS)


def test_action_states_new_provider_mode_allows_only_save_and_test():
    """No provider selected yet: save/test create it, per-provider actions cannot apply."""
    states = core.action_states(busy=False, selected=False, builtin=False, has_oauth=False)
    assert states["save"] is True
    assert states["test"] is True
    for key in ("delete_provider", "add_model", "delete_model", "clear_models", "fetch_models"):
        assert states[key] is False, key


def test_action_states_builtin_with_oauth_can_still_log_out():
    """A logged-in builtin (e.g. an extension-login provider) is read-only but log-out-able."""
    states = core.action_states(busy=False, selected=True, builtin=True, has_oauth=True)
    assert states["logout"] is True
    assert states["save"] is False
    assert states["hide_builtin"] is True


def test_action_states_busy_wins_over_oauth_and_builtin():
    """Regression: finishing a request must not re-enable buttons the selection forbids.

    The old GUI recomputed busy-state from `selected` alone, so a request started on a
    custom provider and completing after the user selected a builtin left save/delete
    enabled on that builtin.
    """
    assert core.action_states(busy=True, selected=True, builtin=True, has_oauth=True) == {
        key: False for key in core.ACTION_KEYS
    }


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


def test_is_builtin_provider_distinguishes_store():
    store = {"deepseek": {"models": [{"id": "a"}]}, "nvidia": {"models": []}}
    assert core.is_builtin_provider("deepseek", store) is True
    assert core.is_builtin_provider("nvidia", store) is True  # empty models list still counts
    assert core.is_builtin_provider("ark", store) is False  # custom-only
    assert core.is_builtin_provider("ghost", store) is False
    assert core.is_builtin_provider("x", {}) is False


def test_auth_kind_classifies_api_key_vs_oauth():
    apikey_auth = {"newapi": {"type": "api_key", "key": "sk-abc"}}
    oauth_auth = {"corp-x": {"access": "tok", "refresh": "r", "expires": 99999999999999}}
    # api_key via auth.json
    assert core.auth_kind("newapi", apikey_auth, {}) == "api_key"
    # api_key via custom models.json (no auth entry)
    custom_ak = {"providers": {"p": {"apiKey": "sk-zzz"}}}
    assert core.auth_kind("p", {}, custom_ak) == "api_key"
    # oauth via auth.json access token
    assert core.auth_kind("corp-x", oauth_auth, {}) == "oauth"
    # unknown provider / bare entry
    assert core.auth_kind("ghost", {}, {}) == ""
    assert core.auth_kind("x", {"x": {"type": "weird"}}, {}) == ""
    # has_key now True for OAuth too
    assert core.resolve_has_key("corp-x", oauth_auth, {}) is True
    assert core.resolve_has_key("corp-x", {"corp-x": {"access":""}}, {}) is False


def test_auth_login_state_tracks_expiry():
    far_future = 9_999_999_999_999
    assert core.auth_login_state("p", {"p": {"access": "t", "expires": far_future}}) == "logged_in"
    assert core.auth_login_state("p", {"p": {"access": "t", "expires": 1}}) == "expired"
    assert core.auth_login_state("p", {"p": {"access": "t"}}) == "logged_in"  # no expires → not-yet-expired
    assert core.auth_login_state("p", {"p": {"access": ""}}) == "none"
    assert core.auth_login_state("p", {}) == "none"
    assert core.auth_login_state("ghost", {"x": {}}) == "none"


def test_hidden_builtins_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("PISWITCH_DATA_DIR", str(tmp_path))
    assert core.load_hidden_builtins() == set()
    core.hide_builtin("nvidia"); core.hide_builtin("deepseek")
    assert core.load_hidden_builtins() == {"nvidia", "deepseek"}
    core.hide_builtin("nvidia")  # idempotent
    assert core.load_hidden_builtins() == {"nvidia", "deepseek"}
    core.unhide_builtin("nvidia")
    assert core.load_hidden_builtins() == {"deepseek"}
    core.unhide_builtin("never-was")  # unhide absent is no-op
    assert core.load_hidden_builtins() == {"deepseek"}


def test_hidden_builtins_recovers_from_corrupt_file(monkeypatch, tmp_path):
    monkeypatch.setenv("PISWITCH_DATA_DIR", str(tmp_path))
    tmp_path.joinpath("hidden_builtins.json").write_text("not json{", encoding="utf-8")
    assert core.load_hidden_builtins() == set()
    core.hide_builtin("x")  # write succeeds and recovers
    assert core.load_hidden_builtins() == {"x"}


def test_hidden_builtins_accepts_legacy_dict_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("PISWITCH_DATA_DIR", str(tmp_path))
    tmp_path.joinpath("hidden_builtins.json").write_text(
        '{"providers": ["a", "b"]}', encoding="utf-8")
    assert core.load_hidden_builtins() == {"a", "b"}


def test_text_matches_query_is_case_insensitive_and_ands_terms():
    assert core.text_matches_query("OPEN router", "OpenRouter", "https://openrouter.ai")
    assert core.text_matches_query("", "anything")
    assert not core.text_matches_query("open local", "OpenRouter", "remote gateway")


def test_auth_label_covers_every_auth_kind():
    custom = {"providers": {"p": {"api": "openai-completions"}}}
    key_auth = {"p": {"type": "api_key", "key": "sk-x"}}
    assert core.auth_label("p", key_auth, custom, builtin=False) == "API Key"
    assert core.auth_label("p", {}, custom, builtin=False) == "无"


def test_auth_label_reports_oauth_login_state():
    custom = {"providers": {"p": {}}}
    live = {"p": {"type": "oauth", "access": "t", "expires": 9_999_999_999_999}}
    dead = {"p": {"type": "oauth", "access": "t", "expires": 1}}
    assert core.auth_label("p", live, custom, builtin=False) == "已登录"
    assert core.auth_label("p", dead, custom, builtin=False) == "已过期"


def test_auth_label_prefixes_builtin_and_collapses_empty():
    custom = {"providers": {}}
    key_auth = {"p": {"type": "api_key", "key": "sk-x"}}
    assert core.auth_label("p", key_auth, custom, builtin=True) == "内置·API Key"
    # 无凭据的内置只显示「内置」，不显示「内置·无」
    assert core.auth_label("p", {}, custom, builtin=True) == "内置"


def _rows_by_id(rows):
    return {r["provider"]: r for r in rows}


def test_provider_rows_merges_custom_over_builtin_of_same_id():
    custom = {"providers": {"dup": {"name": "我的", "models": [1, 2]}}}
    store = {"dup": {"name": "内置的", "models": [1]}, "only": {"models": []}}
    rows = core.provider_rows(custom, {}, store, default_provider=None,
                              health={}, hidden=set())
    by_id = _rows_by_id(rows)
    # 同名自定义覆盖内置，列表里只出现一次，用自定义的名字和模型数
    assert len(rows) == 2
    assert by_id["dup"]["values"][1] == "我的"
    assert by_id["dup"]["values"][2] == 2
    # 覆盖内置的自定义条目仍计入自定义
    assert by_id["dup"]["custom"] is True
    assert by_id["only"]["custom"] is False


def test_provider_rows_hides_listed_builtins_only():
    custom = {"providers": {"mine": {"models": []}}}
    store = {"gone": {"models": []}, "kept": {"models": []}}
    rows = core.provider_rows(custom, {}, store, default_provider=None,
                              health={}, hidden={"gone", "mine"})
    # hidden 只对内置生效，自定义供应商不受影响
    assert set(_rows_by_id(rows)) == {"mine", "kept"}


def test_provider_rows_stars_the_default_and_keeps_health():
    custom = {"providers": {"a": {"name": "A", "models": []},
                            "b": {"name": "B", "models": []}}}
    rows = core.provider_rows(custom, {}, {}, default_provider="b",
                              health={"a": "✓ 120ms"}, hidden=set())
    by_id = _rows_by_id(rows)
    assert by_id["b"]["values"][1] == "★ B"
    assert by_id["a"]["values"][1] == "A"
    assert by_id["a"]["values"][4] == "✓ 120ms"
    assert by_id["b"]["values"][4] == ""


def test_provider_rows_tolerates_malformed_entries():
    custom = {"providers": {"ok": {"models": []}, "bad": "not a dict"}}
    store = {"okstore": {"models": []}, "badstore": ["nope"]}
    rows = core.provider_rows(custom, {}, store, default_provider=None,
                              health={}, hidden=set())
    assert set(_rows_by_id(rows)) == {"ok", "okstore"}


def test_provider_rows_counts_non_list_models_as_zero():
    custom = {"providers": {"x": {"models": "oops"}}}
    rows = core.provider_rows(custom, {}, {}, default_provider=None,
                              health={}, hidden=set())
    assert rows[0]["values"][2] == 0


def test_load_snapshot_reads_each_config_once(monkeypatch):
    calls: list[str] = []
    original = core.store.read_json

    def counting(path, default):
        calls.append(str(path))
        return original(path, default)

    monkeypatch.setattr(core.store, "read_json", counting)
    snap = core.load_snapshot()
    # 四个配置文件各读一次，不多不少
    assert len(calls) == len(set(calls)) == 4
    assert isinstance(snap.custom.get("providers"), dict)
    assert isinstance(snap.hidden, set)
