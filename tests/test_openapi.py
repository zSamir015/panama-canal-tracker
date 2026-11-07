"""OpenAPI completo (tarea 7.3): resumen, descripción y ejemplos en todas las operaciones.

Si alguien añade un endpoint sin documentarlo, o cambia un modelo y deja su ejemplo viejo, este
archivo falla.
"""

import json
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app
from app.schemas.examples import REGISTRY

JSON = "application/json"
PROBLEM_JSON = "application/problem+json"
# Los nombres de los atributos Python que la API publica con otro nombre (`serialization_alias`).
UNALIAS = {"from": "start", "to": "end", "date": "day"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    app: FastAPI = create_app(Settings(_env_file=None, app_env="test"))
    return app.openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
    ]


def resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    return resolve(spec, spec["components"]["schemas"][ref.rsplit("/", 1)[1]])


def has_example(spec: dict[str, Any], media: dict[str, Any]) -> bool:
    if "example" in media or "examples" in media:
        return True
    schema = resolve(spec, media.get("schema", {}))
    return bool(schema.get("examples") or "example" in schema)


def test_the_spec_lists_every_route(spec: dict[str, Any]) -> None:
    # Si el esquema saliera vacío, los demás tests pasarían sin comprobar nada.
    assert len(operations(spec)) >= 19


def test_every_operation_has_summary_and_description(spec: dict[str, Any]) -> None:
    missing = [
        f"{method} {path}"
        for method, path, op in operations(spec)
        if not op.get("summary") or not op.get("description")
    ]

    assert missing == []


def test_every_json_response_and_request_body_has_an_example(spec: dict[str, Any]) -> None:
    missing: list[str] = []
    for method, path, op in operations(spec):
        for code, response in op["responses"].items():
            if not code.startswith("2"):
                continue
            for media_type, media in response.get("content", {}).items():
                if not has_example(spec, media):
                    missing.append(f"{method} {path} {code} {media_type}")
        for media_type, media in op.get("requestBody", {}).get("content", {}).items():
            if not has_example(spec, media):
                missing.append(f"{method} {path} request {media_type}")

    assert missing == []


def test_every_documented_error_has_an_example(spec: dict[str, Any]) -> None:
    missing: list[str] = []
    for method, path, op in operations(spec):
        for code, response in op["responses"].items():
            if not code.startswith(("4", "5")):
                continue
            medias = response.get("content", {})
            if not medias or not all(has_example(spec, media) for media in medias.values()):
                missing.append(f"{method} {path} {code}")

    assert missing == []


def test_a_problem_example_has_the_shape_the_api_really_returns(spec: dict[str, Any]) -> None:
    example = spec["paths"]["/api/v1/vessels/{mmsi}"]["get"]["responses"]["404"]["content"][
        PROBLEM_JSON
    ]["example"]

    assert set(example) == {"type", "title", "status", "detail", "instance", "request_id"}
    assert example["status"] == 404 and example["title"] == "Not Found"
    assert example["instance"] == "/api/v1/vessels/{mmsi}"


def test_the_validation_error_example_lists_where_it_failed(spec: dict[str, Any]) -> None:
    content = spec["paths"]["/api/v1/vessels"]["get"]["responses"]["422"]["content"]
    example = content[PROBLEM_JSON]["example"]

    assert example["status"] == 422
    assert set(example["errors"][0]) == {"loc", "msg", "type"}  # nunca el valor recibido


def test_the_metrics_example_is_prometheus_text(spec: dict[str, Any]) -> None:
    text = spec["paths"]["/metrics"]["get"]["responses"]["200"]["content"]["text/plain"]["example"]

    assert text.startswith("# HELP canal_up") and "\ncanal_up 1\n" in text


# --- Los ejemplos no mienten ----------------------------------------------------------------


def unalias(value: Any) -> Any:
    if isinstance(value, dict):
        return {UNALIAS.get(key, key): unalias(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unalias(item) for item in value]
    return value


@pytest.mark.parametrize(("model", "example"), REGISTRY, ids=[m.__name__ for m, _ in REGISTRY])
def test_every_example_validates_against_its_model(model: Any, example: dict[str, Any]) -> None:
    validated = model.model_validate(unalias(example))

    # Y al serializarlo (con los alias de la API) da el mismo JSON que el ejemplo.
    assert json.loads(validated.model_dump_json(by_alias=True)) == json.loads(json.dumps(example))


def test_every_documented_model_appears_in_the_registry(spec: dict[str, Any]) -> None:
    registered = {model.__name__ for model, _ in REGISTRY}
    in_spec = {
        resolve_name
        for _, _, op in operations(spec)
        for media in [
            *(r.get("content", {}).get(JSON, {}) for r in op["responses"].values()),
            op.get("requestBody", {}).get("content", {}).get(JSON, {}),
        ]
        if (resolve_name := media.get("schema", {}).get("$ref", "").rsplit("/", 1)[-1])
    }

    assert in_spec - {"HTTPValidationError"} <= registered, in_spec - registered
