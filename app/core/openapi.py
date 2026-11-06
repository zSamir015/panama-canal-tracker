"""Retoques del esquema OpenAPI que no caben en cada endpoint (tarea 7.3).

Todos los errores de la API son `application/problem+json` (RFC 9457) con la misma forma. En vez
de repetir un ejemplo en cada `responses=` de cada router, se completa aquí: cada respuesta de
error documentada recibe un ejemplo con su código, su título y la ruta, y el `detail` que ya
tenía como descripción.
"""

from http import HTTPStatus
from typing import Any

from app.core.errors import DEFAULT_DETAILS
from app.schemas.examples import PROBLEM

PROBLEM_JSON = "application/problem+json"


def add_problem_examples(spec: dict[str, Any]) -> dict[str, Any]:
    """Añade un ejemplo a cada respuesta `problem+json` que no lo tenga. Modifica `spec`."""
    for path, operations in spec.get("paths", {}).items():
        for operation in operations.values():
            for code, response in operation.get("responses", {}).items():
                if code == "422" and PROBLEM_JSON not in response.get("content", {}):
                    # El 422 que FastAPI documenta solo (`HTTPValidationError`, en JSON normal)
                    # no es lo que devuelve la API: `register_exception_handlers` lo convierte en
                    # `problem+json`, como todos los errores.
                    response["content"] = {PROBLEM_JSON: {}}
                content = response.get("content", {}).get(PROBLEM_JSON)
                if content is None or "example" in content or "examples" in content:
                    continue
                status = HTTPStatus(int(code))
                example = {
                    **PROBLEM,
                    "title": status.phrase,
                    "status": status.value,
                    "detail": response.get("description", PROBLEM["detail"]),
                    "instance": path,
                }
                if status == HTTPStatus.UNPROCESSABLE_ENTITY:
                    example["detail"] = DEFAULT_DETAILS[status]
                    # El 422 lleva además qué campos fallan: ubicación, mensaje y tipo (nunca el
                    # valor recibido, que podría ser una contraseña).
                    example["errors"] = [
                        {
                            "loc": ["query", "size"],
                            "msg": "Input should be less than or equal to 200",
                            "type": "less_than_equal",
                        }
                    ]
                content["example"] = example
    return spec
