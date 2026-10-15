# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: `v0.<fase>.0` al cerrar cada fase; `v1.0.0` al cerrar la Fase 7.

## [Unreleased]

### Added
- Scaffold del proyecto: estructura de `app/`, `web/`, `tests/`, `scripts/`, `docs/`.
- Documentación: arquitectura, roadmap por fases, diseño de API, fuentes de datos y ADRs 0001–0006.
- `AGENTS.md` como guía única de convenciones, con reglas de seguridad obligatorias (§8).
- `pyproject.toml` con ruff, pytest y mypy; lockfiles con hashes verificados.
- Baseline de seguridad: `SECURITY.md`, `.dockerignore`, pre-commit con gitleaks, Dependabot.
- `app/core/config.py`: configuración con pydantic-settings; en producción la app no arranca con
  `JWT_SECRET_KEY` débil o ausente, `CORS_ORIGINS` sin definir o `LOG_LEVEL=DEBUG`. `CORS_ORIGINS`
  vacía o con `*` se rechaza en cualquier entorno. Los errores de validación no muestran secretos.
- `app/core/logging.py`: logs JSON de una línea con structlog, también para `logging` y uvicorn
  (incluida su CLI). Campos sensibles redactados y tracebacks sin variables locales.
- `app/main.py`: fábrica `create_app(settings)` con logging, CORS explícito, router `/api/v1` y
  `GET /health` en la raíz. `uvicorn app.main:app` arranca y responde 200.
- Errores `application/problem+json` (RFC 9457) con `detail` en español e `instance`, para rutas
  inexistentes, métodos no permitidos, validación (422, sin devolver el valor recibido) y errores
  no controlados (500, sin mensaje ni traza: los detalles van al log).
- `X-Request-ID` único por petición, en la cabecera, en el cuerpo de los errores y en cada log
  (también en los access logs de uvicorn). Un id enviado por el cliente se ignora.
- Límite de 64 KB en el body: 413 por `Content-Length` antes de leer y también contando bytes
  en peticiones chunked; `Content-Length` no numérico devuelve 400.
- Cabeceras de seguridad en todas las respuestas, incluidos los errores 500:
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` y
  `Cross-Origin-Resource-Policy: same-site`; `Cache-Control: no-store` bajo `/api/v1/auth/`.
- CORS endurecido: un preflight rechazado responde `problem+json` sin anunciar métodos, cabeceras
  ni credenciales; `X-Request-ID` expuesto al frontend; `max_age` de 600 s explícito.
- `CORS_ORIGINS` valida cada origen (`esquema://host[:puerto]`, sin ruta, barra final, usuario ni
  `null`) y en producción solo admite `https`.
- CI en GitHub Actions con cinco jobs: ruff, mypy, pytest con cobertura, `pip-audit` sobre los
  lockfiles y gitleaks sobre todo el historial. `GITHUB_TOKEN` sin permisos por defecto (solo
  `contents: read` por job), actions fijadas por SHA y binario de gitleaks verificado por SHA-256.
