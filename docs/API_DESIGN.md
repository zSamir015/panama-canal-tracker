# Diseño de API — Panama Canal Tracker

- **Base URL**: `/api/v1`. Excepción: `/health`, `/ready` y `/metrics` van en la raíz (los usa
  la infraestructura, no los clientes).
- **Auth**: `Authorization: Bearer <access_token>`. **Denegar por defecto**: todo endpoint exige
  token salvo los marcados con "—" en estas tablas (AGENTS.md §8.9).
- **Límites**: body ≤ 64 KB, `size` ≤ 200, rangos de fechas acotados, 429 con `Retry-After`.
- **Errores**: `application/problem+json` según RFC 9457:

```json
{
  "type": "https://github.com/<usuario>/panama-canal-tracker/docs/errors#vessel-not-found",
  "title": "Vessel not found",
  "status": 404,
  "detail": "No existe un buque con MMSI 123456789.",
  "instance": "/api/v1/vessels/123456789"
}
```

## Infraestructura

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | — | El proceso está vivo |
| GET | `/ready` | — | DB y Redis alcanzables |
| GET | `/metrics` | red interna | Métricas Prometheus |

## Auth

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/auth/register` | — | Crea usuario, **siempre** con rol `user` (el rol no se acepta en el body) |
| POST | `/auth/login` | — | Devuelve `{access_token, token_type, expires_in}`; el refresh va en cookie |
| POST | `/auth/refresh` | cookie refresh | Rota el refresh (cookie nueva) y devuelve un access token nuevo |
| POST | `/auth/logout` | ✅ | Revoca el refresh actual y borra la cookie |
| GET | `/auth/me` | ✅ | Perfil del usuario actual |

- **Refresh token**: cookie `refresh_token`, `HttpOnly; Secure; SameSite=Strict;
  Path=/api/v1/auth`. Nunca en el body ni en `localStorage`. Es un JWT firmado
  (`token_type: refresh`) cuyo `jti` se guarda en `refresh_tokens`; un access token no sirve como
  refresh ni al revés. Cada login abre una sesión (familia); reutilizar un refresh ya rotado
  revoca esa sesión completa (AGENTS.md §8.4), no las demás sesiones del usuario.
- **Logout**: `204`, revoca la sesión del refresh de la cookie (solo si es del usuario del access
  token) y borra la cookie.
- **Register**: body `{email, password}` con `extra="forbid"`; contraseña de 12 a 128 caracteres.
  Responde `201` con `{id, email, role, created_at}`. Si el email ya existe (sin distinguir
  mayúsculas) responde 409.
- **Login**: credenciales incorrectas → 401 con el mismo mensaje y tiempo similar exista o no el
  email.
- **Rate limiting** (ADR-0007): login 5/min por IP y por email, register 3/min por IP, refresh
  10/min por IP; el resto de `/api/v1`, 120/min por usuario. Exceso → 429 con `Retry-After`. Si el
  contador (Redis) no responde, los endpoints de auth responden 503 y el resto sigue sin límite.

## Vessels

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/vessels` | ✅ | Buques vistos (paginado, filtros `ship_type`, `seen_since`) |
| GET | `/vessels/{mmsi}` | ✅ | Ficha del buque + última posición |
| GET | `/vessels/{mmsi}/history` | ✅ | Trayectoria GeoJSON `LineString` (`from`, `to`, máx. 7 días) |

- `GET /vessels`: `?page=1&size=50` (máx. 200), `ship_type` (1–99) y `seen_since` (con zona
  horaria, máx. 90 días atrás); cualquier otro parámetro → 422. Orden: última señal más reciente
  primero (los nunca vistos al final), desempate por MMSI. Respuesta `{items, total, page, size}`
  con `{mmsi, name, imo, ship_type, length_m, beam_m, last_seen_at}` por buque.
- `GET /vessels/{mmsi}`: lo mismo más `last_position` (`{received_at, lat, lon, sog, cog,
  heading, nav_status}` o `null`). MMSI que no tiene 9 dígitos → 422; inexistente → 404.
- `name` es texto AIS tal cual (puede contener `<`, `>`...): el cliente lo muestra como texto.
- `/vessels/{mmsi}/history` queda para una tarea posterior (no está en la 3.9).

## Transits

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/transits` | ✅ | Histórico (filtros `direction`, `status`, `from`, `to`) |
| GET | `/transits/current` | ✅ | Tránsitos `in_progress` |
| GET | `/transits/{id}` | ✅ | Detalle, incluida la espera en fondeo previa |

## Stats

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/stats/daily` | ✅ | Tránsitos por día, sentido y tipo de buque |
| GET | `/stats/transit-durations` | ✅ | Duración de tránsito (media, p50, p90) por ventana |
| GET | `/stats/waiting-times` | ✅ | Espera en fondeo antes de entrar (media, p50, p90) |

## Admin

Router `/api/v1/admin` con `require_admin` aplicado **a nivel de router**: sin token → 401,
rol `user` → 403. No hay endpoint para crear admins (se crean con `scripts/create_admin.py`).

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/admin/ingestion/status` | admin | Estado del worker: último mensaje, reconexiones, cola |

- Respuesta `{available, stale, age_seconds, status}`. `available=false` si no hay estado en
  Redis (worker parado: la clave caduca a los 15 s); `stale=true` si tiene más de 30 s. `status`
  lleva conexión, último mensaje, reconexiones, cola, rechazos por motivo y contadores del
  writer. Redis sin responder → 503. Cada consulta queda en el log de auditoría.

## WebSocket `/ws/live`

1. El cliente abre la conexión **sin token en la URL** (evita que quede en logs). El servidor
   rechaza el handshake si el header `Origin` no está en `CORS_ORIGINS` (CORS no cubre
   WebSockets). Máximo 5 conexiones simultáneas por usuario y mensajes de cliente ≤ 4 KB.
2. Primer mensaje del cliente, en menos de 5 s:
   `{"type": "auth", "token": "<access_token>"}` → si falla, se cierra con código `4401`.
3. El cliente envía su viewport y lo actualiza al mover el mapa:
   `{"type": "subscribe", "bbox": [min_lon, min_lat, max_lon, max_lat]}`
4. El servidor responde con un snapshot y luego con lotes de cambios (≤ 1 por segundo):

```json
{"type": "snapshot", "vessels": [{"mmsi": 352001234, "lon": -79.91, "lat": 9.35,
  "cog": 145.2, "sog": 7.8, "ship_type": 70, "name": "EXAMPLE", "ts": "2026-10-16T14:30:00Z"}]}
{"type": "update", "vessels": [ ... ]}
{"type": "remove", "mmsi": [352001234]}
```

Si la demo pública lo permite (DATA_SOURCES.md, tarea 3.7), se habilitará un modo anónimo de
solo lectura con límite de conexiones por IP.

## Convenciones

- Paginación: `?page=1&size=50` (máx. 200) → `{items, total, page, size}`. Para historiales
  largos, paginación por cursor (`?cursor=`).
- Fechas: ISO 8601 en UTC (`2026-10-16T14:30:00Z`).
- `mmsi`: entero de 9 dígitos (`Field(ge=100000000, le=999999999)`).
- Toda respuesta geográfica en GeoJSON (orden `[lon, lat]`).
- Los campos de texto que vienen de AIS (`name`, `destination`, `callsign`) son datos externos no
  confiables: la API los valida y limita en longitud; el cliente los muestra siempre como texto.
- Recursos de otro usuario → 404, nunca 403 (no revela que existen).
- Cabeceras en todas las respuestas: `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`; `Cache-Control: no-store` en `/auth/*`.
