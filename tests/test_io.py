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
