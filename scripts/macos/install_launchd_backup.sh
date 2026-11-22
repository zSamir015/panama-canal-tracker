#!/usr/bin/env bash
# Instala, consulta o desinstala el LaunchAgent de macOS que hace la copia nocturna de la base.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este instalador solo aplica a macOS (Darwin)." >&2
  exit 1
fi

LABEL="com.panama-canal-tracker.backup"
KEYCHAIN_SERVICE="panama-canal-tracker-db-backup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WRAPPER="$REPO_DIR/scripts/macos/run_db_backup.sh"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/panama-canal-tracker"
DOMAIN="gui/$(id -u)"

usage() {
  cat <<EOF
Uso: $0 [--install | --status | --uninstall]

  --install    Instala (o actualiza) el LaunchAgent: una copia cada día a las 03:00 (por defecto).
  --status     Muestra si el agente está cargado y las últimas líneas del log.
  --uninstall  Descarga el agente y elimina el plist (no borra las copias ni el Keychain).
EOF
}

ACTION="install"
case "${1:-}" in
  "" | --install) ACTION="install" ;;
  --status) ACTION="status" ;;
  --uninstall) ACTION="uninstall" ;;
  -h | --help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$ACTION" == "status" ]]; then
  launchctl print "$DOMAIN/$LABEL" 2>/dev/null || echo "Agente $LABEL no cargado."
  if [[ -f "$LOG_DIR/backup.err.log" ]]; then
    echo "--- Últimas líneas de $LOG_DIR/backup.err.log ---"
    tail -n 20 "$LOG_DIR/backup.err.log"
  fi
  exit 0
fi

if [[ "$ACTION" == "uninstall" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "LaunchAgent $LABEL desinstalado."
  exit 0
fi

if ! security find-generic-password -a "$USER" -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1; then
  echo "Falta la contraseña de cifrado en el Keychain (servicio $KEYCHAIN_SERVICE)." >&2
  echo "Créala una vez, sin mostrarla, y guárdala también en tu gestor de contraseñas:" >&2
  echo "  security add-generic-password -a \"\$USER\" -s $KEYCHAIN_SERVICE -w \"\$(openssl rand -base64 32)\"" >&2
  exit 1
fi

chmod +x "$WRAPPER"
mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$WRAPPER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO_DIR</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>3</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/backup.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/backup.err.log</string>
</dict>
</plist>
EOF

chmod 600 "$PLIST_PATH"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"

echo "LaunchAgent instalado: $PLIST_PATH (cada día a las 03:00; si la Mac duerme, corre al despertar)."
echo "Copias en ~/Backups/panama-canal-tracker (14 días). Logs: $LOG_DIR/backup.out.log y backup.err.log"
echo "Prueba ahora mismo: launchctl kickstart $DOMAIN/$LABEL"
