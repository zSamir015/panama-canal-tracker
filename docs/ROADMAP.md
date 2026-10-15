# Roadmap — Panama Canal Tracker

Desarrollo por fases. **Una fase a la vez, en orden.** Cada fase termina con:

1. Tests verdes en CI y criterios de aceptación cumplidos.
2. Documentación de la entrega (AGENTS.md §7): README, diagramas, capturas/GIF si hay algo visible.
3. Entrada en `CHANGELOG.md` y tag `v0.<fase>.0`.

Organización en GitHub: **un Milestone por fase, un Issue por tarea, un PR por Issue.**

Leyenda: `[ ]` pendiente · `[~]` en curso · `[x]` terminada

---

## Fase 0 — Scaffold `[x]`

- [x] Estructura de directorios (`app/`, `web/`, `tests/`, `scripts/`, `docs/`)
- [x] `AGENTS.md` (fuente única), `CLAUDE.md` y `copilot-instructions.md` apuntando a él
- [x] `docs/` (ARCHITECTURE, ROADMAP, DATA_SOURCES, API_DESIGN) y ADRs 0001–0006
- [x] `pyproject.toml` (deps, ruff, pytest, mypy), `.python-version`, `LICENSE` (MIT)
- [x] Plantilla de PR con checklist de seguridad
- [x] Baseline de seguridad: reglas en AGENTS.md §8, `SECURITY.md`, `.dockerignore`,
      `.gitignore` endurecido, pre-commit con gitleaks, Dependabot, lockfiles con hashes

**Aceptación**: repo clonable con documentación coherente; sin código de aplicación.

---

## Fase 1 — Esqueleto FastAPI, CI y seguridad del repo `[x]`
**Objetivo**: API mínima que arranca, con configuración por entorno y un CI exigente desde el día 1.

- [x] 1.1 `app/core/config.py` con pydantic-settings: `SecretStr`, validación fail-fast en
      producción (secreto JWT, CORS sin `*`, variables obligatorias)
- [x] 1.2 `app/core/logging.py`: logs JSON con structlog
- [x] 1.3 `app/main.py`: app FastAPI, CORS desde config, router `/api/v1`, `GET /health`
- [x] 1.4 Handler global de errores `application/problem+json` (RFC 9457), sin detalles internos
      en producción; límite de tamaño de body
- [x] 1.5 Middleware de cabeceras de seguridad y CORS endurecido
- [x] 1.6 Tests: `/health`, 404 problem+json, cabeceras, CORS rechaza origen no listado,
      500 sin stack trace en producción, config rechaza secreto débil en producción
- [x] 1.7 GitHub Actions: ruff, mypy, pytest + cobertura, `pip-audit` sobre los lockfiles,
      `gitleaks` con historial completo; permisos mínimos del `GITHUB_TOKEN`
- [x] 1.8 Branch protection en `main` con CI obligatorio; secret scanning + push protection y
      private vulnerability reporting activados
- [x] 1.9 Badges de CI en `README.md` y `README.es.md`

**Aceptación**: `uvicorn app.main:app` levanta; `GET /health` → 200; CI verde con todos los jobs.
**Release**: `v0.1.0`.

---

## Fase 2 — Base de datos y autenticación `[ ]`
**Objetivo**: PostgreSQL/PostGIS/TimescaleDB local, usuarios con registro, login y refresh seguro.

- [ ] 2.1 `docker-compose.yml`: `db` (TimescaleDB + PostGIS) y `redis` con contraseña; roles
      `canal_owner` (migraciones) y `canal_app` (sin DDL)
- [ ] 2.2 SQLAlchemy 2.0 async, `get_db`, patrón repository
- [ ] 2.3 Alembic; migraciones de `users` y `refresh_tokens`
- [ ] 2.4 `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me`;
      refresh en cookie HttpOnly con rotación y detección de reutilización
- [ ] 2.5 Argon2id (pwdlib), PyJWT con `iss`/`aud`; `get_current_user`, `require_admin` a nivel
      de router; login resistente a enumeración; `scripts/create_admin.py`
- [ ] 2.6 Rate limiting con contador en Redis (ADR-0007 elige la librería)
- [ ] 2.7 Test "denegar por defecto" que recorre `app.routes`
- [ ] 2.8 CI con service container de la DB; tests de integración reales
- [ ] 2.9 Tests: registro, duplicado (409), campo `role` en el body rechazado, login, token
      inválido / expirado / `alg: none` / audiencia incorrecta (401), refresh rotado, refresh
      reutilizado revoca la familia, rol admin (403), rate limit (429). Cobertura ≥ 80 %

**Aceptación**: flujo register → login → endpoint protegido → refresh → logout, con tests verdes.
**Release**: `v0.2.0`.

---

## Fase 3 — Ingesta AIS (worker) y tiempo real interno `[ ]`
**Objetivo**: el worker consume AISStream, persiste posiciones y las publica en Redis.

- [ ] 3.1 Modelos `vessels` y `positions` (hypertable, índices GIST y por buque/tiempo)
- [ ] 3.2 Parser puro de `PositionReport` y `ShipStaticData` con validación, longitudes máximas y
      filtros de calidad (los datos AIS son entrada no confiable)
- [ ] 3.3 `app/workers/ais_consumer.py`: conexión única, bbox, backoff con jitter, cola acotada
- [ ] 3.4 Writer con batch inserts y upsert de `vessels`
- [ ] 3.5 Publisher a Redis (`vessels.live`) y estado del worker
- [ ] 3.6 `scripts/ais_simulator.py`: trayectorias realistas por el Canal, mismo formato que AISStream
- [ ] 3.7 Revisar términos de uso de AISStream respecto a mostrar datos públicamente; documentar
      conclusión en `DATA_SOURCES.md` (decide si la demo es pública, con login o con retraso)
- [ ] 3.8 Prueba de humo real con API key; ajustar bbox con datos reales
- [ ] 3.9 `GET /vessels`, `GET /vessels/{mmsi}`, `GET /admin/ingestion/status`
- [ ] 3.10 Dockerfiles (api y worker, multi-stage, no root, sin secretos en capas) y compose
      completo sin puertos publicados para db y redis

**Aceptación**: con el simulador, `positions` crece, Redis recibe eventos y `GET /vessels` lista
buques. Con la key real, el worker aguanta una desconexión forzada y se recupera.
**Release**: `v0.3.0`.

---

## Fase 4 — Mapa en tiempo real y demo desplegada `[ ]`
**Objetivo**: lo visible. Un mapa en vivo del Canal, desplegado y enlazado desde el README.

- [ ] 4.1 Inicializar `web/` (Vite + React + TypeScript strict + ESLint/Prettier + Vitest)
- [ ] 4.2 `WS /ws/live`: suscripción a Redis, snapshot inicial, filtro por viewport, batching 1 Hz,
      validación de `Origin`, auth en el primer mensaje, límites de conexiones y tamaño
- [ ] 4.3 Mapa MapLibre con capa GeoJSON de buques (icono rotado por rumbo, color por tipo)
- [ ] 4.4 Ficha del buque al hacer clic; estela de los últimos 30 min (`/vessels/{mmsi}/history`)
- [ ] 4.5 Reconexión del WebSocket en el cliente; indicador "en vivo / reconectando"
- [ ] 4.6 CI del frontend (lint con regla anti `dangerouslySetInnerHTML`, typecheck, tests,
      build, `npm audit`); test XSS con un nombre de buque malicioso
- [ ] 4.7 Despliegue: VPS con compose + reverse proxy (TLS, HSTS, rate limit global);
      CSP estricta en el frontend; firewall solo 80/443/SSH con llave
- [ ] 4.8 Prueba de carga del WebSocket (p. ej. 500 clientes simulados); documentar resultados
- [ ] 4.9 GIF del mapa en vivo en el README y enlace a la demo

**Aceptación**: la demo pública muestra buques moviéndose en tiempo real; el WS soporta la carga
objetivo sin degradar la ingesta.
**Release**: `v0.4.0`.

---

## Fase 5 — Detección de tránsitos `[ ]`
**Objetivo**: la feature diferenciadora. Convertir posiciones en tránsitos del Canal.

- [ ] 5.1 Polígonos GeoJSON de entradas Atlántico y Pacífico (versionados, visibles en el mapa)
- [ ] 5.2 Máquina de estados pura (`in_progress` → `completed` / `aborted`), sin I/O
- [ ] 5.3 Integración en el worker; modelo `transits` + migración
- [ ] 5.4 `GET /transits`, `/transits/current`, `/transits/{id}`
- [ ] 5.5 Tests con trayectorias sintéticas: completo en ambos sentidos, abortado por timeout,
      reversa, buque detenido, señal intermitente
- [ ] 5.6 Panel "en tránsito ahora" en el mapa
- [ ] 5.7 **Validación con datos reales**: comparar tránsitos detectados por día con estadísticas
      públicas de la ACP; documentar precisión, falsos positivos y causas en `docs/VALIDATION.md`

**Aceptación**: una trayectoria sintética Atlántico → Pacífico produce un `transit` `completed`,
`southbound`, con duración correcta; el informe de validación está publicado.
**Release**: `v0.5.0`.

---

## Fase 6 — Fondeo, tiempos de espera y estadísticas `[ ]`

- [ ] 6.1 Polígonos de fondeaderos; `AnchorageService` y tabla `anchorage_visits`
- [ ] 6.2 Enlace visita de fondeo → tránsito siguiente (tiempo de espera real)
- [ ] 6.3 Agregados continuos de TimescaleDB para estadísticas
- [ ] 6.4 `GET /stats/daily`, `/stats/transit-durations`, `/stats/waiting-times`
- [ ] 6.5 Compresión y downsampling de `positions` (sin borrar histórico)
- [ ] 6.6 Vista de estadísticas en `web/` (gráficas)

**Aceptación**: estadísticas correctas sobre datos sintéticos sembrados y visibles en el frontend.
**Release**: `v0.6.0`.

---

## Fase 7 — Producción y pulido de portafolio `[ ]`

- [ ] 7.1 `/metrics` Prometheus y `/ready`; alerta si el worker lleva > 5 min sin mensajes
- [ ] 7.2 Backups automáticos de la DB y procedimiento de restauración probado
- [ ] 7.3 OpenAPI completo (descripciones y ejemplos en todos los endpoints)
- [ ] 7.4 README final: GIFs, diagramas, decisiones técnicas, resultados de validación y carga
- [ ] 7.5 Sección "How it was built" enlazando roadmap, ADRs, issues y releases
- [ ] 7.6 Revisión de seguridad final (dependencias, headers, CORS, secretos, capturas)

**Release**: `v1.0.0`.

---

## Backlog (fuera de alcance hasta v1.0)
- Exportación CSV/GeoJSON de tránsitos
- Alertas (webhook o email) cuando un buque entra al Canal
- Inferencia de esclusas usadas (Panamax vs. Neopanamax)
- Tracker aéreo con OpenSky Network sobre Tocumen (ver DATA_SOURCES.md §6)
