# Revisión de seguridad (tarea 7.6)

Revisión final de lo construido contra `AGENTS.md` §8, hecha el 2026-11-19 sobre `main` después de
cerrar la Fase 5 (`v0.5.0`). Sustituye a la primera pasada del 2026-11-06.

**Alcance (ADR-0017)**: `v1.0.0` no tiene entorno de producción. Se revisa lo que existe: la demo
estática en GitHub Pages, la pila completa local (API, worker, base de datos y Redis), el código,
las dependencias, el historial y lo publicado en `docs/media/`. Lo que solo tiene sentido en un
servidor no se da por hecho: está en "Antes de desplegar", al final, como requisito.

Cada fila dice cómo se sabe: **hoy** = lo comprobé en esta revisión ejecutando algo o leyendo el
código; **tests** = lo cubren tests que existen y pasan.

## Cómo se comprobó

| Comprobación (ejecutada hoy) | Resultado |
|---|---|
| `gitleaks` sobre el historial completo (106 commits, todas las ramas) | Sin hallazgos |
| `pip-audit --strict` con `requirements.lock` y `requirements-dev.lock` | Sin vulnerabilidades conocidas |
| `npm audit` en `web/` (con y sin dependencias de desarrollo) | 0 vulnerabilidades |
| Alertas abiertas en GitHub (Dependabot y secret scanning) | 0 y 0 |
| Secret scanning, push protection y actualizaciones de seguridad de Dependabot | Activados (consultado con `gh api`) |
| `deptry` sobre `app/` | Solo `starlette` importado sin declarar (ver "Riesgos aceptados"); el resto, falsos positivos explicados abajo |
| Autores de los commits | 82 con el `noreply` del dueño y 6 de Dependabot; ningún correo personal |
| `debug=True`, `print(`, `os.environ` fuera de `app/core/config.py` | Ninguno |
| `dangerouslySetInnerHTML`, `innerHTML`, `setHTML`, `eval(` en `web/src` (sin tests) | Ninguno |
| Rutas locales con el usuario del sistema en lo versionado | Ninguna |
| Acciones de GitHub sin fijar por SHA; imágenes sin digest | Ninguna; la imagen de Python va por digest (`ARG PYTHON_IMAGE`) |
| Capturas y GIF de `docs/media/` (13 PNG y `live-map.gif`, mirados uno a uno y los metadatos) | Solo la app y datos simulados o inventados; sin pestañas, rutas, correos ni metadatos de texto |
| **App completa con la CSP en Chrome** (ver abajo) | 0 violaciones, 0 peticiones bloqueadas |
| Cabeceras de la demo en Pages | HTTPS con HSTS (`max-age=31556952`) y redirección 301 desde HTTP, puestas por GitHub; CSP en el `<meta>` |
| `pytest` (1112), `vitest` (218), `ruff`, `mypy app tests` | Verdes |

### La app completa con la CSP

Faltaba en la primera pasada. Frontend compilado en modo normal (no demo, la CSP de
`web/csp.ts` en el `<meta>`) servido con `vite preview` en `localhost:5173`, que reenvía `/api` y
`/ws` a la API: el mismo origen, como estaría detrás de un proxy. API, worker y simulador AIS
locales; un usuario de prueba creado para la ocasión y borrado después. Chrome sin interfaz
controlado por el protocolo de depuración (CDP), con un escuchador de `securitypolicyviolation`
instalado antes de cargar la página: login, 20 s en el mapa en tiempo real y la pestaña de
estadísticas.

- **0 violaciones de CSP, 0 peticiones bloqueadas o fallidas, 0 excepciones.**
- Login, `/transits/current` y las tres estadísticas: 200.
- El WebSocket `ws://localhost:5173/ws/live` funciona bajo `connect-src 'self'`: 13 mensajes en 20 s.
- Tiles de OpenFreeMap: 7 respuestas. El mapa se pinta con los 8 buques simulados y el panel
  "En tránsito ahora".
- Lo único en la consola: el 401 de `/auth/refresh` al abrir sin sesión (esperado: no hay cookie
  todavía) y dos avisos del estilo de OpenFreeMap sobre filtros de escudos de carretera, que no
  tienen que ver con la CSP.

## Lectura del código (hoy)

La primera pasada daba por buenos estos apartados solo por sus tests. Esta vez se leyeron:

- **Autenticación (8.4)** — `app/core/security.py`, `app/core/auth.py`, `app/services/auth.py`,
  `app/routers/auth.py`. Lista fija `algorithms=["HS256"]` (y `jwt_algorithm` es un `Literal`, no
  se puede configurar otro); exige `sub`, `iat`, `exp`, `iss`, `aud`, `jti` y `token_type`, y el
  tipo impide usar un refresh como access. Refresh con rotación, `jti` guardado (no el token) y
  detección de reutilización que revoca la familia. Login contra un hash ficticio si el email no
  existe, mismo error. Cookie `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/api/v1/auth`, con
  tamaño máximo. Logout revoca la familia del refresh recibido y solo si es del usuario. Todos los
  fallos de token dan el mismo 401 y el log solo lleva el motivo, nunca el token.
- **Administración (8.3)** — `require_admin` en el router (`dependencies=[...]`), así que un
  endpoint nuevo queda protegido aunque no lo declare; registro siempre con rol `user`; la acción
  queda en el log `audit` con el id del administrador.
- **CORS (8.10)** — lista explícita validada al arrancar (sin `*`, solo orígenes exactos, `https`
  en producción); métodos y cabeceras explícitos; un preflight rechazado responde `problem+json`
  sin anunciar la política. El WebSocket valida `Origin` contra la misma lista antes de aceptar.
- **Hash de contraseñas (8.17)** — Argon2id de `pwdlib` con rehash automático; longitud 12 a 128
  (y una contraseña de más de 128 no se hashea ni en el login).
- **WebSocket `/ws/live` (8.9)** — aquí salió el único hallazgo (siguiente apartado).

## Hallazgos

| # | Hallazgo | Gravedad | Estado |
|---|---|---|---|
| 1 | `/ws/live` validaba el access token solo en el primer mensaje: la conexión seguía recibiendo posiciones aunque el token caducara o el usuario cerrara sesión | Baja (datos de solo lectura para cualquier usuario registrado) | **Arreglado** en #158 (issue #157): se cierra con `4401` al caducar; el frontend ya renovaba el token y reconectaba |

Los hallazgos abiertos de la primera pasada quedan así:

- Entorno de producción, proxy, HSTS, límites por IP, `/metrics` y `frame-ancestors`: fuera del
  alcance de `v1.0.0` (ADR-0017); van a "Antes de desplegar".
- CSP de la app completa sin probar: **probada** (arriba).
- Copias sin programar: la 7.2 se cerró con las copias listas y la retención probada; programarlas
  va a "Antes de desplegar".
- Validación con datos reales (5.7): **hecha** en `docs/VALIDATION.md` (`v0.5.0`), con el límite de
  cobertura de AISStream documentado.
- Zona gris de los términos de GitHub para el recolector (ADR-0012): sin cambios, documentada; se
  apaga con `AIS_COLLECT_ENABLED`.
- Autenticación, administración, CORS y hash solo por sus tests: **leídos** (arriba).
- Capturas y GIF sin revisar: **revisados** (arriba).
- Reglas de alerta sin conectar a Prometheus: van a "Antes de desplegar".

## Riesgos aceptados

- **El registro dice si un email ya existe** (409). El login no lo revela, pero `register` sí: no
  hay verificación por correo que permita responder igual en los dos casos. Lo frena el límite de 3
  registros por minuto e IP, y la lista de usuarios de un tracker de buques no es un dato sensible.
- **Un access token sigue valiendo en la API REST hasta 15 minutos tras el logout.** Es el precio
  de un JWT sin estado: el logout revoca el refresh, así que no se puede renovar. Comprobar una
  lista de revocación en cada petición costaría una consulta por petición.
- **No hay cambio de contraseña.** La regla "cambiar la contraseña revoca todas las sesiones"
  (§8.4) no aplica todavía; si se añade, debe revocar todas las familias del usuario.
- **`starlette` se importa sin declararla.** Llega con FastAPI, que fija su versión; declararla
  aparte podría chocar con ese rango. Los otros avisos de `deptry` son falsos positivos: `pyjwt` se
  importa como `jwt`, `asyncpg` es el driver de SQLAlchemy (va en la URL), `alembic` se usa en
  `alembic/` y `httpx` solo en los tests.

## Estado por apartado de AGENTS.md §8

| § | Tema | Estado | Evidencia |
|---|---|---|---|
| 8.1 | Claves y secretos | Cumple | gitleaks limpio, 0 alertas de secret scanning, push protection activado (hoy) |
| 8.2 | Variables de entorno | Cumple | Ningún `os.environ` fuera de `config.py`; validación de producción leída (hoy) y con tests |
| 8.3 | Rutas de administración | Cumple | Leído (hoy); tests 401/403 |
| 8.4 | Autenticación | Cumple | Leído (hoy); el WebSocket ya no sobrevive al token (#158); riesgos aceptados arriba |
| 8.5 | Autorización de usuarios | No aplica | Datos de lectura para cualquier usuario autenticado; no hay recursos propios |
| 8.6 | Validación de entradas | Cumple | `extra="forbid"`, rangos y ventanas acotadas; SQL solo con SQLAlchemy (tests) |
| 8.7 | XSS | Cumple | Sin sinks peligrosos (hoy); regla de ESLint y tests con nombres hostiles |
| 8.8 | Rate limiting | Cumple en la app | Límites de la app con tests. La capa del proxy: "Antes de desplegar" |
| 8.9 | Endpoints | Cumple | `test_deny_by_default`; `/metrics` con token; Origin del WebSocket (hoy) |
| 8.10 | CORS | Cumple | Leído (hoy) y con tests |
| 8.11 | Cabeceras | Cumple en lo que existe | API: middleware con tests. Frontend: CSP probada con la app completa (hoy). Pages: HSTS y redirección de GitHub (hoy). Proxy propio: "Antes de desplegar" |
| 8.12 | Modo de depuración | Cumple | Sin `debug`, sin source maps; `/docs` público por decisión |
| 8.13 | Dependencias | Cumple | pip-audit y npm audit limpios, 0 alertas de Dependabot, lockfiles con hashes (hoy) |
| 8.14 | Paquetes sin usar | Cumple | `deptry` (hoy): ningún paquete declarado sin uso |
| 8.15 | Archivos expuestos | Cumple | `.gitignore` y `.dockerignore`; ninguna ruta local versionada (hoy) |
| 8.16 | Base de datos | Cumple en lo que existe | Sin puertos publicados, mínimo privilegio con tests, copias cifradas con restauración y retención probadas. Programarlas: "Antes de desplegar" |
| 8.17 | Hash de contraseñas | Cumple | Leído (hoy); Argon2id con tests |
| 8.18 | Historial de Git | Cumple | Solo correos `noreply`; gitleaks en pre-commit y en CI (hoy) |
| 8.19 | Auditoría integral | Esta revisión | CI con gitleaks, pip-audit, tests de autorización y ruff `S` |
| 8.20 | Precisión | Cumple | Cada comprobación de esta tabla se ejecutó o se leyó hoy |

## Antes de desplegar

Requisitos para cualquier despliegue de la pila completa en un servidor (ADR-0017). Ninguno está
hecho; hacerlos es una tarea nueva con su propio ADR.

1. **Proxy inverso** delante de la API y del frontend, en el mismo origen: TLS, redirección de
   HTTP a HTTPS, `Strict-Transport-Security: max-age=31536000; includeSubDomains`, sin versión del
   servidor y `Content-Security-Policy` como **cabecera** (con `frame-ancestors 'none'`, que un
   `<meta>` ignora).
2. **Límite global por IP** en el proxy (§8.8), además de los de la app.
3. **`/metrics` bloqueado desde Internet** en el proxy (solo red interna), además de su token.
4. **Variables de producción**: `APP_ENV=production`, `CORS_ORIGINS` solo con el dominio del
   frontend, secretos en el gestor del entorno. La app se niega a arrancar si faltan.
5. **Copias programadas** con `BACKUP_KEEP_DAYS` y llevadas fuera de la máquina; ejecutar
   `scripts/db_backup_check.sh` allí y restaurar una copia real (`docs/BACKUP.md`).
6. **Alertas**: conectar `docker/prometheus/` a un Prometheus y a un canal de aviso.
7. **Repetir esta revisión contra el entorno vivo**, incluida una pasada con securityheaders.com.
