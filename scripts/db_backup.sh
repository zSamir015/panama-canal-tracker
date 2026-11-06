#!/usr/bin/env bash
# Copia de seguridad cifrada de la base de datos (tarea 7.2, docs/BACKUP.md).
#
#   BACKUP_PASSPHRASE='...' scripts/db_backup.sh [directorio]      # por defecto: ./backups
#
# Hace `pg_dump` (formato personalizado) dentro del contenedor `db` como `canal_owner`, lo cifra
# al vuelo con `gpg` (AES-256, con comprobación de integridad) y lo deja en
# `canal-AAAAMMDDTHHMMSSZ.dump.gpg` junto a su `.sha256`. Sin copia en claro en el disco: el volcado
# viaja por una tubería. La contraseña de cifrado va por un descriptor de fichero, nunca en la
# línea de comandos (se vería en `ps`). Variables: `DB_NAME` (por defecto `canal_tracker`) y
# `GPG` (ruta del binario, por defecto `gpg`).
set -euo pipefail

: "${BACKUP_PASSPHRASE:?Define BACKUP_PASSPHRASE (guárdala en un gestor de contraseñas: sin ella la copia no se puede leer)}"
if [ "${#BACKUP_PASSPHRASE}" -lt 20 ]; then
  echo "BACKUP_PASSPHRASE debe tener al menos 20 caracteres (openssl rand -base64 32)" >&2
  exit 2
fi
GPG=${GPG:-gpg}
command -v "$GPG" >/dev/null || { echo "Falta gpg en el equipo que ejecuta la copia" >&2; exit 2; }

db=${DB_NAME:-canal_tracker}
dir=${1:-backups}
umask 077  # solo el dueño lee las copias
mkdir -p "$dir"
file="$dir/canal-$(date -u +%Y%m%dT%H%M%SZ).dump.gpg"
partial="$file.partial"
trap 'rm -f "$partial"' EXIT

# `$1` es el nombre de la base: llega como argumento, no pegado al texto del comando.
docker compose exec -T db bash -c \
  'PGPASSWORD="$CANAL_OWNER_PASSWORD" pg_dump -h 127.0.0.1 -U canal_owner -d "$1" --format=custom' \
  _ "$db" |
  "$GPG" --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 \
    --symmetric --cipher-algo AES256 --compress-algo none --output "$partial" 3<<<"$BACKUP_PASSPHRASE"

[ -s "$partial" ] || { echo "La copia salió vacía: no se guarda" >&2; exit 1; }
mv "$partial" "$file"
trap - EXIT
(cd "$dir" && shasum -a 256 "$(basename "$file")" >"$(basename "$file").sha256")
echo "$file"
