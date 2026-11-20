#!/usr/bin/env bash
# Instala, consulta o desinstala el LaunchAgent de macOS para mantener encendido el worker AIS local.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este instalador solo aplica a macOS (Darwin)." >&2
  exit 1
fi

LABEL="com.panama-canal-tracker.worker"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WRAPPER="$REPO_DIR/scripts/macos/run_worker_caffeinate.sh"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/panama-canal-tracker"
DOMAIN="gui/$(id -u)"

usage() {
  cat <<EOF
Uso: $0 [--install | --status | --uninstall]

  --install    Instala (o actualiza) el LaunchAgent y arranca el worker (por defecto).
  --status     Muestra si el agente está cargado en launchd y las últimas líneas del log.
  --uninstall  Detiene el agente y elimina el fichero plist.
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
  if [[ -f "$LOG_DIR/worker.err.log" ]]; then
    echo "--- Últimas líneas de $LOG_DIR/worker.err.log ---"
    tail -n 20 "$LOG_DIR/worker.err.log"
  fi
  exit 0
fi

if [[ "$ACTION" == "uninstall" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "LaunchAgent $LABEL desinstalado."
  exit 0
fi

if [[ ! -x "$WRAPPER" ]]; then
  chmod +x "$WRAPPER"
fi

if [[ ! -f "$REPO_DIR/.env" ]]; then
  echo "Aviso: falta $REPO_DIR/.env; créalo desde .env.example con tu AISSTREAM_API_KEY antes de que arranque." >&2
fi

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
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>15</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/worker.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/worker.err.log</string>
</dict>
</plist>
EOF

chmod 600 "$PLIST_PATH"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"

echo "LaunchAgent instalado y arrancado: $PLIST_PATH"
echo "Logs: $LOG_DIR/worker.out.log y $LOG_DIR/worker.err.log"
echo "El worker arranca con AIS_CANAL_BOUND_ENABLED=false (puede correr a la vez que collect-ais.yml, ADR-0019)."
