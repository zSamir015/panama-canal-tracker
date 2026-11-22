"""`scripts/macos/run_db_backup.sh`: contraseña del Keychain y contenedor `db` (issue #182)."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "scripts" / "macos" / "run_db_backup.sh"


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path, *, keychain_ok: bool, db_running: bool
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(
        bin_dir / "security", 'echo "p4ssphrase-de-prueba-0123456789"' if keychain_ok else "exit 44"
    )
    # `docker compose ps --status running --services`: lista `db` solo si está en marcha.
    _executable(bin_dir / "docker", "echo db" if db_running else "exit 0")
    _executable(bin_dir / "sleep", "exit 0")  # sin esperas reales en el test
    stub = tmp_path / "backup_stub.sh"
    _executable(stub, 'echo "dir=$1 keep=$BACKUP_KEEP_DAYS pass=${#BACKUP_PASSPHRASE}"')
    env = {
        # Los dobles van primero: el wrapper solo añade rutas al final del PATH.
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "USER": "tester",
        "BACKUP_SCRIPT": str(stub),
    }
    return subprocess.run(  # noqa: S603 (script del propio repo con dobles locales)
        ["/bin/bash", str(WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_runs_the_backup_with_the_keychain_passphrase_and_14_day_retention(tmp_path: Path) -> None:
    result = _run(tmp_path, keychain_ok=True, db_running=True)
    assert result.returncode == 0, result.stderr
    assert f"dir={tmp_path}/Backups/panama-canal-tracker keep=14 pass=31" in result.stdout


def test_fails_without_the_keychain_item_and_does_not_back_up(tmp_path: Path) -> None:
    result = _run(tmp_path, keychain_ok=False, db_running=True)
    assert result.returncode == 1
    assert "Keychain" in result.stderr
    assert "dir=" not in result.stdout


def test_fails_when_the_db_container_is_not_running(tmp_path: Path) -> None:
    result = _run(tmp_path, keychain_ok=True, db_running=False)
    assert result.returncode == 1
    assert "db" in result.stderr
    assert "dir=" not in result.stdout


@pytest.mark.parametrize("script", ["run_db_backup.sh", "install_launchd_backup.sh"])
def test_scripts_have_valid_bash_syntax(script: str) -> None:
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", "-n", str(REPO / "scripts" / "macos" / script)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
