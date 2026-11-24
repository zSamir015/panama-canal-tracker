#!/usr/bin/env bash
# Copia nocturna de la base local (issue #182, docs/BACKUP.md). La lanza el LaunchAgent
# `com.panama-canal-tracker.backup`, pero también sirve a mano.
#
# La contraseña de cifrado se lee del Keychain (servicio `panama-canal-tracker-db-backup`) y no
# se guarda en el plist ni en el repositorio. Variables opcionales: `BACKUP_DIR` (por defecto
# `~/Backups/panama-canal-tracker`), `BACKUP_KEEP_DAYS` (por defecto 14) y `BACKUP_SCRIPT`,
# `OFFSITE_REMOTE` (destino de rclone, por defecto `gdrive:panama-canal-tracker-backups`; vacío o sin
# rclone/remote configurado: no se sube nada).
set -euo pipefail

# launchd arranca con un PATH mínimo: hacen falta Homebrew (docker, gpg) y las rutas del sistema.
export PATH="${PATH:-/usr/bin:/bin}:/opt/homebrew/bin:/usr/local/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_DIR"

KEYCHAIN_SERVICE="panama-canal-tracker-db-backup"
BACKUP_DIR="${BACKUP_DIR:-$HOME/Backups/panama-canal-tracker}"
BACKUP_SCRIPT="${BACKUP_SCRIPT:-$REPO_DIR/scripts/db_backup.sh}"

if ! BACKUP_PASSPHRASE="$(security find-generic-password -a "$USER" -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)"; then
  echo "Error: falta la contraseña en el Keychain (servicio $KEYCHAIN_SERVICE). Ver docs/BACKUP.md." >&2
  exit 1
fi
export BACKUP_PASSPHRASE
export BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

# Colima arranca al iniciar sesión; si Docker aún no responde, se espera un poco antes de rendirse.
for _ in $(seq 1 20); do
  if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    break
  fi
  sleep 3
done
if ! docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  echo "Error: el contenedor db no está en marcha; no se hace la copia." >&2
  exit 1
fi

"$BACKUP_SCRIPT" "$BACKUP_DIR"

# Copia fuera del disco (ADR-0017). Va después de la copia local y su fallo no la invalida: la copia
# local ya está hecha, así que solo se avisa y se sale con error para que el log lo deje claro.
OFFSITE_REMOTE="${OFFSITE_REMOTE-gdrive:panama-canal-tracker-backups}"
if [ -n "$OFFSITE_REMOTE" ] && command -v rclone >/dev/null && rclone listremotes 2>/dev/null | grep -qx "${OFFSITE_REMOTE%%:*}:"; then
  # `copy` (no `sync`): borrar copias viejas en local no las borra en la nube.
  if ! rclone copy "$BACKUP_DIR" "$OFFSITE_REMOTE" --include "canal-*.dump.gpg*" --retries 3; then
    echo "Aviso: la copia local está hecha, pero falló la subida a $OFFSITE_REMOTE." >&2
    exit 1
  fi
else
  echo "Aviso: sin copia fuera del disco (falta rclone o el remote ${OFFSITE_REMOTE%%:*})." >&2
fi
