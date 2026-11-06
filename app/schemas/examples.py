"""Ejemplos del esquema OpenAPI (tarea 7.3).

Cada modelo de petición y de respuesta lleva un ejemplo, que `/docs` enseña y que sirve de
documentación viva. Para que no mientan, `tests/test_openapi.py` valida cada ejemplo contra su
modelo y exige que todas las operaciones tengan resumen, descripción y ejemplos.

Los valores son inventados: MMSI de ejemplo, fechas del 6 de noviembre de 2026 y el correo
`demo@example.com` (nunca datos reales, AGENTS.md §7.1).
"""

from typing import Any

# (modelo, ejemplo): lo rellena `with_example`; lo lee el test.
REGISTRY: list[tuple[type, dict[str, Any]]] = []


def with_example(example: dict[str, Any]) -> Any:
    """Decorador de modelos Pydantic: añade el ejemplo al esquema JSON y lo registra."""

    def decorate(model: Any) -> Any:
        extra = {**(model.model_config.get("json_schema_extra") or {}), "examples": [example]}
        model.model_config = {**model.model_config, "json_schema_extra": extra}
        model.model_rebuild(force=True)
        REGISTRY.append((model, example))
        return model

    return decorate


# --- Auth -----------------------------------------------------------------------------------

USER_CREATE = {"email": "demo@example.com", "password": "una frase larga y fácil de recordar"}
LOGIN = {"email": "demo@example.com", "password": "una frase larga y fácil de recordar"}
TOKEN = {"access_token": "<jwt de acceso>", "token_type": "bearer", "expires_in": 900}
USER = {
    "id": "5b3f6c1e-2d4a-4e8b-9c7d-0a1b2c3d4e5f",
    "email": "demo@example.com",
    "role": "user",
    "created_at": "2026-11-06T12:00:00Z",
}

# --- Buques ---------------------------------------------------------------------------------

VESSEL = {
    "mmsi": 352001234,
    "name": "PACIFIC STAR",
    "imo": 9301234,
    "ship_type": 70,
    "length_m": 225.0,
    "beam_m": 32.0,
    "last_seen_at": "2026-11-06T11:58:00Z",
}
POSITION = {
    "received_at": "2026-11-06T11:58:00Z",
    "lat": 9.35,
    "lon": -79.91,
    "sog": 7.8,
    "cog": 145.2,
    "heading": 146.0,
    "nav_status": 0,
}
VESSEL_PAGE = {"items": [VESSEL], "total": 1, "page": 1, "size": 50}
VESSEL_DETAIL = {**VESSEL, "last_position": POSITION}
VESSEL_TRACK = {
    "type": "Feature",
    "geometry": {"type": "LineString", "coordinates": [[-79.70, 9.10], [-79.80, 9.20]]},
    "properties": {
        "mmsi": 352001234,
        "from": "2026-11-06T11:30:00Z",
        "to": "2026-11-06T12:00:00Z",
        "timestamps": ["2026-11-06T11:50:00Z", "2026-11-06T11:55:00Z"],
        "truncated": False,
    },
}
CANAL_BOUND_VESSEL = {
    "mmsi": 636012345,
    "name": "ATLANTIC DAWN",
    "imo": 9456789,
    "ship_type": 80,
    "length_m": 244.0,
    "destination": "PANAMA CANAL",
    "port_locode": "PA",
    "eta": "2026-11-08T06:00:00Z",
    "lat": 12.4,
    "lon": -81.3,
    "reported_at": "2026-11-06T10:00:00Z",
}
CANAL_BOUND_PAGE = {"items": [CANAL_BOUND_VESSEL], "total": 1, "page": 1, "size": 50}

# --- Tránsitos ------------------------------------------------------------------------------

TRANSIT = {
    "id": "3f0c2a52-7d11-4c0a-8d5e-9a1b2c3d4e5f",
    "mmsi": 352001234,
    "vessel_name": "PACIFIC STAR",
    "ship_type": 70,
    "direction": "southbound",
    "status": "completed",
    "abort_reason": None,
    "entered_at": "2026-11-06T02:00:00Z",
    "exited_at": "2026-11-06T08:45:00Z",
    "duration_minutes": 405,
}
TRANSIT_IN_PROGRESS = {
    **TRANSIT,
    "status": "in_progress",
    "exited_at": None,
    "duration_minutes": None,
}
TRANSIT_PAGE = {"items": [TRANSIT], "total": 1, "page": 1, "size": 50}
CURRENT_TRANSITS = {"items": [TRANSIT_IN_PROGRESS], "total": 1}
TRANSIT_DETAIL = {
    **TRANSIT,
    "anchorage_wait": {
        "anchorage": "atlantic",
        "arrived_at": "2026-11-05T14:00:00Z",
        "departed_at": "2026-11-06T01:50:00Z",
        "wait_minutes": 720,
    },
}

# --- Estadísticas ---------------------------------------------------------------------------

DISTRIBUTION = {"count": 54, "mean_minutes": 405.0, "p50_minutes": 398.0, "p90_minutes": 462.0}
EMPTY_DISTRIBUTION = {
    "count": 0,
    "mean_minutes": None,
    "p50_minutes": None,
    "p90_minutes": None,
}
DAILY_STATS = {
    "from": "2026-10-07T12:00:00Z",
    "to": "2026-11-06T12:00:00Z",
    "items": [
        {"date": "2026-11-04", "direction": "southbound", "ship_category": "cargo", "transits": 2},
        {"date": "2026-11-04", "direction": "northbound", "ship_category": "tanker", "transits": 1},
    ],
}
TRANSIT_DURATIONS = {
    "from": "2026-10-07T12:00:00Z",
    "to": "2026-11-06T12:00:00Z",
    "overall": DISTRIBUTION,
    "by_direction": {"northbound": EMPTY_DISTRIBUTION, "southbound": DISTRIBUTION},
}
WAITING_TIMES = {
    "from": "2026-10-07T12:00:00Z",
    "to": "2026-11-06T12:00:00Z",
    "overall": DISTRIBUTION,
    "by_anchorage": {"atlantic": DISTRIBUTION, "pacific": EMPTY_DISTRIBUTION},
}

# --- Infraestructura y administración -------------------------------------------------------

HEALTH = {"status": "ok"}
READY = {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}
READY_UNAVAILABLE = {"status": "unavailable", "checks": {"database": "ok", "redis": "failed"}}
INGESTION_STATUS = {
    "available": True,
    "stale": False,
    "age_seconds": 2.4,
    "status": {
        "updated_at": "2026-11-06T12:00:00Z",
        "connected": True,
        "subscribed": True,
        "connections": 1,
        "last_message_at": "2026-11-06T11:59:41Z",
        "last_error": None,
        "received": 1200,
        "queued": 1190,
        "queue_size": 3,
        "dropped": 0,
        "ignored": 0,
        "rejected": {"invalid_mmsi": 3},
        "batches": 40,
        "positions_written": 1150,
        "positions_duplicated": 2,
        "rows_rejected_by_db": 0,
        "batches_dropped": 0,
        "last_flush_at": "2026-11-06T11:59:58Z",
    },
}
METRICS_TEXT = (
    "# HELP canal_up La API responde.\n"
    "# TYPE canal_up gauge\n"
    "canal_up 1\n"
    "# HELP canal_ais_last_message_age_seconds Segundos desde el último mensaje de AISStream.\n"
    "# TYPE canal_ais_last_message_age_seconds gauge\n"
    "canal_ais_last_message_age_seconds 19\n"
)
PROBLEM = {
    "type": "about:blank",
    "title": "Not Found",
    "status": 404,
    "detail": "Buque no encontrado",
    "instance": "/api/v1/vessels/352001234",
    "request_id": "3fbf8d3ce72d477596e3ecdba5e675f7",
}
