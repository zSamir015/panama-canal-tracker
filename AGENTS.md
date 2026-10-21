# AGENTS.md — Fuente única de verdad para asistentes de IA

Este archivo es la **fuente de verdad** para cualquier asistente de IA que trabaje en este repositorio
(Claude Code, GitHub Copilot, Kimi u otro). `CLAUDE.md` y `.github/copilot-instructions.md` solo
apuntan aquí. Si hay conflicto entre documentos, **gana este archivo**; si el conflicto es real,
corrígelo con un ADR, no lo ignores.

Léelo completo antes de generar código.

---

## 1. Contexto del proyecto

**Panama Canal Tracker** es un sistema de portafolio profesional que rastrea en tiempo real los
buques del Canal de Panamá a partir de datos AIS, detecta tránsitos completos y tiempos de espera
en fondeo, y los muestra en un **mapa en vivo**.

- **Backend**: API FastAPI async (`app/`) + worker de ingesta AIS como **proceso separado**.
- **Frontend**: mapa en tiempo real con React + TypeScript + MapLibre GL (`web/`).
- **Datos**: AISStream.io (WebSocket) → PostgreSQL 16 + PostGIS + TimescaleDB.
- **Tiempo real**: Redis pub/sub entre worker y API; la API reenvía a los navegadores por `/ws/live`.
- **Área de interés (bbox inicial)**: lat `8.4`–`9.7`, lon `-80.2`–`-79.2` (refinar en Fase 3).
- **Objetivo**: un proyecto terminado, desplegado y escalable, no una demo a medias. Cada fase deja
  algo funcionando, probado y visible.

Documentos de referencia (leer según la tarea):

| Documento | Para qué |
|---|---|
| `docs/ROADMAP.md` | Fases, tareas y criterios de aceptación. **Qué hacer.** |
| `docs/ARCHITECTURE.md` | Componentes, flujo de datos, modelo de datos. **Cómo encaja.** |
| `docs/API_DESIGN.md` | Contrato REST y WebSocket. **Qué exponer.** |
| `docs/DATA_SOURCES.md` | Reglas y límites de AISStream, zonas geográficas. |
| `docs/adr/` | Decisiones tomadas y por qué. **No reabrirlas sin un ADR nuevo.** |

## 2. Reglas de oro (no negociables)

1. **Nunca** hardcodear secretos ni API keys. Todo por variables de entorno vía
   `app/core/config.py` (pydantic-settings). Ver `.env.example`.
2. **Nunca** commitear `.env` ni archivos con credenciales.
3. Contraseñas hasheadas con **Argon2id** vía `pwdlib`. JWT con **PyJWT**. (ADR-0003)
4. Todo endpoint protegido valida JWT; los endpoints de admin validan rol.
5. **Ninguna tarea se da por terminada sin tests pasando** (`pytest` verde) y `ruff` limpio.
6. AISStream: **una sola conexión WebSocket por API key**, solo desde el proceso `worker`, con
   reconexión y backoff exponencial. Nunca desde el navegador ni desde la API. (ADR-0002, ADR-0004)
7. No modificar `docs/` salvo para reflejar una decisión real; toda decisión nueva va en un ADR
   en `docs/adr/` con el siguiente número libre.
8. **Seguridad**: cumplir la sección 8 completa en cada cambio. Denegar por defecto.
9. **Atribución**: no añadir créditos a asistentes de IA en el repositorio. Nada de trailers
   `Co-Authored-By`, líneas "Generated with ...", ni menciones a Claude, Copilot o Kimi en
   commits, PRs, comentarios, issues o código. El autor de los commits es el dueño del repo.

## 3. Convenciones de código — backend (`app/`)

- **Python 3.12**, todo async (`async def`, `asyncpg`, SQLAlchemy 2.0 async).
- **Type hints obligatorios** en funciones públicas. `mypy --strict` debe pasar en `app/`.
- Estilo: `ruff` (lint + format), línea máxima 100. Configurado en `pyproject.toml`.
- Identificadores en **inglés**; comentarios y docstrings en **español** cuando expliquen lógica de
  negocio del Canal.
- Capas estrictas: `routers/` (HTTP) → `services/` (lógica) → `repositories/` (acceso a datos)
  → `models/` (ORM). Nunca lógica de negocio en routers ni modelos ORM en responses.
- Schemas Pydantic en `app/schemas/` con sufijos `Create`, `Update`, `Response`
  (ej. `TransitResponse`).
- Dependencias FastAPI con `Depends`: `get_db`, `get_current_user`, `require_admin`.
- Consultas geoespaciales con PostGIS vía `geoalchemy2` (`ST_Within`, `ST_DWithin`, ...).
- Errores: excepciones de dominio en `services/`; un handler global las traduce a respuestas
  `application/problem+json` (RFC 9457). Mensajes `detail` en español.
- Logs estructurados en JSON (nunca `print`). Nunca loguear tokens, contraseñas ni API keys.
- Migraciones con Alembic (desde Fase 2). Nunca modificar una migración ya mergeada.
- Lógica de dominio pura (detección de tránsitos, parseo AIS) sin I/O, para testearla sin DB.

## 4. Convenciones de código — frontend (`web/`)

- React + TypeScript (`strict`) + Vite. Mapa con **MapLibre GL JS**. (ADR-0006)
- Los buques se pintan como **capa GeoJSON** (WebGL), nunca como markers DOM uno a uno.
- Estado de servidor con TanStack Query; el stream en vivo en un hook (`useLiveVessels`).
- La URL de la API y del proveedor de tiles vienen de variables `VITE_*`. Nunca keys en el código.
- Lint con ESLint + Prettier; tests con Vitest.

## 5. Tests

- `pytest` + `pytest-asyncio` (modo auto) + `httpx.AsyncClient`. Fixtures en `tests/conftest.py`.
- Cubrir caso feliz y errores (401, 403, 404, 422) en cada endpoint.
- Tests de integración contra PostgreSQL/PostGIS y Redis reales, no SQLite. En el CI, el job de
  tests levanta el mismo `docker-compose.yml` con credenciales aleatorias de cada ejecución.
- Mensajes AIS de ejemplo en `tests/fixtures/ais_messages/`. Ningún test depende de AISStream real.
- Cobertura mínima: 80 % en `app/` (lo exige el CI desde Fase 2).

## 6. Flujo de trabajo y coordinación entre asistentes

- Seguir **estrictamente** `docs/ROADMAP.md`: **una fase a la vez, en orden**. No adelantar
  funcionalidad de fases futuras salvo petición explícita.
- **Un issue = una rama = un PR.** Rama `tipo/descripcion-corta` (ej. `feat/health-endpoint`).
- **Un asistente por rama.** Antes de empezar, revisar el issue y los PR abiertos para no pisar
  trabajo de otro asistente. Dejar el estado en el issue al terminar o al quedarse bloqueado.
- Commits: [Conventional Commits](https://www.conventionalcommits.org/) en inglés
  (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`, `ci:`).
- PRs usan `.github/pull_request_template.md`. CI verde antes de pedir revisión.
- Al completar una fase: marcar el checkbox en `ROADMAP.md`, actualizar "Project status" en
  `README.md` y `README.es.md`, y crear el tag `vX.Y.0` correspondiente.

## 7. Documentación de cada entrega (nivel senior)

Cada PR y cada fase cerrada se documentan como lo haría un ingeniero senior: cualquiera debe
entender **qué cambió, por qué y cómo funciona** sin leer el código.

- **PR**: plantilla completa (antes/después, por qué, cómo se probó). Si cambia algo visible,
  incluir captura o GIF. Si cambia el flujo de datos, actualizar el diagrama.
- **Diagramas** en Mermaid dentro del Markdown (GitHub los renderiza): arquitectura, secuencia de
  ingesta, máquina de estados de tránsitos. Se actualizan en el mismo PR que cambia el diseño.
- **Imágenes y GIFs** en `docs/media/` con nombres descriptivos (`fase4-live-map.gif`).
  GIFs cortos (≤ 15 s, ≤ 5 MB); para demos largas, enlazar un video.
- **README** (`README.md` en inglés y `README.es.md` en español): demo, GIF principal,
  arquitectura, cómo correrlo, decisiones técnicas, estado por fase.
- **`CHANGELOG.md`** con formato Keep a Changelog; una entrada por release `vX.Y.0`.
- **ADR** por cada decisión técnica relevante; la documentación explica el *por qué*, no solo
  el *qué*.
- **OpenAPI**: cada endpoint con `summary`, `description` y ejemplos de request/response.

### 7.1 Seguridad de la información en la documentación (obligatorio)

Nada que se publique (código, docs, PRs, issues, capturas, GIFs, logs, commits) puede exponer
datos del dueño del repositorio ni secretos. Antes de publicar, revisar:

- **Nunca** incluir API keys, tokens JWT, contraseñas, `DATABASE_URL` reales ni el contenido de
  `.env`. En ejemplos, usar placeholders evidentes (`<AISSTREAM_API_KEY>`, `changeme`).
- **Capturas y GIFs**: grabar solo la ventana de la app. Que no se vean pestañas, barras de
  favoritos, terminales con variables de entorno, rutas locales con el usuario del sistema
  (`/Users/...`, `C:\Users\...`), notificaciones ni correos. Usar cuentas de demo
  (`demo@example.com`), nunca la cuenta personal.
- **Datos personales**: no publicar correo personal, teléfono, dirección, ubicación propia,
  IPs ni nombres de host internos. Las IPs y dominios del servidor de producción no se documentan
  más allá del enlace público de la demo.
- **Logs y trazas** pegados en issues o PRs: revisar y redactar tokens, headers `Authorization`
  y query params con credenciales.
- **Git**: si un secreto llega a un commit, se considera comprometido: **rotarlo de inmediato**
  (borrarlo del historial no basta) y avisar al dueño.
- **Controles automáticos**: GitHub secret scanning con push protection activado y `gitleaks`
  en CI (Fase 1). Un hallazgo bloquea el merge.

## 8. Seguridad (obligatoria en todas las fases)

Estas reglas aplican a **todo** el código, configuración y documentación, desde el primer commit.
Cada una indica cómo se verifica. Un PR que incumpla una regla no se mergea.
Principio general: **denegar por defecto** — todo cerrado salvo lo que se abre explícitamente.

### 8.1 Claves de API y secretos
- Ningún secreto en código, tests, docs, fixtures, capturas ni mensajes de commit.
- Secretos solo en `.env` (local) o en el gestor de secretos del entorno de despliegue / GitHub
  Actions Secrets (CI).
- La API key de AISStream solo la lee el proceso `worker`; nunca llega a la API ni al frontend.
- Verificación: `gitleaks` en pre-commit y en CI; secret scanning + push protection en GitHub.

### 8.2 Variables de entorno
- Se leen **solo** en `app/core/config.py` (pydantic-settings). Prohibido `os.environ` en el resto.
- Secretos tipados como `SecretStr`; nunca se loguean ni se devuelven en respuestas.
- Validación al arrancar (fail fast): en `APP_ENV=production` la app se niega a iniciar si
  `JWT_SECRET_KEY` es el placeholder o mide < 32 bytes, si `CORS_ORIGINS` contiene `*`, o si
  falta alguna variable obligatoria.
- `.env.example` solo con placeholders evidentes (`changeme`, vacío).
- Frontend: toda variable `VITE_*` es **pública** (queda en el JavaScript). Nunca secretos ahí.

### 8.3 Rutas de administración
- Todas bajo `/api/v1/admin/`, en un router con `dependencies=[Depends(require_admin)]` a nivel
  de router, para que ningún endpoint nuevo quede sin protección por olvido.
- El rol **nunca** se acepta desde el cuerpo de una request (registro siempre crea `user`).
  El primer admin se crea con un script de CLI (`scripts/create_admin.py`), no por la API.
- Acciones de admin se registran en el log de auditoría (quién, qué, cuándo).
- Verificación: tests 401 (sin token) y 403 (rol `user`) para **cada** ruta admin.

### 8.4 Autenticación
- PyJWT con lista explícita `algorithms=["HS256"]`; se validan `exp`, `iat`, `iss`, `aud` y `sub`.
- Access token corto (15 min). Refresh token con `jti` persistido, **rotación** en cada uso y
  **detección de reutilización** (si se reusa un refresh ya rotado, se revoca toda la familia).
- En el navegador: access token solo en memoria; refresh token en cookie `HttpOnly`, `Secure`,
  `SameSite=Strict`, `Path=/api/v1/auth`. Nunca tokens en `localStorage`.
- Login con respuesta idéntica y tiempo similar exista o no el email (evita enumeración de
  usuarios: si el email no existe, se verifica contra un hash ficticio).
- Logout revoca el refresh token. Cambio de contraseña revoca todas las sesiones.
- Verificación: tests de token expirado, firma inválida, `alg: none`, audiencia incorrecta,
  refresh reutilizado.

### 8.5 Acceso de usuarios (autorización)
- Los datos de buques y tránsitos son de lectura para cualquier usuario autenticado.
- Todo recurso que pertenezca a un usuario (perfil, sesiones; en el futuro, alertas) se consulta
  **siempre** filtrando por `user_id` del token, nunca por un id recibido del cliente.
  Acceder al recurso de otro usuario devuelve **404** (no revela que existe).
- Verificación: test por cada recurso propio en el que el usuario B intenta leer/modificar el
  recurso del usuario A.

### 8.6 Validación de entradas ("sanitización de formularios")
- **Validar, no mutar**: toda entrada pasa por un schema Pydantic con tipos estrictos, longitudes
  máximas, rangos y `extra="forbid"` (rechaza campos desconocidos, evita asignación masiva).
- No se "limpian" strings borrando caracteres: se rechazan si no son válidos y se **codifican
  al mostrarlos** (ver 8.7). Sanitizar la entrada corrompe datos y da falsa seguridad.
- Emails con `EmailStr`; MMSI `9` dígitos; bbox y fechas con rangos máximos.
- SQL solo parametrizado (SQLAlchemy). Prohibido construir SQL con f-strings o concatenación,
  incluido `text()`.
- Límite de tamaño de body (p. ej. 64 KB) y de mensajes WebSocket (p. ej. 4 KB).
- Los datos AIS son **entrada externa no confiable** (cualquiera con un transpondedor puede
  emitir un nombre de buque arbitrario): se validan en el parser igual que un formulario.

### 8.7 Protección contra XSS
- La API solo responde JSON (`application/json` / `problem+json`), nunca HTML con datos.
- Frontend: React escapa por defecto. **Prohibido** `dangerouslySetInnerHTML`, `innerHTML` y
  `Popup.setHTML()` de MapLibre con datos dinámicos; usar `setText()` o componentes React.
  Esto incluye nombres y destinos de buques que vienen de AIS.
- Content-Security-Policy estricta en el frontend (ver 8.11), sin `unsafe-inline` en scripts.
- Verificación: regla de ESLint que prohíbe `dangerouslySetInnerHTML`; test con un buque
  llamado `<img src=x onerror=alert(1)>` que debe mostrarse como texto.

### 8.8 Limitación de tasa (rate limiting)
- Dos capas: el reverse proxy (límite global por IP) y la app (límites finos con contador en
  Redis, compartido entre réplicas).
- Límites iniciales: login 5/min por IP y por email; register 3/min por IP; refresh 10/min;
  API general 120/min por usuario; conexiones WebSocket 5 simultáneas por usuario.
- Respuesta 429 con `Retry-After`. Librería `limits` con Redis (ADR-0007). Si Redis no responde,
  auth falla cerrado (503) y la API general falla abierto.

### 8.9 Endpoints de la API
- **Denegar por defecto**: todo endpoint requiere autenticación salvo una lista blanca explícita
  (`/health`, `/ready`, `/auth/register`, `/auth/login`, `/auth/refresh`, docs).
- Verificación: `tests/test_deny_by_default.py` recorre todas las rutas (del esquema OpenAPI:
  desde FastAPI 0.143 `app.routes` no lista las de los routers incluidos) y falla si una ruta
  fuera de la lista blanca responde sin token. Por eso `include_in_schema=False` está prohibido
  en `app/`.
- Paginación con tamaño máximo; rangos de fechas acotados; sin endpoints que devuelvan tablas
  completas.
- Errores sin stack traces ni detalles internos; los detalles van al log con un id de request.
- `/metrics` no se expone a Internet (solo red interna).
- WebSocket `/ws/live`: autenticación en el primer mensaje, validación del header `Origin`
  contra la lista de orígenes permitidos (CORS no protege WebSockets), límites de mensajes.
  La librería `websockets` escribe cada frame en DEBUG (`websockets.server` / `.client`): con
  tokens o API keys en los mensajes, su logger se fija en INFO como mínimo (ver el worker AIS).

### 8.10 CORS
- Lista explícita de orígenes desde `CORS_ORIGINS`; nunca `*` (y nunca `*` con credenciales).
- Métodos y headers permitidos explícitos (`GET`, `POST`, `DELETE`; `Authorization`,
  `Content-Type`). `allow_credentials=True` solo porque el refresh va en cookie.
- Producción: solo el dominio del frontend. Verificación: test que un origen no listado no recibe
  `Access-Control-Allow-Origin`.

### 8.11 Cabeceras de seguridad
- API (middleware): `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cache-Control: no-store` en respuestas de auth,
  `Cross-Origin-Resource-Policy: same-site`.
- Reverse proxy (producción): `Strict-Transport-Security: max-age=31536000; includeSubDomains`,
  redirección HTTP → HTTPS, ocultar versión del servidor.
- Frontend: `Content-Security-Policy` con `default-src 'self'`, `connect-src` solo a la API,
  `wss://` de la API y el proveedor de tiles; `frame-ancestors 'none'`; `object-src 'none'`.
- No usar `X-XSS-Protection` (obsoleto; los navegadores actuales lo ignoran).
- Verificación: test de cabeceras en la API; revisión con securityheaders.com en la Fase 7.

### 8.12 Modo de depuración
- Nunca `debug=True` en FastAPI; `--reload` solo en desarrollo local.
- En producción: `LOG_LEVEL=INFO` o superior, sin stack traces en respuestas, sin source maps
  publicados del frontend salvo decisión explícita.
- La documentación OpenAPI (`/docs`) puede quedar pública porque es parte del portafolio; no
  expone nada que no esté ya en el repo público.
- Verificación: test que en `APP_ENV=production` un error 500 no devuelve detalles internos.

### 8.13 Dependencias
- Rangos en `pyproject.toml` con mínimo = versión verificada y techo = siguiente mayor.
- Instalación reproducible con lockfiles con hashes (`requirements.lock`,
  `requirements-dev.lock`), regenerados con `uv pip compile ... --generate-hashes`.
- **Actualizar no es instalar lo último a ciegas**: Dependabot propone, el CI (tests + mypy +
  `pip-audit`) verifica, y solo entonces se mergea.
- `pip-audit` en CI falla el build si hay vulnerabilidades conocidas. `npm audit` en `web/`
  desde la Fase 4.

### 8.14 Paquetes no utilizados
- Solo se declaran dependencias que el código usa. Cada fase añade las suyas en el mismo PR que
  las usa (lista prevista en el comentario de `pyproject.toml`).
- Revisión en cada fase: ningún paquete declarado sin import (`deptry` o revisión manual).

### 8.15 Archivos expuestos
- `.gitignore` cubre `.env*`, llaves (`*.pem`, `*.key`), credenciales, volcados de DB y backups.
- `.dockerignore` impide que `.git`, `.env`, tests y docs entren en las imágenes.
- El servidor de estáticos no sirve dotfiles ni listados de directorio.
- Verificación: `gitleaks` + hook `detect-private-key`; revisar `docker history` de la imagen en
  la Fase 3.

### 8.16 Base de datos
- Nunca expuesta a Internet: en producción, sin puertos publicados (solo red interna de Docker).
  Lo mismo para Redis, que además exige contraseña.
- Mínimo privilegio: rol `canal_app` (SELECT/INSERT/UPDATE/DELETE en sus tablas, sin DDL) para
  la app; rol `canal_owner` solo para migraciones.
- Contraseñas largas y aleatorias; TLS si la DB no está en el mismo host.
- Backups automáticos, cifrados y con restauración probada (Fase 7).
- Consultas solo parametrizadas (8.6).

### 8.17 Hash de contraseñas
- Argon2id vía `pwdlib` (ADR-0003). Nunca MD5, SHA-x, ni cifrado reversible.
- Política (NIST SP 800-63B): mínimo 12 caracteres, máximo 128, sin reglas de composición
  forzadas. Rehash automático si cambian los parámetros de Argon2.
- Nunca loguear contraseñas ni hashes.

### 8.18 Historial de Git
- `gitleaks` como hook de pre-commit (`.pre-commit-config.yaml`) y en CI escaneando **todo** el
  historial (`fetch-depth: 0`).
- Commits con el email `noreply` de GitHub del dueño, no con el correo personal.
- Si un secreto llega a cualquier commit: **rotarlo inmediatamente** (se considera comprometido
  aunque se reescriba el historial), luego limpiar el historial si procede.

### 8.19 Auditoría integral
- Cada PR: checklist de seguridad de la plantilla + CI (gitleaks, pip-audit, tests de
  autorización, ruff con reglas `S` de bandit).
- Cierre de cada fase: revisar esta sección completa contra lo construido y anotar el resultado
  en el PR de cierre.
- Fase 7: auditoría final (dependencias, cabeceras, CORS, permisos de DB, capturas y docs).

### 8.20 Precisión
- Ningún cambio se da por bueno sin verificación ejecutable: tests, tipos, lint y CI verdes.
- Si una regla no puede cumplirse o choca con otra, **no improvisar**: detenerse, explicarlo en el
  issue/PR y proponer un ADR.
- No inventar APIs, opciones de librerías ni versiones: comprobarlas en la documentación oficial o
  ejecutándolas.

## 9. Estado actual

> **Fase actual: 3 — Ingesta AIS (worker) y tiempo real interno.** Las Fases 1 (esqueleto,
> CI y seguridad del repositorio, `v0.1.0`) y 2 (base de datos y autenticación, `v0.2.0`) están
> cerradas.

## 10. Comandos útiles

```bash
pip install --require-hashes -r requirements-dev.lock && pip install --no-deps -e .
pre-commit install               # hooks: gitleaks, detect-private-key, ruff
pytest                           # tests (configurados en pyproject.toml)
ruff check . && ruff format .    # lint + formato
mypy app                         # tipos
docker compose up -d --wait      # db + redis (desde Fase 2); contraseñas en .env
scripts/check_dev_services.sh    # verifica roles de la DB y contraseña de Redis
uvicorn app.main:app --reload    # API
python -m app.workers.ais_consumer  # worker AIS (desde Fase 3)
python scripts/ais_simulator.py serve  # tráfico AIS simulado (AISSTREAM_URL=ws://127.0.0.1:8765)
docker compose -f docker-compose.stack.yml up -d --build --wait  # pila completa en contenedores
```

## 11. Si algo no está claro

1. Revisar `docs/` y los ADRs.
2. Si persiste la duda: **preguntar al usuario antes de asumir** y documentar la decisión como ADR.
