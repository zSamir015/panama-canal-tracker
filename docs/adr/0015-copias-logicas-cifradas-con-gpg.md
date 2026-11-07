# ADR-0015: Copias lógicas cifradas con `pg_dump` y `gpg`

- **Fecha**: 2026-11-06
- **Estado**: Aceptada

## Contexto
AGENTS.md §8.16 pide "backups automáticos, cifrados y con restauración probada" y la tarea 7.2 del
roadmap repite lo mismo. La base es PostgreSQL 16 con PostGIS y TimescaleDB, y hoy no hay un
servidor desplegado (ADR-0011, ADR-0012): solo existe el contenedor de desarrollo. El volumen es
pequeño (la cobertura de AISStream en el Canal es escasa, `docs/DATA_SOURCES.md` §2b).

## Decisión
- **Copia lógica**: `pg_dump --format=custom` de toda la base, hecho dentro del contenedor `db`
  con el rol `canal_owner` (`scripts/db_backup.sh`). Se restaura en una base **nueva** con el
  superusuario y las funciones `timescaledb_pre_restore()` y `timescaledb_post_restore()`
  (`scripts/db_restore.sh`), que TimescaleDB exige para restaurar una base con hypertables,
  agregados continuos y compresión.
- **Cifrado con `gpg`** (`--symmetric`, AES-256), el mismo mecanismo del recolector de AIS
  (ADR-0012), que además comprueba la integridad: una copia alterada no se descifra. El volcado
  viaja por una tubería: nunca hay una copia en claro en el disco. La contraseña pasa por un
  descriptor de fichero, no por la línea de comandos.
- **La restauración se prueba de verdad** con `scripts/db_backup_check.sh`, que hace el ciclo
  completo sobre bases temporales y compara una huella del contenido, y comprueba que la
  comparación puede fallar.
- **La programación (cron, systemd) no forma parte de los scripts**: depende de dónde se despliegue
  y se documenta en `docs/BACKUP.md`.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Copias físicas con archivado de WAL (pgBackRest, WAL-G) | Permiten recuperar a un instante, pero necesitan un servidor, un destino de archivado y su operación; es mucho para una base de este tamaño y sin despliegue |
| `openssl enc` en lugar de `gpg` | Disponible en el contenedor, pero el cifrado CBC no comprueba la integridad; habría que añadir un MAC a mano |
| Cifrar con una clave pública (`gpg --encrypt`) | Evitaría guardar una contraseña en el servidor de copias, pero obliga a custodiar una clave privada aparte y complica la restauración; se puede adoptar más adelante |
| Confiar en el cifrado del disco o del destino | No protege la copia una vez sale de ese disco ni cuando alguien la lee con permisos |

## Consecuencias
- **Pérdida máxima de datos = el intervalo entre copias**; no hay recuperación a un instante.
- Hace falta `gpg` en el equipo que ejecuta la copia (ni el host de desarrollo ni la imagen de la
  base lo traen).
- La copia lleva hashes de contraseñas y refresh tokens: se trata como un secreto.
- Hay que restaurar en la misma versión de TimescaleDB que la copia; para subir de versión, se
  restaura y luego se actualiza la extensión.
- Esto cubre "copias cifradas y restauración probada" del roadmap; **"automáticos" queda pendiente
  de que haya un entorno de despliegue donde programarlo**.
