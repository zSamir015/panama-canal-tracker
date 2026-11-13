"""Métricas y disponibilidad (tarea 7.1): formato de Prometheus, métricas del worker y token."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.schemas.ingestion import IngestionStatusResponse, WorkerStatus
from app.services.metrics import (
    Metric,
    Readiness,
    Sample,
    counter,
    gauge,
    render,
    worker_metrics,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parent.parent

# Una línea del formato de exposición: nombre, etiquetas opcionales y un valor numérico.
SAMPLE_LINE = re.compile(
    r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[a-z_]+="[^"\\\n]*"(,[a-z_]+="[^"\\\n]*")*\})? -?\d+(\.\d+)?$'
)


def worker_status(**overrides: Any) -> WorkerStatus:
    values: dict[str, Any] = {
        "updated_at": NOW,
        "connected": True,
        "subscribed": True,
        "connections": 1,
        "last_message_at": NOW - timedelta(seconds=42),
        "last_error": None,
        "received": 120,
        "queued": 118,
        "queue_size": 3,
        "dropped": 2,
        "ignored": 0,
        "rejected": {},
        "batches": 10,
        "positions_written": 115,
        "positions_duplicated": 1,
        "rows_rejected_by_db": 0,
        "batches_dropped": 0,
        "last_flush_at": NOW,
    }
    return WorkerStatus(**(values | overrides))


def by_name(metrics: list[Metric]) -> dict[str, float]:
    return {metric.name: metric.samples[0].value for metric in metrics}


# --- Formato --------------------------------------------------------------------------------


def test_render_writes_help_type_and_one_line_per_sample() -> None:
    text = render(
        [
            gauge("canal_up", "La API responde.", 1),
            counter("canal_ais_messages_received_total", "Mensajes.", 120),
            Metric(
                "canal_dependency_up",
                "Dependencias.",
                "gauge",
                (Sample(1, (("name", "database"),)), Sample(0, (("name", "redis"),))),
            ),
        ]
    )

    assert text == (
        "# HELP canal_up La API responde.\n"
        "# TYPE canal_up gauge\n"
        "canal_up 1\n"
        "# HELP canal_ais_messages_received_total Mensajes.\n"
        "# TYPE canal_ais_messages_received_total counter\n"
        "canal_ais_messages_received_total 120\n"
        "# HELP canal_dependency_up Dependencias.\n"
        "# TYPE canal_dependency_up gauge\n"
        'canal_dependency_up{name="database"} 1\n'
        'canal_dependency_up{name="redis"} 0\n'
    )


def test_every_sample_line_has_a_valid_shape() -> None:
    text = render(
        worker_metrics(IngestionStatusResponse(available=True, status=worker_status()), NOW)
    )

    for line in text.splitlines():
        assert line.startswith("# ") or SAMPLE_LINE.match(line), line


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (3, "3"), (42.0, "42"), (42.5, "42.5"), (0.1, "0.1")],
)
def test_numbers_are_written_without_a_useless_decimal_point(value: float, expected: str) -> None:
    assert render([gauge("x", "x", value)]).splitlines()[-1] == f"x {expected}"


def test_label_values_are_escaped() -> None:
    text = render([Metric("x", "x", "gauge", (Sample(1, (("name", 'a"b\\c'),)),))])

    assert text.splitlines()[-1] == 'x{name="a\\"b\\\\c"} 1'


# --- Métricas del worker --------------------------------------------------------------------


def test_worker_metrics_report_counters_and_the_age_of_the_last_message() -> None:
    metrics = worker_metrics(IngestionStatusResponse(available=True, status=worker_status()), NOW)

    assert by_name(metrics) == {
        "canal_ais_worker_available": 1,
        "canal_ais_worker_connected": 1,
        "canal_ais_queue_size": 3,
        "canal_ais_messages_received_total": 120,
        "canal_ais_messages_dropped_total": 2,
        "canal_ais_positions_written_total": 115,
        "canal_ais_batches_dropped_total": 0,
        "canal_ais_last_message_age_seconds": 42.0,
    }
    assert {m.name: m.type for m in metrics}["canal_ais_messages_received_total"] == "counter"


def test_a_stopped_worker_is_unavailable_and_has_no_other_metrics() -> None:
    metrics = worker_metrics(IngestionStatusResponse(available=False), NOW)

    assert by_name(metrics) == {"canal_ais_worker_available": 0}


def test_a_stale_status_counts_as_unavailable_but_keeps_what_it_knows() -> None:
    status = IngestionStatusResponse(
        available=True, stale=True, age_seconds=90.0, status=worker_status(connected=False)
    )

    values = by_name(worker_metrics(status, NOW))

    assert values["canal_ais_worker_available"] == 0
    assert values["canal_ais_worker_connected"] == 0


def test_without_any_message_there_is_no_age_to_report() -> None:
    status = IngestionStatusResponse(
        available=True, status=worker_status(last_message_at=None, received=0)
    )

    assert "canal_ais_last_message_age_seconds" not in by_name(worker_metrics(status, NOW))


def test_the_age_never_goes_negative_when_clocks_disagree() -> None:
    future = worker_status(last_message_at=NOW + timedelta(seconds=5))

    values = by_name(worker_metrics(IngestionStatusResponse(available=True, status=future), NOW))

    assert values["canal_ais_last_message_age_seconds"] == 0.0


def test_readiness_needs_both_dependencies() -> None:
    assert Readiness(database=True, redis=True).ready
    assert not Readiness(database=True, redis=False).ready
    assert not Readiness(database=False, redis=True).ready


# --- Token ----------------------------------------------------------------------------------


def test_the_metrics_token_is_optional_and_masked() -> None:
    assert Settings(_env_file=None).metrics_token is None
    token = Settings(_env_file=None, metrics_token="x" * 40).metrics_token

    assert isinstance(token, SecretStr)
    assert "x" * 10 not in repr(token)


def test_a_short_metrics_token_is_rejected_without_echoing_it() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, metrics_token="corto-pero-secreto")

    assert "METRICS_TOKEN" in str(error.value)
    assert "corto-pero-secreto" not in str(error.value)


# --- Reglas de alerta -----------------------------------------------------------------------


def load_rules() -> dict[str, dict[str, Any]]:
    document = yaml.safe_load((ROOT / "docker" / "prometheus" / "canal-alerts.yml").read_text())
    return {rule["alert"]: rule for group in document["groups"] for rule in group["rules"]}


def test_the_alert_rules_cover_a_silent_worker_for_more_than_five_minutes() -> None:
    rules = load_rules()

    assert set(rules) == {
        "CanalAisWorkerDown",
        "CanalAisNoMessages",
        "CanalAisNoMessagesSinceStart",
        "CanalDependencyDown",
    }
    assert rules["CanalAisNoMessages"]["expr"].strip() == "canal_ais_last_message_age_seconds > 300"
    assert rules["CanalAisNoMessagesSinceStart"]["for"] == "5m"


def test_every_metric_the_rules_use_is_one_the_api_exports() -> None:
    exported = {
        metric.name
        for metric in [
            *worker_metrics(IngestionStatusResponse(available=True, status=worker_status()), NOW),
            gauge("canal_up", "", 1),
            gauge("canal_dependency_up", "", 1),
        ]
    }
    used = {
        name
        for rule in load_rules().values()
        for name in re.findall(r"canal_[a-z_]+", rule["expr"])
    }

    assert used <= exported, used - exported


def test_every_alert_has_severity_and_a_summary() -> None:
    for name, rule in load_rules().items():
        assert rule["labels"]["severity"] in {"warning", "critical"}, name
        assert rule["annotations"]["summary"], name
