# Revisión de seguridad final (tarea 7.6)

Revisión completa de lo construido frente a `docs/ENGINEERING.md` §8, ejecutada el **2026-11-19** sobre
`main` (`ef6e484`) con el alcance definido en el **ADR-0017** (`v1.0.0` sin entorno de producción:
demo estática en GitHub Pages y pila completa local con `docker compose`).

**Resultado**: los controles de código, dependencias, secretos, contenedores, cabeceras de la API,
CSP del frontend y capturas cumplen `docs/ENGINEERING.md` §8 para este alcance. Lo que requiere un servidor
público (reverse proxy, TLS/HSTS, límites globales por IP, bloqueo de `/metrics`, `frame-ancestors`
en cabecera y backups programados) queda documentado abajo como **requisito previo a cualquier
despliegue**, no como fallo pendiente de `v1.0.0`.

## Cómo se comprobó hoy

| Comprobación (ejecutada el 2026-11-19) | Resultado |
|---|---|
| `gitleaks detect --source . --verbose` | 93 commits escaneados (~2,03 MB); **0 leaks** |
| `pip-audit --strict --disable-pip -r requirements.lock -r requirements-dev.lock` | **0 vulnerabilidades conocidas** |
| `npm audit` en `web/` | **0 vulnerabilidades** |
| `deptry` (`app`, `alembic`, `tests`, `scripts`, grupo `dev`) | **0 paquetes sin usar reales**; solo reporta `asyncpg` (driver en la URL de SQLAlchemy) y `starlette` en `DEP001` (llega con `fastapi`) |
| Autores de los 89 commits en `main` | 82 `zSamir015`, 1 `Samir Herrera` (`noreply` del dueño) y 6 `dependabot[bot]`; **0 correos personales** |
| Búsqueda en `app/` (`debug=True`, `print(`, `os.environ`, `text(`) | Sin `debug=True`, `print(` ni `os.environ` fuera de `config.py`; `text()` solo con literales fijos (índices, `server_default` y `SELECT 1`) |
| Búsqueda en `web/src/` (`dangerouslySetInnerHTML`, `innerHTML`, `setHTML`, `eval(`) | Ninguno fuera de `src/test/lint-rules.test.ts` (regla anti-XSS de ESLint) |
| Lectura línea a línea de auth, admin, CORS, cabeceras y WebSocket | Revisados `security.py`, `core/auth.py`, `services/auth.py`, `routers/auth.py`, `routers/admin.py`, `main.py`, `middleware.py`, `headers.py`, `logging.py`, `config.py`, `routers/live.py`, `routers/infrastructure.py` y `schemas/auth.py` |
| Prueba en navegador (Chromium) de la app completa con CSP (`vite build`) | Pila local (`db`, `redis`, simulador, worker, API) + `web/dist` en el mismo origen (`http://localhost:14173`): login (`200`), mapa + worker de MapLibre + tiles OpenFreeMap, `/ws/live` (`En vivo · 8 buques`), `/transits/current`, `/vessels/{mmsi}` y `/history`, `/stats/*` (`200`). **0 violaciones de CSP, 0 errores de consola** y sin tokens en logs |
| Revisión visual de `docs/media/` (`13` PNGs + fotogramas de `live-map.gif`) | Solo la ventana de la app, con buques/datos simulados; sin pestañas, barras del navegador, rutas locales, correos personales ni secretos |
| Demo en GitHub Pages (cabeceras con `curl -I`) | HTTPS con `Strict-Transport-Security: max-age=31556952` y redirección `301` desde HTTP, puestas por GitHub; CSP en el `<meta>` |
| Alertas abiertas en GitHub (Dependabot y secret scanning) | **0** y **0** |
| Configuración de GitHub (`gh api`) | `secret_scanning`, `secret_scanning_push_protection` y `dependabot_security_updates` **activados** |
| Imágenes base y acciones de GitHub | `timescaledb-ha` y `redis:8.10.2-alpine` fijadas por digest en `docker-compose.yml`; todas las acciones de `.github/workflows/` fijadas por SHA |
| Lockfiles, Dockerfile y pila de contenedores | `1 254` y `2 031` líneas con `--hash=`; `Dockerfile` con `USER 10001:10001` y `.dockerignore`; `docker-compose.stack.yml` sin puertos publicados para `db` ni `redis` y contenedores `read_only` + `cap_drop: ALL` |
| Suites y estáticos locales | `eslint --max-warnings=0`, `tsc -b`, `vitest` (218 tests), `vite build`, `ruff` (lint + format), `mypy app tests` (137 archivos), `pytest -m "not integration"` (785 tests) verdes |

## Lectura línea a línea: verificación de código

* **Autenticación y hash de contraseñas (`app/core/security.py`, `app/services/auth.py`, `app/routers/auth.py`, `app/schemas/auth.py`, `app/core/auth.py`)**:
  * `PasswordHash((Argon2Hasher(),))` con política NIST SP 800-63B (12–128 caracteres, sin composición forzada); `verify_password` usa un hash ficticio en caché (`_dummy_hash()`) cuando el email no existe para igualar tiempos y corta entradas > 128 caracteres sin ejecutar Argon2; soporta rehash automático (`verify_and_update`).
  * `jwt.decode` fija `algorithms=["HS256"]` (`Literal["HS256"]` en `Settings`), exige `REQUIRED_CLAIMS = ("sub", "iat", "exp", "iss", "aud", "jti", "token_type")`, comprueba `token_type` (impide usar un refresh como access y viceversa) y valida `UUID(sub)`.
  * `AuthService.refresh` bloquea la fila con `get_for_update`, comprueba `stored.user_id == claims.user_id` y, si detecta un token ya rotado (`revoked_at is not None`), revoca toda la familia (`family_id`) y registra `refresh_token_reuse_detected`. `logout` exige access token y solo revoca sesiones del propio `user.id`.
  * La cookie `refresh_token` se emite con `HttpOnly=True`, `Secure=True`, `SameSite="strict"` y `Path="/api/v1/auth"`; `UserCreate` y `LoginRequest` usan `extra="forbid", strict=True` sin campo `role` (registro siempre crea `UserRole.USER`).
* **Administración (`app/routers/admin.py`, `app/core/auth.py`)**:
  * `router` montado bajo `api_router` (`get_current_user` + `limit_api_by_user`) y protegido a nivel de router con `dependencies=[Depends(require_admin)]`. Toda operación registra auditoría (`audit.info("admin_action", ...)`).
* **CORS, cabeceras, límites y logs (`app/main.py`, `app/core/middleware.py`, `app/core/headers.py`, `app/core/logging.py`, `app/routers/live.py`, `app/routers/infrastructure.py`)**:
  * `HardenedCORSMiddleware` valida orígenes explícitos sin `*`, `allow_credentials=True`, métodos `GET/POST/DELETE`, cabeceras `Authorization/Content-Type`, y en preflights rechazados devuelve `400 problem+json` sin anunciar cabeceras `Access-Control-Allow-*`.
  * `SecurityHeadersMiddleware` inyecta `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy: same-site` y `Cache-Control: no-store` en `/api/v1/auth/`.
  * `BodySizeLimitMiddleware` corta a 64 KB tanto por `Content-Length` como leyendo chunks; `RequestIdMiddleware` genera UUID propio ignorando cabeceras entrantes; `logging.py` redacta campos sensibles de forma recursiva, desactiva `show_locals` en tracebacks y fija el logger `websockets` en `INFO` como mínimo.
  * `/ws/live` valida `Origin` contra `CORS_ORIGINS` antes de `accept()`, autentica en el primer mensaje (≤ 5 s) y cierra la conexión con `4401` cuando caduca ese access token (hallazgo 1, arreglado en #158), limita frames a 4 KB, mensajes a 20/10 s y conexiones a 5 por usuario en Redis. `/metrics` exige `METRICS_TOKEN` comparado con `hmac.compare_digest` (401 si no hay token configurado).

## Hallazgos

| # | Hallazgo | Gravedad | Estado |
|---|---|---|---|
| 1 | `/ws/live` validaba el access token solo en el primer mensaje: la conexión seguía recibiendo posiciones aunque el token caducara (15 min) o el usuario cerrara sesión. Ningún test lo veía porque ninguno esperaba a que caducara | Baja (datos de solo lectura para cualquier usuario registrado) | **Arreglado** en #158 (issue #157): se cierra con `4401` al caducar y el frontend, que ya trataba el `4401`, renueva el token y reconecta. Test `test_the_connection_closes_with_4401_when_the_token_expires` |

## Riesgos aceptados

- **El registro dice si un email ya existe** (`409`). El login no lo revela, pero `register` sí: sin
  verificación por correo no se puede responder igual en los dos casos. Lo frena el límite de 3
  registros por minuto e IP, y la lista de usuarios de un tracker de buques no es un dato sensible.
- **Un access token sigue valiendo en la API REST hasta 15 minutos tras el logout.** Es el precio
  de un JWT sin estado: el logout revoca el refresh, así que no se puede renovar. Comprobar una
  lista de revocación en cada petición costaría una consulta por petición.
- **No hay cambio de contraseña.** La regla "cambiar la contraseña revoca todas las sesiones"
  (§8.4) no aplica todavía; si se añade, debe revocar todas las familias del usuario.
- **`starlette` se importa sin declararla.** Llega con FastAPI, que fija su versión; declararla
  aparte podría chocar con ese rango.

## Estado por apartado de docs/ENGINEERING.md §8

| § | Tema | Estado (alcance ADR-0017) | Evidencia |
|---|---|---|---|
| 8.1 | Claves y secretos | **Cumple** | `gitleaks` (0 en 93 commits), secret scanning + push protection activos |
| 8.2 | Variables de entorno | **Cumple** | Sin `os.environ` fuera de `config.py`; `SecretStr`; validación fail-fast en producción |
| 8.3 | Rutas de administración | **Cumple** | `require_admin` a nivel de router, log de auditoría, tests 401/403 (leído línea a línea) |
| 8.4 | Autenticación | **Cumple** | PyJWT HS256, rotación + familia, cookie `HttpOnly`/`Secure`/`SameSite=Strict`, login sin enumeración (leído + probado); `/ws/live` ya no sobrevive al token (#158); ver "Riesgos aceptados" |
| 8.5 | Autorización de usuarios | **No aplica / Cumple** | Datos de buques/tránsitos compartidos; `logout` filtra por `user.id` |
| 8.6 | Validación de entradas | **Cumple** | Pydantic `extra="forbid"`, límite de body 64 KB y WS 4 KB, SQL parametrizado, parser AIS estricto |
| 8.7 | XSS | **Cumple** | React sin sinks peligrosos, regla ESLint + tests con `<img onerror>` en ficha y WS |
| 8.8 | Rate limiting | **Cumple (capa de app)** | Límites en Redis (auth fail-closed 503, API fail-open); la capa de proxy queda como requisito previo al despliegue |
| 8.9 | Endpoints | **Cumple** | `test_deny_by_default` + `test_every_websocket_route_is_a_known_authenticated_one`; `/metrics` con token propio; Origin + auth en `/ws/live`, que se cierra al caducar el token (#158) |
| 8.10 | CORS | **Cumple** | `HardenedCORSMiddleware` con orígenes explícitos (leído línea a línea + tests) |
| 8.11 | Cabeceras y CSP | **Cumple (app + meta CSP)** | Middleware de seguridad en API; CSP del frontend probada en vivo en Chromium con app completa (0 violaciones); HSTS y `frame-ancestors` en cabecera quedan para el proxy |
| 8.12 | Modo de depuración | **Cumple** | Sin `debug=True`, sin source maps (`sourcemap: false`), `/docs` público por diseño |
| 8.13 | Dependencias | **Cumple** | `pip-audit` (0 CVEs), `npm audit` (0 CVEs), lockfiles con hashes, Dependabot activo |
| 8.14 | Paquetes sin usar | **Cumple** | Verificado con `deptry` (solo `asyncpg` usado en DSN y `starlette` vía `fastapi`) |
| 8.15 | Archivos expuestos | **Cumple** | `.gitignore` y `.dockerignore` cubren `.env*`, `data/`, `backups/`, llaves y copias |
| 8.16 | Base de datos | **Cumple (pila local)** | Roles `canal_owner`/`canal_app`, `db` y `redis` sin puertos en `docker-compose.stack.yml`, backups cifrados con restauración y retención probadas (7.2) |
| 8.17 | Hash de contraseñas | **Cumple** | Argon2id (`pwdlib`), política 12–128 chars, dummy hash y rehash automático (leído línea a línea) |
| 8.18 | Historial de Git | **Cumple** | Solo correos `noreply` y `dependabot[bot]`; `gitleaks` en pre-commit y CI |
| 8.19 | Auditoría integral | **Cumple** | Revisión completa ejecutada para el cierre de la 7.6 |
| 8.20 | Precisión | **Cumple** | Toda comprobación anotada se ejecutó sobre `main` (`ef6e484`) |

## Requisitos previos a cualquier despliegue en producción (ADR-0017)

La versión `v1.0.0` se entrega únicamente con la demo estática en GitHub Pages y la pila local de
`docker compose`. Si en el futuro se despliega en un servidor accesible desde Internet, es
**obligatorio** completar antes:

1. **Reverse proxy con TLS**: redirección HTTP → HTTPS, `Strict-Transport-Security`, ocultar la
   versión del servidor, rate limiting global por IP, bloqueo externo de `/metrics` y repetir la
   cabecera HTTP `Content-Security-Policy` añadiendo `frame-ancestors 'none'` (que un `<meta>`
   ignora).
2. **Repetir la revisión de seguridad contra el entorno vivo** (cabeceras, CORS con el dominio real,
   cookie `Secure` sobre HTTPS y prueba de penetración básica sobre el proxy).
3. **Backups automáticos y externos (`docs/BACKUP.md`)**: programar `scripts/db_backup.sh` con
   `BACKUP_KEEP_DAYS`, replicar las copias cifradas fuera de la máquina y probar una restauración
   con volumen real.
4. **Monitorización activa**: conectar Prometheus y Alertmanager a `/metrics` y a
   `docker/prometheus/canal-alerts.yml`.

## Limitaciones conocidas fuera del ámbito de seguridad

* **Cobertura gratuita de AISStream (`docs/VALIDATION.md`)**: insuficiencia de señal en el interior
  del Canal; los umbrales y polígonos de tránsitos y fondeaderos se verificaron con datos
  sintéticos, no calibrados contra estadísticas de la ACP.
* **Recolector de AIS en GitHub Actions (`ADR-0012`)**: zona gris de uso de minutos programados;
  el workflow está apagado por defecto y se enciende con la variable `AIS_COLLECT_ENABLED` (hoy
  encendida desde el 2026-11-07 para la validación de la 5.7).
