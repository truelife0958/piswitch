import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def test_launcher_displays_help():
    result = subprocess.run(
        [str(REPO / "bin" / "piswitch"), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "piswitch list" in result.stdout


def test_installer_is_idempotent_in_temporary_home(tmp_path):
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    for _ in range(2):
        result = subprocess.run(
            [str(REPO / "install.sh")],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr

    launcher = tmp_path / ".local/bin/piswitch"
    desktop = tmp_path / ".local/share/applications/piswitch.desktop"
    icon = tmp_path / ".local/share/icons/piswitch.svg"
    assert launcher.is_symlink()
    assert launcher.resolve() == REPO / "bin" / "piswitch"
    assert f"Exec={launcher}" in desktop.read_text(encoding="utf-8")
    assert icon.read_text(encoding="utf-8") == (REPO / "assets/piswitch.svg").read_text(encoding="utf-8")
