# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: `v0.<fase>.0` al cerrar cada fase; `v1.0.0` al cerrar la Fase 7.

## [Unreleased]

### Changed
- Los access tokens llevan el claim obligatorio `token_type: access`.
- El test de rutas públicas lee las rutas del esquema OpenAPI: desde FastAPI 0.143 `app.routes`
  guarda cada router incluido como un solo objeto.
- Coverage mide con `concurrency = ["greenlet", "thread"]`: SQLAlchemy async ejecuta las
  consultas en greenlets y sin esto las líneas tras un `await` a la base salían sin cubrir.

### Added
- `docker-compose.yml` de desarrollo: PostgreSQL 16 + TimescaleDB 2.30 + PostGIS y Redis 8 con
  contraseña, imágenes fijadas por digest, healthchecks, volúmenes y puertos solo en `127.0.0.1`.
- Roles de la base (`docker/db/initdb/100_canal_roles.sh`): `canal_owner` es dueño de la base y
  ejecuta migraciones; `canal_app` solo lee y escribe datos, sin DDL. Contraseña `scram-sha-256`
  obligatoria también dentro del contenedor.
- `scripts/check_dev_services.sh`: comprueba roles, permisos, extensiones y autenticación.
- Acceso a la base con SQLAlchemy 2.1 async + asyncpg (`app/core/db.py`): `create_app()` crea el
  engine y la fábrica de sesiones, y el `lifespan` cierra las conexiones al apagar. `get_db` abre
  una sesión por request, hace rollback si algo falla y la cierra siempre. El engine no registra
  SQL ni incluye los parámetros de las consultas en los errores.
- `DATABASE_URL` como secreto (`SecretStr`) con esquema `postgresql+asyncpg` obligatorio; en
  producción debe definirse y llevar una contraseña distinta del placeholder.
- Patrón repository (`app/repositories/base.py`) y tests de arquitectura: los routers no importan
  el ORM y ninguna consulta se construye con f-strings, `%`, `+` ni `.format()`.
- Tests de integración (marcador `integration`) contra PostgreSQL real con el rol `canal_app`:
  conexión, rol sin DDL, rollback, devolución de conexiones al pool y parámetros enlazados. Si la
  base no está levantada fallan con instrucciones; el CI los excluye hasta la 2.8.
- Alembic async configurado con `MIGRATIONS_DATABASE_URL` y una migración inicial para `users` y
  `refresh_tokens`, incluyendo índices, restricciones, expiración, revocación y rotación.
  `MIGRATIONS_DATABASE_URL` es opcional para la API y Alembic se niega a ejecutarse sin ella.
  La migración no instala extensiones, y la base exige el email en minúsculas
  (`ck_users_email_lowercase`) para que la unicidad no dependa de las mayúsculas. Alembic
  ignora la tabla `spatial_ref_sys` de PostGIS al comparar modelos y base.
- Base `canal_tracker_test` para los tests de integración, con los mismos roles y permisos
  (`docker/db/initdb/110_canal_test_database.sh`; en un volumen existente,
  `scripts/create_test_database.sh`). Los tests de migraciones comprueban upgrade y downgrade,
  que los modelos coinciden con la base migrada y los permisos reales de `canal_app`.
- Hash de contraseñas con Argon2id (`pwdlib`, `app/core/security.py`): política de 12 a 128
  caracteres sin reglas de composición, rehash cuando cambian los parámetros y un hash ficticio
  para verificar en el mismo tiempo exista o no el email.
- Access tokens JWT con PyJWT: `sub`, `iat`, `exp`, `iss`, `aud` y `jti` obligatorios y solo
  `HS256` (`JWT_ALGORITHM` no admite otro valor). Configuración nueva: `JWT_ISSUER`,
  `JWT_AUDIENCE`, `ACCESS_TOKEN_EXPIRE_MINUTES` (1–60) y `REFRESH_TOKEN_EXPIRE_DAYS` (1–30).
- Dependencias `get_current_user` y `require_admin` (`app/core/auth.py`). Todo fallo de
  autenticación responde el mismo 401 con `WWW-Authenticate: Bearer`; el rol se lee de la base en
  cada petición, no del token. `/api/v1` exige token por defecto y el router `/api/v1/admin`
  aplica `require_admin` a nivel de router.
- `UserRepository`, que guarda y busca el email en minúsculas.
- `scripts/create_admin.py`: crea administradores desde la terminal (la API nunca lo hace). Pide
  la contraseña sin mostrarla y deja en el log solo el id del usuario creado.
- Endpoints de auth (`app/routers/auth.py`, `app/services/auth.py`): `register` (siempre rol
  `user`; `role` u otro campo desconocido → 422; duplicado → 409), `login` (mismo 401 exista o no
  el email; rehash si cambiaron los parámetros de Argon2), `refresh`, `logout` y `me`.
- Refresh tokens JWT firmados con `jti` persistido, en cookie `HttpOnly; Secure; SameSite=Strict;
  Path=/api/v1/auth`. Rotación en cada uso y detección de reutilización: un refresh ya rotado
  revoca toda su sesión (familia). Claim `token_type` para que un access no sirva como refresh
  ni al revés.
- Excepciones de dominio (`app/services/exceptions.py`) traducidas a `problem+json` por un
  handler global.
- Rate limiting con `limits` y contador en Redis compartido entre réplicas (ADR-0007,
  `app/core/rate_limit.py`): login 5/min por IP y por email, register 3/min por IP, refresh
  10/min por IP y 120/min por usuario en el resto de `/api/v1`. Exceso → 429 con `Retry-After`.
  Si Redis no responde, auth falla cerrado (503) y la API general falla abierto (log
  `rate_limit_unavailable`). Las claves llevan el email como SHA-256, nunca en claro.
- `REDIS_URL` como `SecretStr`, con esquema `redis`/`rediss` y obligatoria en producción con
  contraseña real.
- Test de denegar por defecto (`tests/test_deny_by_default.py`): recorre todas las rutas y exige
  el mismo 401 sin token y con token falso fuera de la lista blanca, que queda documentada en el
  test. Una ruta-sonda sin autenticación propia en el router protegido comprueba que la protección
  viene del router. `include_in_schema=False` prohibido en `app/` para que ninguna ruta escape al
  recorrido.

### Security
- `certifi` 2026.10.19 en `requirements-dev.lock` (GHSA-6q48-6c7w-9gw2 en 2026.7.22).

## [0.1.0] - 2026-10-15

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
