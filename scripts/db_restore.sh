#!/usr/bin/env bash
# Restaura una copia cifrada en una base NUEVA (tarea 7.2, docs/BACKUP.md).
#
#   BACKUP_PASSPHRASE='...' scripts/db_restore.sh canal-AAAA...dump.gpg nombre_de_la_base_nueva
#
# Nunca sobrescribe: si la base de destino ya existe, se niega. Para sustituir una base hay que
# borrarla antes a mano, sabiendo lo que se hace. Como TimescaleDB lo exige, se llama a
# `timescaledb_pre_restore()` antes de `pg_restore` y a `timescaledb_post_restore()` después.
# Se restaura con el superusuario del contenedor, conservando dueños y permisos de la copia: los
# roles `canal_owner` y `canal_app` tienen que existir en el servidor (los crea la inicialización).
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Define BACKUP_PASSPHRASE}"
[ $# -eq 2 ] || { echo "Uso: $0 <copia.dump.gpg> <base_nueva>" >&2; exit 2; }
backup=$1
target=$2
GPG=${GPG:-gpg}
command -v "$GPG" >/dev/null || { echo "Falta gpg" >&2; exit 2; }
[ -f "$backup" ] || { echo "No existe $backup" >&2; exit 2; }
# El nombre acaba en comandos de SQL: solo letras, números y guion bajo.
[[ $target =~ ^[a-z][a-z0-9_]{0,62}$ ]] || { echo "Nombre de base no válido: $target" >&2; exit 2; }

if [ -f "$backup.sha256" ]; then
  (cd "$(dirname "$backup")" && shasum -a 256 -c "$(basename "$backup").sha256" >/dev/null) ||
    { echo "La suma de comprobación no coincide: la copia está dañada o la tocaron" >&2; exit 1; }
fi

su() {  # SQL como superusuario, sin eco de avisos
  docker compose exec -T -e PGOPTIONS='-c client_min_messages=warning' db bash -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 -qtA "$@"' _ "$@"
}

exists=$(su -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = '$target'")
[ "$exists" = 0 ] || { echo "La base $target ya existe: no se sobrescribe" >&2; exit 1; }

su -d postgres -c "CREATE DATABASE $target OWNER canal_owner"
cleanup_on_failure() { echo "Falló la restauración: se borra la base $target a medias" >&2; su -d postgres -c "DROP DATABASE IF EXISTS $target WITH (FORCE)" >/dev/null || true; }
trap cleanup_on_failure ERR

# TimescaleDB exige que `CREATE EXTENSION` sea el primer comando de la sesión: va solo y antes.
su -d "$target" -c "CREATE EXTENSION IF NOT EXISTS timescaledb"
su -d "$target" -c "CREATE EXTENSION IF NOT EXISTS postgis"
su -d "$target" -c "SELECT timescaledb_pre_restore()" >/dev/null

"$GPG" --batch --quiet --pinentry-mode loopback --passphrase-fd 3 --decrypt "$backup" 3<<<"$BACKUP_PASSPHRASE" |
  docker compose exec -T db bash -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h 127.0.0.1 -U postgres -d "$1" --exit-on-error' _ "$target"

su -d "$target" -c "SELECT timescaledb_post_restore()" >/dev/null
trap - ERR
echo "Restaurada en la base $target"
