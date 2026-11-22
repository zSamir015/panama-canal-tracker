# Operación

Cómo se ejecuta y se mantiene Panama Canal Tracker una vez terminado. Describe el entorno real
del proyecto: una pila local con `docker compose` y la demo estática de GitHub Pages, sin servidor
de producción (ADR-0017). Para desplegarlo en un servidor, ver los requisitos al final de
`docs/SECURITY_REVIEW.md`.

## Qué corre y dónde

| Componente | Dónde | Cómo se arranca |
|---|---|---|
| PostgreSQL 16 con PostGIS y TimescaleDB (`db`) | Contenedor, `127.0.0.1:5432` | `docker compose up -d --wait` |
| Redis (`redis`) | Contenedor, `127.0.0.1:6379` | `docker compose up -d --wait` |
| API (FastAPI) | Proceso en el equipo, `:8000` | `uvicorn app.main:app` |
| Worker de ingesta | Proceso en el equipo | `python -m app.workers.ais_consumer`, o el agente de `launchd` |
| Frontend (desarrollo) | Proceso en el equipo, `:5173` | `cd web && npm run dev` |
| Recolector de AIS | GitHub Actions, workflow `Collect AIS` | Automático, ver `docs/AIS_COLLECTOR.md` |
| Demo estática | GitHub Pages | Se publica en cada cambio a `main` |

La base de datos y Redis solo escuchan en `127.0.0.1`. El frontend de desarrollo reenvía `/api` y
`/ws` a `localhost:8000`; se debe abrir por `localhost`, no por `127.0.0.1`, porque `/ws/live`
valida el origen.

Hay una segunda pila, `docker-compose.stack.yml`, con la API y el worker también en contenedores,
sin puertos publicados para la base ni para Redis y con cada servicio recibiendo solo sus
variables. Con el perfil `simulator` genera tráfico AIS sintético sin clave de AISStream.

## Arranque desde cero

```bash
cp .env.example .env              # y rellenar los secretos: nunca se versiona
docker compose up -d --wait       # db y redis
scripts/check_dev_services.sh     # comprueba los roles de la base y la contraseña de Redis
alembic upgrade head              # migraciones (con MIGRATIONS_DATABASE_URL, el rol con DDL)
uvicorn app.main:app              # API
python -m app.workers.ais_consumer  # worker (necesita AISSTREAM_API_KEY)
cd web && npm ci && npm run dev   # frontend
```

El primer administrador se crea con `scripts/create_admin.py`; el registro desde la interfaz solo
crea usuarios con rol `user`.

## Worker en macOS

`docs/LOCAL_WORKER_MAC.md` describe el agente de `launchd` que mantiene el worker en marcha:
arranca al iniciar sesión, se reinicia si se cae y evita el reposo mientras el equipo está
enchufado.

```bash
./scripts/macos/install_launchd_worker.sh            # instala y arranca
./scripts/macos/install_launchd_worker.sh --status   # estado y últimas líneas del log
./scripts/macos/install_launchd_worker.sh --uninstall
```

Logs en `~/Library/Logs/panama-canal-tracker/worker.out.log` y `worker.err.log`. Colima (el motor
de Docker) arranca con `brew services` al iniciar sesión, y `db` y `redis` se reinician solos.

AISStream permite como máximo dos conexiones por clave. El worker local usa una (con
`AIS_CANAL_BOUND_ENABLED=false`) y el recolector de GitHub otra; no se debe arrancar un segundo
worker ni `scripts/ais_coverage.py` mientras los dos estén activos (ADR-0009, ADR-0019).

## Copias de seguridad

Una copia lógica cifrada cada noche a las 03:00, con retención de 14 días:

```bash
./scripts/macos/install_launchd_backup.sh            # instala el agente
./scripts/macos/install_launchd_backup.sh --status
launchctl kickstart gui/$(id -u)/com.panama-canal-tracker.backup   # copia ahora
```

Las copias quedan en `~/Backups/panama-canal-tracker`. La contraseña de cifrado está en el
Keychain (servicio `panama-canal-tracker-db-backup`) y debe guardarse también en un gestor de
contraseñas: sin ella las copias no se pueden abrir. Las copias están en el mismo disco que la base
de datos, así que conviene copiarlas de vez en cuando a otro disco.

Restaurar, siempre en una base nueva (el script se niega a sobrescribir):

```bash
BACKUP_PASSPHRASE='...' scripts/db_restore.sh canal-AAAAMMDDTHHMMSSZ.dump.gpg canal_restaurada
```

El procedimiento completo y sus límites están en `docs/BACKUP.md`.

## Datos recolectados

El recolector acumula posiciones reales en artefactos cifrados de GitHub Actions. Para descargarlos,
descifrarlos, reproducirlos con el detector o cargarlos en la base local, ver
`docs/AIS_COLLECTOR.md`:

```bash
python scripts/transit_replay.py data/collected/ais-*.jsonl   # qué tránsitos habría detectado
python scripts/import_collected.py                            # ensayo: cuenta, no escribe
python scripts/import_collected.py --apply                    # carga en la base local
```

Antes de `--apply`, hacer una copia de seguridad. El importador no toca lo abierto ni lo que se
solape con filas existentes, y repetirlo no duplica nada. Los ficheros descifrados viven en
`data/collected/`, que está en `.gitignore`.

## Comprobar que funciona

- `GET /ready` responde 200 si la API alcanza la base de datos y Redis; `GET /health` solo dice que
  el proceso vive.
- `GET /metrics` en formato Prometheus, con `Authorization: Bearer <METRICS_TOKEN>`. Las alertas
  están en `docker/prometheus/canal-alerts.yml`.
- El worker escribe en su log, cada minuto, contadores de ingesta (`received`,
  `positions_written`, `dropped`) y del detector (`transit_stats`, `anchorage_stats`).
- Cuántas posiciones han llegado:

  ```sql
  select count(*), max(received_at) from positions;
  select count(distinct vessel_mmsi) from positions where received_at > now() - interval '30 minutes';
  ```

## Rotación de secretos

| Secreto | Dónde vive | Efecto de cambiarlo |
|---|---|---|
| `JWT_SECRET_KEY` | `.env` | Todas las sesiones dejan de valer; los usuarios inician sesión de nuevo |
| `AISSTREAM_API_KEY` | `.env` y secreto de repositorio `AISSTREAM_API_KEY` | Hay que reiniciar el worker y actualizar el secreto del recolector |
| `AIS_COLLECT_PASSPHRASE` | Secreto de repositorio y Keychain | Los artefactos nuevos se cifran con la nueva; los viejos siguen necesitando la antigua |
| Contraseña de copias | Keychain y gestor de contraseñas | Las copias antiguas siguen necesitando la contraseña con la que se hicieron |
| `POSTGRES_PASSWORD`, `CANAL_OWNER_PASSWORD`, `CANAL_APP_PASSWORD`, `REDIS_PASSWORD` | `.env` | Hay que cambiarlas también dentro de PostgreSQL y de Redis; no basta con el `.env` |

`gh secret set NOMBRE` sin entrada interactiva guarda un secreto vacío sin avisar; el workflow del
recolector lo detecta y falla. Que un secreto aparezca en `gh secret list` no demuestra que tenga
valor.

## Problemas conocidos

- Docker no responde: Colima no ha arrancado. `brew services list` y `colima status`.
- El worker no escribe: comprobar `worker.err.log`. La causa habitual es que AISStream cierre la
  conexión por exceso de conexiones con la misma clave.
- El mapa en vivo está casi vacío: es la cobertura de AISStream, no un fallo. Solo se ven los
  buques con una posición de los últimos 30 minutos (`docs/VALIDATION.md`).
- Estadísticas vacías: solo cuentan tránsitos completados, y con la cobertura gratuita casi no
  hay ninguno (`docs/VALIDATION.md`).
- Un test de integración falla una vez y pasa al repetir: los hay sensibles al tiempo, por
  ejemplo el de caducidad del token del WebSocket en un ejecutor lento. Relanzar el job; si se
  repite, es un fallo real.
- `docker compose exec` dentro de un bucle `while read` se come la entrada del bucle: añadir
  `</dev/null`.
- zsh no separa una variable con varias rutas: escribir las rutas o usar un array.

## Qué no cubre

No hay servidor, proxy con TLS, copias fuera de la máquina ni monitorización activa. Es lo que
exigiría un despliegue público y está listado como requisito previo en `docs/SECURITY_REVIEW.md`.
