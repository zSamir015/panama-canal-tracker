#!/usr/bin/env bash
# Arranca el worker AIS local bajo `caffeinate -i -s` (impide reposo mientras el Mac esté
# conectado a corriente AC, sin encender la pantalla). Diseñado para ejecutarse vía `launchd`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_DIR"

if [[ ! -f "$REPO_DIR/.env" ]]; then
  echo "Error: falta $REPO_DIR/.env (copia .env.example y añade tu AISSTREAM_API_KEY)." >&2
  exit 1
fi

if [[ ! -x "$REPO_DIR/.venv/bin/python" ]]; then
  echo "Error: falta el entorno virtual $REPO_DIR/.venv/bin/python." >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$REPO_DIR/.env"
set +a

key_val="${AISSTREAM_API_KEY:-}"
if [[ -z "$key_val" || "$key_val" == "simulator" || "$key_val" == "changeme" ]]; then
  echo "Error: AISSTREAM_API_KEY en .env debe ser una clave real (no vacía ni 'simulator')." >&2
  exit 1
fi
unset key_val

# Tras un reinicio del Mac, Docker Desktop puede tardar unos segundos en abrir los puertos.
"$REPO_DIR/.venv/bin/python" - <<'PY'
import os
import socket
import sys
import time
from urllib.parse import urlsplit

def targets():
    out = []
    for env_key, default_port in (("DATABASE_URL", 5432), ("REDIS_URL", 6379)):
        raw = os.environ.get(env_key, "").strip()
        if not raw:
            continue
        parsed = urlsplit(raw)
        if parsed.hostname:
            out.append((env_key, parsed.hostname, parsed.port or default_port))
    return out

checks = targets()
deadline = time.monotonic() + 90.0
while time.monotonic() < deadline:
    pending = []
    for name, host, port in checks:
        try:
            with socket.create_connection((host, port), timeout=2):
                pass
        except OSError:
            pending.append(f"{name} ({host}:{port})")
    if not pending:
        sys.exit(0)
    time.sleep(3)

sys.stderr.write("Servicios dependientes no listos tras 90 s: " + ", ".join(pending) + "\n")
sys.exit(1)
PY

# -i: evita reposo por inactividad; -s: evita reposo del sistema mientras haya alimentación AC.
exec /usr/bin/caffeinate -i -s -- "$REPO_DIR/.venv/bin/python" -m app.workers.ais_consumer
