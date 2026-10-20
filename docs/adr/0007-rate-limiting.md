# ADR-0007: Librería de rate limiting

- **Fecha**: 2026-10-20
- **Estado**: Aceptada

## Contexto
AGENTS.md §8.8 pide límites finos en la app con un contador en Redis compartido entre réplicas:
login 5/min por IP y por email, register 3/min por IP, refresh 10/min, API general 120/min por
usuario y 5 conexiones WebSocket simultáneas por usuario. Respuesta 429 con `Retry-After` en
`problem+json`. La API es async: ninguna llamada a Redis puede bloquear el event loop.

Requisitos que salen de la seguridad del proyecto:
- Las claves de Redis no contienen contraseñas ni tokens; el email se guarda como hash.
- La IP del cliente sale de la conexión, y de `X-Forwarded-For` solo cuando la petición viene del
  reverse proxy de confianza (si no, cualquiera elige su IP y se salta el límite).
- Tests deterministas (sin esperar un minuto real) y un comportamiento definido si Redis cae.

Versiones y código revisados en PyPI el 2026-10-20.

## Alternativas consideradas

| Opción | A favor | En contra |
|---|---|---|
| **A. `limits` 5.8 (`limits.aio`) + dependencia FastAPI propia** | Async real sobre `redis.asyncio`; tres estrategias (fixed window, moving window, sliding window counter); `get_window_stats` da el reinicio para `Retry-After`; mantenimiento activo (4 versiones en 2025–2026). | Hay que escribir la dependencia (~80 líneas): claves, 429, `Retry-After`. |
| B. `slowapi` 0.1.10 | Popular; decoradores `@limiter.limit("5/minute")`. | Usa la API **síncrona** de `limits`: cada consulta a Redis bloquea el event loop. Obliga a añadir `request: Request` a cada endpoint. Una versión al año. |
| C. `fastapi-limiter` 0.2.0 | Dependencias FastAPI listas, también para WebSocket. | La 0.2.0 se reescribió sobre `pyrate-limiter` 4.x, que publicó versión el mismo día de esta revisión; poco historial en su forma actual. |
| D. A mano con Redis (`INCR` + `EXPIRE` o script Lua) | Cero dependencias además de `redis`; control total. | Ventanas, atomicidad y `Retry-After` los escribimos y probamos nosotros; es justo el código que una librería madura ya resolvió. |

## Decisión
**Opción A**: `limits` con almacenamiento async en Redis (`implementation="redispy"`) y una
dependencia FastAPI propia (`app/core/rate_limit.py`). Es la única opción async sin escribir los
algoritmos a mano, y encaja con el patrón del proyecto (`Depends`, `problem+json`, denegar por
defecto).

- **Moving window** para auth (precisa con límites pequeños como 3/min) y **sliding window
  counter** para la API general (menos trabajo en Redis por petición).
- Claves: `login:ip:<ip>`, `login:email:<sha256 del email>`, `register:ip:<ip>`,
  `refresh:ip:<ip>`, `api:user:<id>`. Nunca contraseñas, tokens ni emails en claro.
- IP del cliente: `request.client.host`. Detrás del proxy, uvicorn la toma de
  `X-Forwarded-For` solo si la conexión viene de `--forwarded-allow-ips` (por defecto
  `127.0.0.1,::1`); la app no lee esa cabecera por su cuenta.
- 429 con `Retry-After` (segundos hasta que se libera el cupo) en `problem+json`.

**Si Redis no responde**:
- Endpoints de auth (login, register, refresh): **fallar cerrado**, 503. Sin límite, un ataque de
  fuerza bruta contra el login no tendría freno.
- API general: **fallar abierto**, con un log `rate_limit_unavailable`. Una caída de Redis no
  debería tirar el mapa entero.

## Consecuencias
- Dependencia nueva: `limits[redis]`, que trae `redis` (previsto para la Fase 3). `limits` 5.8
  declara `redis<8`, así que se queda en la 7.x hasta que `limits` amplíe el rango.
- `REDIS_URL` pasa a leerse en `app/core/config.py` como `SecretStr` (lleva la contraseña).
- Los tests unitarios usan el almacenamiento en memoria de `limits` (sin esperar ventanas reales:
  se agota el cupo y se comprueba el 429), y los de integración el Redis real de `docker compose`.
- El límite de conexiones WebSocket se implementa en la Fase 4 junto a `/ws/live`.
