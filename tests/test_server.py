"""Smoke test del criterio de la Fase 1: `uvicorn app.main:app` levanta y `GET /health` → 200."""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def server() -> Iterator[tuple[str, subprocess.Popen[str]]]:
    port = free_port()
    env = {**os.environ, "APP_ENV": "test", "LOG_LEVEL": "INFO"}
    process = subprocess.Popen(  # noqa: S603 (comando fijo, sin entrada externa)
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                httpx.get(f"{base_url}/health", timeout=1)
                break
            except httpx.TransportError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        yield base_url, process
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_uvicorn_serves_health_and_logs_json(server: tuple[str, subprocess.Popen[str]]) -> None:
    base_url, process = server

    response = httpx.get(f"{base_url}/health")
    process.terminate()
    output, _ = process.communicate(timeout=10)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    records = [json.loads(line) for line in output.splitlines()]
    access = [r for r in records if r.get("logger") == "uvicorn.access"]
    assert access, output
    assert access[-1]["request_id"] == response.headers["x-request-id"]
