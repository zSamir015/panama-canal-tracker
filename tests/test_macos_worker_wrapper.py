"""`scripts/macos/run_worker_caffeinate.sh`: la comprobación previa de servicios (issue #172)."""

import os
import re
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "scripts" / "macos" / "run_worker_caffeinate.sh"


def _preflight_code() -> str:
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", WRAPPER.read_text(), flags=re.S)
    assert match is not None
    return match.group(1)


def _run(tmp_path: Path, port: int, key: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO),
        "AISSTREAM_API_KEY": key,
        "DATABASE_URL": f"postgresql+asyncpg://user:pass@127.0.0.1:{port}/db",
        "REDIS_URL": f"redis://:pass@127.0.0.1:{port}/0",
    }
    # cwd sin `.env`: solo cuentan las variables de arriba.
    return subprocess.run(  # noqa: S603 (código del propio repo, sin entrada externa)
        [sys.executable, "-c", _preflight_code()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_preflight_passes_when_database_and_redis_accept_connections(tmp_path: Path) -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        result = _run(tmp_path, server.getsockname()[1], "real-looking-key")
    assert result.returncode == 0, result.stderr


def test_preflight_rejects_placeholder_key(tmp_path: Path) -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        result = _run(tmp_path, server.getsockname()[1], "simulator")
    assert result.returncode == 1
    assert "AISSTREAM_API_KEY" in result.stderr
