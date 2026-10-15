"""Cabeceras HTTP que la API añade a sus respuestas (AGENTS.md §8.11)."""

REQUEST_ID_HEADER = "X-Request-ID"

# HSTS y ocultar la versión del servidor son tarea del reverse proxy, no de la app.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-site",
}

# Las respuestas de auth llevan tokens: ni el navegador ni un proxy deben guardarlas.
NO_STORE_PATH_PREFIX = "/api/v1/auth/"


def security_headers(path: str) -> dict[str, str]:
    headers = dict(SECURITY_HEADERS)
    if path.startswith(NO_STORE_PATH_PREFIX):
        headers["Cache-Control"] = "no-store"
    return headers
