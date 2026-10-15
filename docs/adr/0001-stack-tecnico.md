# ADR-0001: Stack técnico

- **Fecha**: 2026-10-15
- **Estado**: Aceptada (auth actualizada por ADR-0003; datos ampliados por ADR-0005)

## Contexto
Proyecto de portafolio para demostrar backend Python moderno: API REST con auth, datos
geoespaciales, streaming en tiempo real y un frontend con mapa en vivo.

## Decisión
- **FastAPI** (async) como framework
- **PostgreSQL 16 + PostGIS** como base de datos (TimescaleDB añadido en ADR-0005)
- **SQLAlchemy 2.0 async + Alembic** para ORM y migraciones
- **Pydantic v2 + pydantic-settings** para validación y configuración
- **JWT (access + refresh)**; librerías en ADR-0003
- **pytest + httpx** para tests, **ruff** para lint/format, **mypy** para tipos
- **Docker Compose** para infra, **GitHub Actions** para CI

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Django + DRF | más pesado; async menos natural para WebSockets y streaming |
| Flask | sin async nativo ni validación integrada |
| MongoDB | las consultas geoespaciales y analíticas encajan mejor en PostGIS/SQL |
| SQLite | sin PostGIS; no representa un entorno de producción |

## Consecuencias
- Todo el backend es async de punta a punta.
- La imagen de base de datos debe incluir PostGIS y TimescaleDB.
