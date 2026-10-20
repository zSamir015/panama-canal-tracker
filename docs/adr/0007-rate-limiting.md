# ADR-0007: Rate limiting con `limits` y Redis asíncrono

- **Fecha**: 2026-10-20
- **Estado**: Aceptada

## Contexto

La API necesita límites compartidos entre réplicas para evitar abuso y proteger login, registro,
refresh, endpoints autenticados y conexiones WebSocket. La implementación no puede bloquear el
event loop ni incluir contraseñas o tokens completos en las claves.

## Decisión

Usamos `limits` para sus objetos de límite y semántica de ventanas, y `redis.asyncio` para el
almacenamiento compartido. La aplicación implementa una dependencia FastAPI pequeña que ejecuta
una ventana móvil atómica con un script Lua en Redis, devuelve `429` con `Retry-After` y falla
cerrada con `503` si Redis no está disponible.

Límites iniciales:

| Superficie | Límite | Clave |
|---|---:|---|
| Login | 5/min por IP y email | IP / hash del email |
| Registro | 3/min por IP | IP |
| Refresh | 10/min | IP |
| API autenticada | 120/min | usuario del token |
| WebSocket | 5 conexiones simultáneas | usuario del token |

Las claves contienen solo un ámbito y un hash SHA-256 de identificadores; nunca contraseñas,
cookies, JWT ni tokens completos.

## Alternativas

| Opción | Motivo de descarte |
|---|---|
| `slowapi` | Usa la API síncrona de `limits` y puede bloquear el event loop |
| `fastapi-limiter` | Cambió de implementación recientemente y añade una abstracción innecesaria |
| Redis a mano | Duplica algoritmos y semántica que `limits` ya modela |

## Consecuencias

- Redis es una dependencia operativa obligatoria para las rutas limitadas.
- La dependencia propia mantiene explícitos los identificadores y el contrato RFC 6585.
- Los tests verifican atomicidad lógica, `Retry-After`, no filtración de identificadores sensibles y
  el fallo cerrado cuando Redis no responde.
