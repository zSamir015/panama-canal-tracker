# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: `v0.<fase>.0` al cerrar cada fase; `v1.0.0` al cerrar la Fase 7.

## [Unreleased]

### Changed
- Ficha del buque más clara (issue #125). Debajo del nombre hay una etiqueta de tipo con el
  color del mapa (el color va en el punto y el texto queda oscuro), y el MMSI va en monoespaciada.
  Los datos se reparten en "Movimiento" y "Buque", y el código AIS del tipo tiene fila propia. En
  móvil, si el buque elegido queda bajo la hoja o fuera de pantalla, el mapa lo centra en la parte
  visible (`easeTo`, sin animación con `prefers-reduced-motion`). El gris de texto secundario
  pasa de `#607d8b` (4,37:1) a `#546e7a` (5,4:1) para cumplir WCAG AA en texto pequeño.
- Interfaz en móvil (issue #123; por debajo de 640 px, el escritorio no cambia). Cabecera
  compacta y aviso de demo en una línea: a 390 px pasan de 208 a 67 px en la demo. La leyenda se
  pliega en una pastilla. "En tránsito ahora" es una barra al pie que se despliega como hoja
  inferior, y la ficha del buque es una hoja inferior (45 % de la altura). Mientras hay una hoja
  abierta, los controles y la atribución del mapa suben por encima y solo se ve un panel a la vez.
  Los botones de plegar llevan `aria-expanded` y `aria-controls`. Colores, radios y sombras pasan a
  variables CSS en `web/src/tokens.css`; los colores por tipo de buque siguen en TypeScript. Sin
  dependencias nuevas; el CSS crece 0,8 kB comprimido.
- Detector de tránsitos (issue #121, ADR-0016): un buque que pisa una zona de entrada con rumbo
  hacia el mar está saliendo del Canal y ya no abre un tránsito en sentido contrario. Sin rumbo
  fiable (sin COG o SOG, parado o de través) se abre como antes. El replay lee `sog` y `cog`. Con
  los datos reales de `docs/VALIDATION.md`, 24 abortados en lugar de 46 con el timeout de 30 min;
  ningún umbral cambia.
- Cobertura de AISStream remedida (2026-11-06): 11 posiciones de 10 buques en 5 min dentro del
  Canal, frente a 0 mensajes en octubre. Es escasa pero real; `docs/DATA_SOURCES.md` §2b y
  `docs/ARCHITECTURE.md` §8 ya no la dan por nula.

### Added
- Sección "How it was built" / "Cómo se construyó" en los dos README (tarea 7.5): enlaza el
  roadmap, los 15 ADR, los pull requests, los issues y las etiquetas de versión, y dice qué sigue
  abierto (validación con datos reales y despliegue).
- Revisión de seguridad (tarea 7.6, parcial): `docs/SECURITY_REVIEW.md` contrasta lo construido
  con AGENTS.md §8 (gitleaks sobre el historial, pip-audit, npm audit, búsqueda de patrones
  peligrosos, autores, imágenes y acciones fijadas, Dockerfile) y lista los hallazgos abiertos,
  sobre todo que no existe un entorno de producción donde aplicar HSTS, límites y bloqueos.
- Content-Security-Policy del frontend (AGENTS.md §8.11): se genera al compilar desde la
  configuración (API y tiles) con `web/csp.ts` y se pone en un `<meta>`. Scripts solo del propio
  origen, sin `unsafe-inline` ni `unsafe-eval`. Verificada en la demo con Chrome en tiempo real (0
  violaciones; mapa, buques y zonas); la app completa (login, API y WebSocket) sigue sin probar.
- Copias de seguridad cifradas y restauración probada (tarea 7.2, ADR-0015): `scripts/db_backup.sh`
  (`pg_dump` cifrado al vuelo con `gpg`, con suma SHA-256), `scripts/db_restore.sh` (restaura en
  una base nueva con `timescaledb_pre_restore`/`post_restore`, se niega a sobrescribir y borra lo
  que quede a medias) y `scripts/db_backup_check.sh`, la prueba de punta a punta: migra una base
  temporal, la rellena (con un chunk comprimido y los agregados), copia, restaura y compara filas,
  contenido, chunks comprimidos, políticas y permisos, y comprueba que detecta alteraciones.
  Procedimiento en `docs/BACKUP.md`. **La programación automática queda pendiente**: no hay
  entorno de despliegue donde programarla.
- OpenAPI completo (tarea 7.3): las 19 operaciones tienen resumen y descripción, y todos los
  cuerpos de petición y de respuesta llevan un ejemplo (`app/schemas/examples.py`, adjunto a cada
  modelo con `@with_example`; `/metrics` lleva uno en texto de Prometheus). Cada error documentado
  lleva un ejemplo `problem+json` con su código y su ruta, y el 422 incluye cómo se indica qué
  campo falla. Se corrige además el 422 que FastAPI documentaba por su cuenta (`HTTPValidationError`
  en JSON normal): la API real responde `problem+json` en todos los errores. `tests/test_openapi.py`
  exige todo lo anterior y valida cada ejemplo contra su modelo.
- `/ready` y `/metrics` (tarea 7.1, ADR-0014). `/ready` (público) comprueba la base y Redis y
  responde 503 con cuál falla, sin mensajes de error. `/metrics` exige el token de
  `METRICS_TOKEN` (401 siempre si no está configurado) y exporta, en el formato de texto de
  Prometheus escrito a mano, el estado del worker AIS (disponibilidad, conexión, cola, edad del
  último mensaje y contadores), `canal_dependency_up`, los tránsitos en curso y los buques
  esperando en fondeadero. Reglas de alerta en `docker/prometheus/canal-alerts.yml`, entre ellas
  más de 5 minutos sin mensajes, validadas con `promtool check rules` y con tests de reglas
  (`canal-alerts.test.yml`). No exporta métricas de peticiones HTTP.
- Panel "En tránsito ahora" (tarea 5.6): lista de los buques con tránsito `in_progress` (nombre,
  sentido Atlántico → Pacífico o al revés y cuánto llevan en el Canal) sobre el mapa. Se recarga
  cada 30 s con `GET /transits/current` y, al pulsar un buque, lo selecciona en el mapa y abre su
  ficha. No aparece en la demo estática (no hay API detrás). Nombres como texto, nunca HTML.
- Replay y trayectorias sintéticas (tarea 5.5): `scripts/transit_replay.py` pasa las posiciones
  del recolector por el detector y resume tránsitos por estado, abortos por motivo y completados
  por día y sentido (guía en `docs/AIS_COLLECTOR.md`). Tests nuevos: los dos sentidos completos
  con las rutas del simulador (~5 h 45 min), buques fondeados fuera de las entradas, buque
  detenido dentro de una entrada o en el lago, huecos de señal por debajo y por encima del
  timeout, y lectura tolerante del fichero.
- Endpoints de tránsitos (tarea 5.4): `GET /api/v1/transits` (paginado, filtros `direction`,
  `status` y ventana `from`/`to`, por defecto 7 días y como mucho 90), `GET /transits/current`
  (los `in_progress`) y `GET /transits/{id}`. Exigen token como el resto de la API.
- Detección de tránsitos en el worker (tarea 5.3): tabla `transits` (migración `20261106_0004`,
  con un índice único parcial que permite un solo tránsito `in_progress` por buque y la duración
  como columna generada) y `app/workers/transit_tracker.py`, que pasa por el detector las
  posiciones de cada lote guardado y escribe los eventos. Cada minuto aborta por timeout los
  tránsitos sin señal (`TRANSIT_SIGNAL_TIMEOUT_MINUTES`) y, al arrancar, reconstruye su estado
  desde la base para que un reinicio no pierda tránsitos en curso ni abra falsos con los buques
  parados en una entrada.
- Detector de tránsitos (tarea 5.2): `zone_at(lon, lat)` en `app/services/zones.py` (punto dentro
  de polígono por ray casting) y la máquina de estados pura de `app/services/transit_detector.py`.
  `on_position` abre, completa (con dirección y duración) o aborta por reversa o por timeout;
  `expire` cierra por timeout cuando el buque deja de emitir. Sin I/O: se prueba con
  trayectorias sintéticas (19 tests, verificados con pruebas de mutación). La integración en el
  worker y el modelo `transits` son la 5.3.
- Recolector de posiciones AIS reales en GitHub Actions (ADR-0012): `scripts/ais_collect.py`
  guarda en JSON Lines las posiciones y los datos estáticos del Canal (sin nombres ni destinos),
  con reconexión y espera creciente, y el workflow `collect-ais.yml` lo ejecuta en ventanas de
  340 min cada 6 h, cifra el fichero con `gpg` y lo sube como artefacto. Apagado por defecto
  (variable `AIS_COLLECT_ENABLED`). Guía en `docs/AIS_COLLECTOR.md`. Alimentará el replay (5.5) y la
  validación con datos reales (5.7) sin un servidor encendido.
- Zonas de entrada del Canal (tarea 5.1): polígonos aproximados de la entrada del Atlántico (bahía
  de Limón) y del Pacífico (Balboa) en `app/services/zones.py`, con tests de geometría (anillo
  cerrado, orden lon/lat, sentido antihorario, sin autocruces). `scripts/export_zones.py` genera la
  copia que lee el mapa, que las dibuja con contorno discontinuo y etiqueta; un test falla si la
  copia se desfasa. Se usarán en la detección de tránsitos (5.2 y 5.3).

## [0.6.0] - 2026-11-06

Fase 6: esperas en fondeo y estadísticas. Detección de esperas en los fondeaderos y su enlace con
el tránsito siguiente, agregados continuos y compresión de las posiciones, endpoints de
estadísticas y su vista en el frontend. Probado con datos sintéticos: los umbrales y los
polígonos no están contrastados con datos reales (tarea 5.7, pendiente). La fase 5 sigue abierta
y no hay `v0.5.0`.

### Added
- Vista de estadísticas (tarea 6.6): pestaña "Estadísticas" junto al mapa, con los tránsitos
  completados por día en barras apiladas por sentido (periodo de 7, 30 o 90 días), los totales por
  tipo de buque y las tablas de duración del tránsito y de espera en fondeo (cuenta, media,
  mediana y percentil 90). Gráfico en SVG a mano, sin librería de gráficas nueva. No aparece en
  la demo estática. Captura con datos de ejemplo en
  `docs/media/fase6-estadisticas-datos-de-ejemplo.png`.
- Compresión y histórico reducido de las posiciones (tarea 6.5, ADR-0005): los chunks de
  `positions` de más de 7 días se comprimen (agrupados por buque, ordenados por hora), sin borrar
  nada; se siguen leyendo y el `ON CONFLICT DO NOTHING` del writer sigue funcionando sobre ellos
  (probado). El agregado continuo `positions_5min` guarda la última posición de cada buque cada
  5 minutos, para consultar trayectorias de hace meses sin recorrer todas las posiciones; aún no
  lo lee ningún endpoint. La bajada descomprime y no pierde datos. Las políticas empiezan su
  primera pasada una hora después de la migración.
- Endpoints de estadísticas (tarea 6.4): `GET /api/v1/stats/daily` (tránsitos completados por día,
  sentido y categoría de buque), `/stats/transit-durations` y `/stats/waiting-times` (cuenta,
  media, mediana y percentil 90 en minutos, en total y por sentido o fondeadero), con ventana
  `from`/`to` (30 días por defecto, 365 como máximo). SQL directo con `percentile_cont`
  (ADR-0013). Las categorías de buque son las del mapa y salen de una sola lista de rangos
  (`app/services/ship_categories.py`) que alimenta Python y SQL.
- Agregado continuo `positions_hourly` (tarea 6.3, ADR-0013): una fila por buque y hora con el
  número de posiciones y la velocidad media y máxima, en tiempo real (suma lo posterior a la
  marca de agua) y con una política que lo refresca cada 30 minutos. Servirá para el tráfico
  (buques distintos por día) y para medir la cobertura de AISStream. Las estadísticas de
  tránsitos y esperas (6.4) se calculan con SQL: no son hypertables y tienen pocas filas al día.
- Tiempo de espera real (tarea 6.2): cada visita a un fondeadero se enlaza con el tránsito que la
  sigue (`anchorage_visits.transit_id`). Reglas puras en `app/services/waiting.py`: fondeadero del
  lado por el que el buque entra, la visita más reciente para cada tránsito y el primer tránsito
  posterior para cada visita, con un máximo de 24 h entre que se fue y entró. El
  `AnchorageTracker` lo reconcilia cada minuto sobre lo reciente sin enlazar (idempotente y sin
  depender del orden en que se guardan los eventos). `GET /transits/{id}` devuelve
  `anchorage_wait` con la llegada, la salida y los minutos de espera.
- Esperas en fondeo (tarea 6.1): polígonos aproximados de los fondeaderos del Atlántico y del
  Pacífico (`app/services/anchorages.py`, sin solape con las entradas), detector puro de visitas
  (`app/services/anchorage_detector.py`: parado 15 min dentro de un fondeadero, con la hora de
  llegada retrocedida al inicio de la parada; cierra al salir, navegar a 1 nudo o más, o perder la
  señal), tabla `anchorage_visits` (migración `20261106_0005`, una visita abierta por buque) y
  `AnchorageTracker` en el worker, con la misma restauración al arrancar que el de tránsitos.

## [0.4.0] - 2026-11-06

Fase 4: mapa en tiempo real. Frontend React + MapLibre con ficha del buque y estela de 30 min,
`WS /ws/live` con autenticación en el primer mensaje, reconexión y CI del frontend. La demo
pública corre en GitHub Pages con datos simulados (ADR-0011) y el WebSocket aguantó 500 clientes
en la prueba de carga, sin degradar la ingesta.

### Added
- Prueba de carga del WebSocket (tarea 4.8): `scripts/ws_load_test.py` abre 500 clientes
  (100 usuarios de prueba × 5 sockets) contra `/ws/live` con el simulador AIS y mide conexiones,
  tiempo al primer snapshot, CPU y memoria de la API y la tasa de ingesta. Resultado en
  `docs/LOAD_TEST.md`: 500/500 conectados, sin fallos y sin degradación medible de la ingesta.
- Demo estática en GitHub Pages (#79, tarea 4.7, ADR-0011): al compilar con `VITE_DEMO=true` la
  app salta el login y reproduce en bucle un JSON pregrabado con posiciones de buques generadas por
  `scripts/ais_simulator.py`. Etiqueta «⚠ Datos simulados» siempre visible. Workflow `pages.yml`
  despliega a Pages en cada push a `main`, con actions fijadas por SHA y permisos mínimos. No se
  usan datos de AISStream (ADR-0008).
- CI del frontend (#77, tarea 4.6): job `Frontend (web)` con `npm ci`, Prettier, ESLint (con la
  regla anti-XSS), `tsc -b`, Vitest, `vite build` y `npm audit`, con `setup-node` fijado por SHA y
  permisos de solo lectura. Test XSS de extremo a extremo por `/ws/live`: un nombre
  `<img onerror>` que llega en el snapshot se muestra como texto en la ficha.
- Reconexión y renovación de la sesión (#73, tarea 4.5): `useSession` recupera la sesión al
  cargar la página con la cookie del refresh, renueva el access token un minuto antes de caducar y
  cuando la API lo rechaza (401 o `4401`), con una sola renovación a la vez (también entre
  pestañas, con un Web Lock) porque reutilizar un refresh rotado revoca la sesión.
  `useLiveVessels` reconecta con backoff exponencial con jitter (1 s → 30 s, mínimo 15 s tras
  `4429`) o al volver la red, se suscribe otra vez y conserva los buques hasta el snapshot; un
  token renovado no reabre la conexión y `4400` no se reintenta. Indicador "Reconectando…" en la
  cabecera.
- Ficha del buque y estela (#70, tarea 4.4): `GET /api/v1/vessels/{mmsi}/history` devuelve la
  trayectoria como Feature GeoJSON `LineString` (`from`/`to`, por defecto los últimos 30 min,
  ventana máx. 7 días, como mucho 2000 puntos con `truncated`; `geometry: null` con menos de dos
  posiciones). En `web/`, clic en un buque: ficha en un panel de React (todo como texto, test con
  un nombre `<img onerror>`), aro sobre el buque seleccionado y estela como capa `line`, cortada
  donde faltan más de 5 min de señal. Primeras consultas con TanStack Query (sin reintentar los
  401); un 401 de la API vuelve al login como el cierre `4401` del WebSocket.
- Mapa en vivo (#67, tarea 4.3, ADR-0010): MapLibre GL con tiles de OpenFreeMap (sin key), los
  buques de `/ws/live` como una capa GeoJSON (flecha SDF girada por `cog`, punto si no hay rumbo,
  color por categoría de `ship_type`) y leyenda. Login mínimo con el access token solo en memoria;
  hook `useLiveVessels` (auth en el primer mensaje, suscripción al viewport con debounce, mensajes
  del servidor validados antes de aplicarlos). MapLibre va en un chunk aparte que se carga tras el
  login. Proxy de Vite para `/api` y `/ws` en desarrollo.
- `WS /ws/live` (#65, tarea 4.2): handshake solo desde `CORS_ORIGINS`, auth con el primer
  mensaje (5 s, cierre `4401`), snapshot del viewport desde PostgreSQL y lotes `update`/`remove`
  como mucho 1 por segundo a partir de Redis (`canal:vessels.live`), con una suscripción por
  réplica y backpressure por cliente (solo la última posición de cada buque). Límites: 5
  conexiones por usuario entre réplicas (Redis, con latido), mensajes de 4 KB, 20 mensajes cada
  10 s; uvicorn con `--ws-max-size`. El logger de `websockets` nunca baja de INFO. Los modelos
  del canal en vivo pasan a `app/schemas/live.py`, compartidos por el worker y la API.
- `web/` inicializado (#63, tarea 4.1): Vite + React + TypeScript `strict`, ESLint (reglas con
  tipos, hooks de React y prohibición de `dangerouslySetInnerHTML`/`innerHTML`/`setHTML`, con un
  test que comprueba que sigue activa), Prettier, Vitest + Testing Library, configuración `VITE_*`
  validada (solo `http(s)`, sin credenciales), build sin source maps y Dependabot para `npm`.
- Buques de todo el mundo con destino declarado al Canal (#59, ADR-0009): segunda conexión del
  worker a AISStream (bbox mundial, solo `ShipStaticData`, `AIS_CANAL_BOUND_ENABLED`) con cola y
  writer propios; detección de destinos (`app/services/canal_destination.py`) con códigos
  UN/LOCODE verificados, nombres de puerto y rutas, probada contra falsos positivos reales; tabla
  `canal_bound_vessels` (migración `20261022_0003`) y `GET /api/v1/vessels/canal-bound`.
- El parser lee el destino (validado: sin caracteres de control, máx. 64), la ETA (sin año en
  AIS: se elige el más cercano a la recepción; valores "no disponible" → `null`) y la posición de
  `MetaData` de los `ShipStaticData`.

### Changed
- AGENTS.md (regla 6) y DATA_SOURCES: como máximo dos conexiones por API key (antes, una).
- La recogida de lotes de la cola pasa a `app/workers/common.py` (`collect_batch`), compartida por
  los dos writers.

## [0.3.0] - 2026-10-21

Fase 3: ingesta AIS. Worker con una única conexión a AISStream → parser → PostgreSQL por lotes
→ Redis en vivo, API de buques y estado de la ingesta, simulador y pila completa en contenedores.
La prueba con la key real funciona, pero la cobertura de AISStream en el Canal es casi nula.

### Changed
- El simulador y las fixtures AIS usan el formato real de `MetaData` (`latitude`/`longitude` en
  minúsculas, `MMSI_String`, `time_utc`) y el relleno con espacios que entrega AISStream.

### Added
- Modelos y migración de `vessels` y `positions`: la tabla de posiciones usa una hypertable de
  TimescaleDB, `GEOGRAPHY(Point,4326)`, índices GIST y por buque/tiempo, clave foránea al buque
  y constraints para MMSI y valores AIS básicos.
- Parser de mensajes `PositionReport` y `ShipStaticData` de AISStream con validación de entrada,
  normalización de valores AIS no disponibles y protección frente a mensajes sobredimensionados.
- Simulador AIS (`scripts/ais_simulator.py`): tráfico reproducible por semilla con el formato de
  AISStream (tránsitos en ambos sentidos con velocidades por tramo, fondeos, pérdida de señal e
  inyección opcional de mensajes inválidos), en JSON Lines o como servidor WebSocket local que
  imita el protocolo de suscripción de AISStream. Todo lo que genera lo acepta el parser, y lo
  inválido lo rechaza con el motivo esperado.
- `websockets` como dependencia directa (ya llegaba con `uvicorn[standard]`, versión 17.2).
- Worker de ingesta (`python -m app.workers.ais_consumer`): una única conexión WebSocket con
  AISStream, suscripción al área del Canal al conectar, espera de la confirmación, backoff
  exponencial con jitter que se reinicia tras una conexión sana, cola acotada que descarta los
  mensajes más antiguos sin bloquear la lectura, rechazos contados por motivo y parada limpia con
  SIGTERM. Configuración: `AISSTREAM_API_KEY` (solo el worker; obligatoria para arrancar),
  `AISSTREAM_URL` (`wss://` en producción, sin credenciales en la URL),
  `AIS_RECONNECT_MAX_SECONDS` y `AIS_QUEUE_MAX_SIZE`. La key no aparece en los logs ni en DEBUG.
- Writer del worker AIS (`app/workers/ais_writer.py`, `app/repositories/ais.py`): guarda la cola
  en PostgreSQL por lotes (`AIS_BATCH_SIZE`, `AIS_BATCH_FLUSH_SECONDS`) en una transacción por
  lote; upsert de `vessels` que no borra datos conocidos con un `NULL` y solo adelanta
  `last_seen_at`; `positions` con `ON CONFLICT DO NOTHING` para mensajes repetidos; fila a fila
  con savepoints si la base rechaza un dato; reintentos con backoff si la base no responde. El
  worker vacía la cola antes de terminar.
- Publisher del worker AIS (`app/workers/ais_publisher.py`): tras guardar cada lote, publica en
  `canal:vessels.live` la última posición de cada buque con el formato de `/ws/live`, validada con
  Pydantic y con el nombre y el tipo aprendidos de los `ShipStaticData`. El estado del worker
  (consumer, cola y writer) se guarda en `canal:ais:worker:status` con `updated_at` y caducidad.
  Redis caído no frena la ingesta: timeout de 1 s, sin reintentos de la librería y pausa de 5 s
  tras un fallo. `redis` pasa a ser dependencia directa (7.4.1, el rango de `limits`).
- Endpoints de buques: `GET /api/v1/vessels` (paginado, filtros `ship_type` y `seen_since`
  acotados, parámetros desconocidos → 422) y `GET /api/v1/vessels/{mmsi}` (ficha y última
  posición; 404 si no existe). Requieren token y cuentan para el límite general.
- `GET /api/v1/admin/ingestion/status` (solo admin): estado del worker leído de Redis, con
  `available` y `stale`; 503 si Redis no responde; cada consulta queda en el log `audit`.
- `app/core/redis.py` (cliente y nombres de claves) y `app/schemas/ingestion.py` (contrato del
  estado) compartidos por el worker y la API.
- Imágenes Docker de la API y del worker (`Dockerfile` multi-stage, base fijada por digest,
  dependencias con hashes, usuario sin privilegios, sin secretos en capas) y pila completa en
  `docker-compose.stack.yml` (base y Redis sin puertos publicados, servicio `migrate` con el rol
  de DDL, API, worker y simulador opcional; solo lectura, sin capabilities). Healthcheck del
  worker por la frescura de su estado en Redis. Nuevo job de CI que construye las dos imágenes.
- Prueba con AISStream real (3.8): suscripción, formato y reconexión tras una desconexión
  forzada verificados; cobertura del Canal casi nula, documentada en `docs/DATA_SOURCES.md` §2b.
  `scripts/ais_coverage.py` mide la cobertura (solo recuentos) para seguirla varios días.
- ADR-0008: AISStream no publica términos de uso; los datos de buques solo se muestran a usuarios
  con sesión, sin modo anónimo. Revisión documentada en `docs/DATA_SOURCES.md`.

## [0.2.0] - 2026-10-20

Fase 2: base de datos y autenticación. Flujo register → login → endpoint protegido → refresh →
logout probado de extremo a extremo contra PostgreSQL y Redis reales (en local y en el CI).

### Changed
- El job `Tests (pytest)` del CI ejecuta también los tests de integración: levanta el mismo
  `docker-compose.yml` de desarrollo con credenciales aleatorias de cada ejecución (enmascaradas,
  nunca secretos del repositorio), comprueba roles y permisos con `scripts/check_dev_services.sh`,
  aplica las migraciones a una base vacía con `alembic check`, y exige un 80 % de cobertura
  (`fail_under`).
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
- Tests de aceptación de la fase (`tests/integration/test_phase2_acceptance.py`): el flujo
  completo como un navegador, y la fuerza bruta contra el login frenada con 429 por el contador
  en Redis.

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
