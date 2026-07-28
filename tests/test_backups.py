import core


def test_light_backup_retains_latest_twenty():
    for index in range(22):
        core.light_backup(f"20260728-{index:06d}")
    backups = core.list_switch_backups()
    assert len(backups) == core.BACKUP_RETENTION == 20
    assert backups[0].name == "switch-20260728-000021"
    assert backups[-1].name == "switch-20260728-000002"


def test_restore_switch_backup_restores_configuration():
    backup = core.light_backup("20260728-110000")
    core.write_json_atomic(core.models_path(), {"providers": {}})
    core.write_json_atomic(core.auth_path(), {})

    restored = core.restore_switch_backup(backup, ts="20260728-110001")
    assert set(restored) == {"settings.json", "models.json", "auth.json"}
    assert "newapi" in core.load_custom()["providers"]
    assert "deepseek" in core.load_auth()


def test_restore_rejects_directory_outside_backup_root(tmp_path):
    with __import__("pytest").raises(ValueError, match="invalid backup"):
        core.restore_switch_backup(tmp_path, ts="20260728-110002")


def test_default_target_detection():
    assert core.is_default_provider("nvidia") is True
    assert core.is_default_provider("newapi") is False
    assert core.is_default_model("nvidia", "z-ai/glm-5.2") is True
    assert core.is_default_model("nvidia", "other") is False
    assert core.is_default_provider("nvidia", settings={}) is False
