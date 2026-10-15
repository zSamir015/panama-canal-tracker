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
