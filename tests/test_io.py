import json
from pathlib import Path
import pytest
import core


def test_paths_follow_env(pi_env):
    assert core.agent_dir() == pi_env["agent"]
    assert core.data_dir() == pi_env["data"]
    assert core.settings_path() == pi_env["agent"] / "settings.json"
    assert core.presets_path() == pi_env["data"] / "presets.json"
    assert core.switch_backups_dir() == pi_env["data"] / "backups"


def test_read_json_missing_returns_default():
    assert core.read_json(core.data_dir() / "nope.json", {"x": 1}) == {"x": 1}


def test_read_json_corrupt_raises(pi_env):
    bad = pi_env["agent"] / "settings.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        core.read_json(bad, {})


def test_write_json_atomic_roundtrip_and_mkdir(pi_env):
    target = pi_env["data"] / "sub" / "out.json"
    core.write_json_atomic(target, {"a": [1, 2], "中文": "值"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": [1, 2], "中文": "值"}


def test_write_json_atomic_preserves_mode(pi_env):
    target = pi_env["agent"] / "settings.json"
    target.chmod(0o600)
    core.write_json_atomic(target, {"k": "v"})
    assert (target.stat().st_mode & 0o777) == 0o600


def test_write_json_bundle_rolls_back_prior_files(monkeypatch, pi_env):
    first = pi_env["agent"] / "models.json"
    second = pi_env["agent"] / "auth.json"
    original_first = core.read_json(first, {})
    original_second = core.read_json(second, {})
    real_write = core.write_json_atomic
    failed = False

    def fail_second_once(path, data):
        nonlocal failed
        if Path(path) == second and not failed:
            failed = True
            raise OSError("simulated write failure")
        real_write(path, data)

    monkeypatch.setattr(core, "write_json_atomic", fail_second_once)
    with pytest.raises(OSError, match="simulated"):
        core.write_json_bundle([(first, {"changed": True}), (second, {"changed": True})])

    assert core.read_json(first, {}) == original_first
    assert core.read_json(second, {}) == original_second


def test_load_custom_self_heals_legacy_openai_compat(pi_env):
    # Regression: a provider saved before the safe-default code shipped had no
    # compat block, so pi sent prompt_cache_key upstream and got HTTP 400.
    legacy = {"providers": {"elysiver": {
        "name": "elysiver", "api": "openai-completions",
        "baseUrl": "https://elysiver.example/v1",
        "apiKey": "sk-legacy",
        "models": [{"id": "glm-5.2", "name": "glm-5.2"}],
    }, "ark": {
        "name": "ark", "api": "openai-completions",
        "compat": {"sendSessionAffinityHeaders": True},  # missing long-cache key
    }}}
    (pi_env["agent"] / "models.json").write_text(json.dumps(legacy), encoding="utf-8")

    loaded = core.load_custom()
    assert loaded["providers"]["elysiver"]["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }
    assert loaded["providers"]["ark"]["compat"] == {
        "sendSessionAffinityHeaders": True,
        "supportsLongCacheRetention": False,
    }

    # The backfill is idempotent across reads.
    core.load_custom()
