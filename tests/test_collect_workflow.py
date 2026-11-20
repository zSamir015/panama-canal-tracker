"""Comprobaciones estáticas del workflow continuo `collect-ais.yml` y scripts macOS."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "collect-ais.yml"
RUN_WORKER_SCRIPT = REPO_ROOT / "scripts" / "macos" / "run_worker_caffeinate.sh"
MACOS_SCRIPTS = (
    RUN_WORKER_SCRIPT,
    REPO_ROOT / "scripts" / "macos" / "install_launchd_worker.sh",
)


def _load_workflow() -> dict[Any, Any]:
    loaded: object = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_collect_workflow_chaining_and_permissions() -> None:
    workflow = _load_workflow()
    # PyYAML parsea `on:` como True salvo comillas; aceptamos ambas claves.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers

    dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["chain"]["type"] == "boolean"
    assert dispatch_inputs["chain"]["default"] is True

    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {"group": "collect-ais", "cancel-in-progress": False}

    # El job con secretos no tiene permiso de escritura sobre Actions ni dispara nada.
    collect_job = workflow["jobs"]["collect"]
    assert collect_job["permissions"] == {"contents": "read"}
    for step in collect_job["steps"]:
        assert "gh workflow run" not in str(step.get("run", ""))
        uses = step.get("uses")
        if uses is not None:
            ref = uses.split("@", maxsplit=1)[1]
            sha = ref.split()[0]
            assert len(sha) == 40 and all(ch in "0123456789abcdef" for ch in sha)

    # El disparo de la siguiente ventana vive aislado, sin secretos, solo tras éxito y solo en main.
    chain_job = workflow["jobs"]["chain"]
    assert chain_job["needs"] == "collect"
    assert chain_job["timeout-minutes"] == 5
    assert chain_job["permissions"] == {"actions": "write"}
    cond = chain_job["if"]
    assert "needs.collect.result == 'success'" in cond
    assert "github.ref == 'refs/heads/main'" in cond

    chain_step = chain_job["steps"][0]
    assert chain_step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
    }
    assert "queued" in chain_step["run"]
    assert "gh workflow run collect-ais.yml --ref main" in chain_step["run"]


def test_macos_worker_scripts_syntax_and_security() -> None:
    bash_bin = shutil.which("bash") or "/bin/bash"
    for script in MACOS_SCRIPTS:
        assert script.is_file()
        assert os.access(script, os.X_OK), f"{script.name} debe ser ejecutable"
        result = subprocess.run(  # noqa: S603 (rutas fijas del repo, sin entrada externa)
            [bash_bin, "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{script.name}: {result.stderr}"

    worker_text = RUN_WORKER_SCRIPT.read_text(encoding="utf-8")
    assert "AIS_CANAL_BOUND_ENABLED=false" in worker_text
    assert "source " not in worker_text
    assert ". ./.env" not in worker_text
