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
