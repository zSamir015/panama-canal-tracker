# Recolector AIS en GitHub Actions

Guía de uso del recolector (ADR-0012). Acumula posiciones AIS reales del Canal sin un servidor
encendido, para el replay (tarea 5.5) y la validación con datos reales (tarea 5.7).

## Cómo funciona

El workflow `Collect AIS` se conecta a AISStream durante 340 minutos (~5 h 40 min), guarda las
posiciones en JSON Lines, las cifra con `gpg` y sube el artefacto (`job collect`, solo con
`contents: read`). Cuando ese job termina **con éxito** en `main` (y `AIS_COLLECT_ENABLED` sigue en
`true`), un job separado `chain` (sin secretos ni acciones de terceros, solo `actions: write` y
`timeout-minutes: 5`) comprueba que no exista otro run pendiente y dispara la siguiente ventana con
`gh workflow run collect-ais.yml --ref main`, reduciendo los huecos frente al cron (~52 % → ~95 %).
El cron cada 6 horas queda como respaldo si la cadena se corta. Está **apagado por defecto**.

## Activarlo (una vez)

1. Genera una contraseña de cifrado y guárdala en tu gestor de contraseñas (sin ella no podrás
   leer los datos):

   ```bash
   openssl rand -base64 32
   ```

2. En GitHub, *Settings → Secrets and variables → Actions → Secrets*, crea dos secretos del
   repositorio:
   - `AISSTREAM_API_KEY`: tu key de AISStream.
   - `AIS_COLLECT_PASSPHRASE`: la contraseña del paso 1.

3. En *Variables*, crea `AIS_COLLECT_ENABLED` con el valor `true`.

4. Para probar sin esperar al cron ni iniciar bucle continuo: *Actions → Collect AIS → Run
   workflow*, con `minutes` en `5` y **`chain` desmarcado (`false`)**.
   Si quieres arrancar la captura continua al instante, déjalo con `minutes=340` y `chain=true`.

Worker local y recolector pueden ejecutarse **a la vez solo con `AIS_CANAL_BOUND_ENABLED=false`**
en el worker (`1` conexión del worker + `1` del recolector = `2` conexiones, ADR-0019). Si prefieres
usar `AIS_CANAL_BOUND_ENABLED=true`, apaga antes `AIS_COLLECT_ENABLED=false`.

## Apagarlo

Cambia `AIS_COLLECT_ENABLED` a `false` (o bórrala). Los workflows programados también se
desactivan solos tras 60 días sin actividad en el repositorio.

## Descargar y descifrar los datos

Los artefactos se llaman `ais-<run>-<intento>` y caducan a los 90 días. El fichero va cifrado
porque el repositorio es público:

```bash
gh run list --workflow=collect-ais.yml                         # elige un run
gh run download <run-id> --dir data/collected                  # baja el artefacto
read -rs AIS_PASS                                              # escribe la contraseña (no queda en el historial)
printf '%s' "$AIS_PASS" | gpg --batch --pinentry-mode loopback --passphrase-fd 0 \
  --decrypt data/collected/ais-*/ais.jsonl.gpg > data/collected/ais-<run-id>.jsonl
unset AIS_PASS
```

`data/` está en `.gitignore`: los datos descifrados no se suben nunca a git.

## Formato

Una línea JSON por mensaje:

```json
{"kind":"position","mmsi":353123000,"received_at":"2026-11-06T12:00:00+00:00","lat":9.3,"lon":-79.9,"sog":12.5,"cog":181.0,"heading":180,"nav_status":0}
{"kind":"static","mmsi":353123000,"received_at":"2026-11-06T12:00:05+00:00","ship_type":70,"length_m":294.0,"beam_m":32.0}
```

No se guardan nombres ni destinos de buques.

## Replay con el detector de tránsitos

`scripts/transit_replay.py` pasa las posiciones grabadas por la misma máquina de estados que usa
el worker (sin base de datos ni red) y resume qué tránsitos habría detectado:

```bash
python scripts/transit_replay.py data/collected/ais-*.jsonl                       # resumen
python scripts/transit_replay.py data/collected/ais-*.jsonl --json                # un tránsito por línea
python scripts/transit_replay.py data/collected/ais-*.jsonl --timeout-minutes 60  # otro timeout
```

El resumen da el periodo, las posiciones y los buques, los tránsitos por estado, los abortados
por motivo y los completados por día y sentido: es lo que se compara con las estadísticas de la
ACP en la tarea 5.7. Las líneas que no son posiciones válidas se omiten y se cuentan por motivo.
Con varios ficheros los trata como uno solo, ordenado por hora.

Un buque que se ve por primera vez a mitad del Canal y sale por una entrada abre un tránsito
desde esa entrada (la regla del detector es "aparece en una entrada"), que queda `in_progress`
hasta que el timeout lo aborta. Con cobertura parcial esto produce tránsitos falsos de corta
vida; medirlos es parte de la validación de la 5.7.

## Importar a la base local

`scripts/import_collected.py` carga esos ficheros en la base que lee la app (la de `.env`), para
tener el histórico recolectado en local junto a lo que guarda el worker:

```bash
python scripts/import_collected.py            # ensayo: cuenta lo que haría y no escribe nada
python scripts/import_collected.py --apply    # escribe (haz antes una copia: docs/BACKUP.md)
```

- **Buques y posiciones**: un buque por MMSI (con tipo, eslora y manga si el recolector los vio) y
  todas las posiciones válidas. Las que ya estaban (misma hora y MMSI) se omiten: repetir el
  comando no duplica nada.
- **Tránsitos y visitas a fondeo**: se recalculan con los mismos detectores y el mismo timeout que
  el worker (`TRANSIT_SIGNAL_TIMEOUT_MINUTES`) y solo se guardan los ya **cerrados**. Lo que siga
  abierto al terminar los datos, y cualquier fila que se solape en el tiempo con una ya guardada
  del mismo buque, no se toca: así no se pisa el estado del worker.
- **Qué se ve en la app**: el mapa en vivo solo enseña buques con una posición de los últimos 30
  minutos (`LIVE_WINDOW`), así que no cambia. Las estadísticas solo cuentan tránsitos
  *completados*, y con el timeout de 30 min la validación (`docs/VALIDATION.md`) da 0: tampoco se
  llenan. Lo importado sirve para `GET /transits`, el historial y las estelas de un buque
  (`/vessels/{mmsi}/history`, hasta 7 días) y las consultas directas a la base.
- Los datos del recolector no traen nombres de buque.

## Límites

- Entre el fin de una ventana encadenada y el arranque de la siguiente suele haber apenas 1–2 minutos
  de transición; si GitHub Actions retrasa la cola, el respaldo cron de cada 6 h reanuda la cadena.
- La cobertura de AISStream en el Canal es escasa (`docs/DATA_SOURCES.md` §2b): es normal que
  una ventana de casi 6 horas deje pocos miles de líneas.
- Las condiciones de GitHub piden usar Actions para probar, desplegar y publicar el proyecto.
  El recolector está cerca de ese límite (ADR-0012, consecuencias).
