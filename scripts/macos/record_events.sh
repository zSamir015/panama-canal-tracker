#!/usr/bin/env bash
# Graba la pantalla cuando el worker local registra un tránsito o una espera en fondeo.
# Uso: scripts/macos/record_events.sh [segundos]   (por defecto 90)
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este script solo aplica a macOS (Darwin)." >&2
  exit 1
fi

SECS="${1:-90}"
LOG="${PCT_WORKER_LOG:-$HOME/Library/Logs/panama-canal-tracker/worker.out.log}"
OUT="${PCT_VIDEO_DIR:-$HOME/Movies/panama-canal-tracker}"
URL="${PCT_APP_URL:-http://localhost:5173}"
MAX_FILES=40

mkdir -p "$OUT"
last=0

tail -n 0 -F "$LOG" | while read -r line; do
  case "$line" in
    *'"event": "transit_event"'*) prefix="transito" ;;
    *'"event": "anchorage_event"'*) prefix="fondeo" ;;
    *) continue ;;
  esac

  now=$(date +%s)
  # Un solo video por ráfaga de eventos.
  if (( now - last < SECS )); then continue; fi
  last=$now

  kind=$(sed -n 's/.*"kind": "\([A-Za-z]*\)".*/\1/p' <<<"$line")
  mmsi=$(sed -n 's/.*"mmsi": \([0-9]*\).*/\1/p' <<<"$line")
  file="$OUT/${prefix}-$(date +%Y%m%d-%H%M%S)-${kind}-${mmsi}.mov"

  open "$URL" >/dev/null 2>&1 || true
  sleep 3
  screencapture -v -V "$SECS" -x "$file"
  echo "$(date '+%F %T') grabado $file" >>"$OUT/recorder.log"

  # Conserva solo los últimos MAX_FILES videos.
  find "$OUT" -maxdepth 1 -name '*.mov' -print0 | xargs -0 ls -t 2>/dev/null \
    | tail -n +$((MAX_FILES + 1)) | while read -r old; do rm -f -- "$old"; done
done
