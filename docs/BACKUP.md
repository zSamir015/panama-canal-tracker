# Copias de seguridad y restauración

Procedimiento de las copias de la base de datos (tarea 7.2, ADR-0015). Lo que está probado y lo
que no está claro al final, en "Límites".

## Qué es una copia

Un volcado lógico de PostgreSQL (`pg_dump`, formato personalizado) de toda la base: usuarios,
buques, posiciones (incluidos los chunks comprimidos), tránsitos, visitas a fondeaderos y los
agregados continuos de TimescaleDB, con sus dueños y permisos. Se cifra al vuelo con `gpg`
(AES-256 con comprobación de integridad) y no hay copia en claro en el disco. Lleva datos
sensibles (hashes Argon2 de contraseñas y los refresh tokens): trátala como un secreto.

## Hacer una copia

```bash
export BACKUP_PASSPHRASE="$(openssl rand -base64 32)"   # solo la primera vez; guárdala ya
scripts/db_backup.sh /ruta/a/las/copias                  # por defecto: ./backups
```

Crea `canal-AAAAMMDDTHHMMSSZ.dump.gpg` y su `.sha256`, y imprime la ruta. **Sin la contraseña la
copia no se puede leer**: guárdala en un gestor de contraseñas, aparte de las copias. Necesita
`gpg` en el equipo que la ejecuta y la pila de `docker compose` en marcha. `DB_NAME` cambia la base
(por defecto `canal_tracker`).

## Restaurar

```bash
BACKUP_PASSPHRASE='...' scripts/db_restore.sh canal-20261106T030000Z.dump.gpg canal_restaurada
```

Restaura en una base **nueva**: si el nombre ya existe, se niega (para sustituir una base hay que
borrarla antes a mano). Comprueba la suma `.sha256` si está junto a la copia, llama a
`timescaledb_pre_restore()` y `timescaledb_post_restore()` como exige TimescaleDB, y si algo falla
borra la base a medias. Después se apunta la aplicación a la base restaurada
(`DATABASE_URL` y `MIGRATIONS_DATABASE_URL`) y se comprueba con `/ready` y las estadísticas.

Requisitos del servidor de destino: PostgreSQL 16 con PostGIS y TimescaleDB de la **misma versión**
que la de la copia (hoy 2.30.2); para pasar a una más nueva se restaura primero y se actualiza la
extensión después. Y los roles `canal_owner` y `canal_app` ya creados (`docker/db/initdb/100_canal_roles.sh`).

## Comprobar que funciona

```bash
docker compose up -d --wait && scripts/db_backup_check.sh
```

Es la prueba de punta a punta, y debe repetirse en el entorno real tras cualquier cambio en estos
scripts o en la versión de TimescaleDB. Crea una base temporal, la migra, la rellena (con un chunk
comprimido, los agregados refrescados y datos enlazados), hace una copia, la restaura en otra base
y compara una huella (filas y suma MD5 del contenido) de cada tabla y agregado, los chunks
comprimidos, las políticas y los permisos de `canal_app`. Además comprueba que:

- la comparación detecta un dato alterado (si no pudiera fallar, no valdría);
- se niega a restaurar sobre una base existente;
- rechaza una copia alterada, con y sin fichero de suma, y una contraseña equivocada, sin dejar
  bases a medias.

Borra las dos bases y los temporales al terminar (`KEEP_DATABASES=1` las conserva para
inspeccionarlas). No toca `canal_tracker`.

## Programarlas

Las copias **no se programan solas**: no hay todavía un servidor desplegado (ADR-0011, ADR-0012),
y programarlas es cosa del entorno donde viva la base. En un servidor Linux, con `cron` (cada
noche a las 03:00, quedándose con las de los últimos 14 días):

```cron
0 3 * * * cd /opt/panama-canal-tracker && BACKUP_PASSPHRASE="$(cat /etc/canal/backup-passphrase)" scripts/db_backup.sh /var/backups/canal && find /var/backups/canal -name 'canal-*.dump.gpg*' -mtime +14 -delete
```

El fichero de la contraseña con permisos `600`, fuera del repositorio y de las copias. Conviene
llevar las copias a otro disco o a otro sitio: una copia en la misma máquina no protege de perderla.

## Límites

- **Pérdida máxima de datos = el intervalo entre copias.** Es un volcado lógico, no archivado de
  WAL: no hay recuperación a un instante concreto. Con una copia nocturna, hasta un día de
  posiciones. Las posiciones se vuelven a recibir de AISStream solo mientras lleguen en directo;
  lo que ocurrió mientras la base estaba caída no se recupera.
- **Probado solo contra el contenedor de desarrollo** y bases temporales, con datos sintéticos.
  No se ha restaurado nunca una copia de una base de producción (no existe) ni con volumen real.
  Con datos reales conviene medir cuánto tarda la copia y la restauración.
- **Programación y copias fuera de la máquina: sin hacer ni probar.**
- El volcado de `pg_dump` avisa de claves foráneas circulares en el catálogo de TimescaleDB; la
  restauración funciona (está en la prueba) porque se hace con el superusuario y con las funciones
  `pre_restore` y `post_restore`.
- La contraseña de cifrado no se rota sola: si cambia, las copias antiguas siguen necesitando la
  vieja. Guarda cada contraseña mientras guardes copias hechas con ella.
- Las copias son del dueño: se crean con `umask 077`, pero nada impide que alguien las copie con
  permisos de lectura. `backups/`, `*.dump.gpg` y `*.sha256` están en `.gitignore`.
