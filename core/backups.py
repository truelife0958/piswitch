"""Pre-mutation snapshots and restore."""
from __future__ import annotations

from pathlib import Path
import shutil

from .paths import auth_path, models_path, settings_path, switch_backups_dir
from .store import read_json, write_json_bundle

BACKUP_RETENTION = 20


def light_backup(ts: str) -> Path:
    dest = switch_backups_dir() / f"switch-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for p in (settings_path(), models_path(), auth_path()):
        if p.exists():
            shutil.copy2(p, dest / p.name)
    backups = sorted(
        path for path in switch_backups_dir().glob("switch-*")
        if path.is_dir()
    )
    for old_backup in backups[:-BACKUP_RETENTION]:
        shutil.rmtree(old_backup, ignore_errors=True)
    return dest


def list_switch_backups() -> list[Path]:
    return sorted(
        (
            path for path in switch_backups_dir().glob("switch-*")
            if path.is_dir()
        ),
        reverse=True,
    )


def restore_switch_backup(backup: Path, *, ts: str) -> list[str]:
    backup = Path(backup).resolve()
    backup_root = switch_backups_dir().resolve()
    if backup.parent != backup_root or not backup.name.startswith("switch-") or not backup.is_dir():
        raise ValueError("invalid backup directory")

    targets = {
        "settings.json": settings_path(),
        "models.json": models_path(),
        "auth.json": auth_path(),
    }
    snapshot = {}
    for name in targets:
        source = backup / name
        if source.exists():
            snapshot[name] = read_json(source, {})
    if not snapshot:
        raise ValueError("backup does not contain configuration files")

    light_backup(ts)
    write_json_bundle([(targets[name], data) for name, data in snapshot.items()])
    return list(snapshot)
