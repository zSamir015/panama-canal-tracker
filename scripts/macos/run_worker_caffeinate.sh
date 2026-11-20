#!/usr/bin/env bash
# Arranca el worker AIS local bajo `caffeinate -i -s` (impide reposo mientras el Mac esté
# conectado a corriente AC, sin encender la pantalla) y con `AIS_CANAL_BOUND_ENABLED=false` (una
# sola conexión, compatible con el recolector continuo de GitHub según ADR-0019).
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

# Lee `.env` sin ejecutarlo como shell (`pydantic-settings` lee solo las claves tipadas en Settings).
"$REPO_DIR/.venv/bin/python" - <<'PY'
import socket
import sys
import time
from urllib.parse import urlsplit

from app.core.config import get_settings

settings = get_settings()
key = settings.aisstream_api_key
key_val = key.get_secret_value().strip() if key is not None else ""
if not key_val or key_val in {"simulator", "changeme"}:
    sys.stderr.write("Error: AISSTREAM_API_KEY en .env debe ser una clave real.\n")
    sys.exit(1)

checks: list[tuple[str, str, int]] = []
for name, url, default_port in (
    ("DATABASE_URL", settings.database_url, 5432),
    ("REDIS_URL", settings.redis_url, 6379),
):
    # En Settings son SecretStr (llevan la contraseña): se leen aquí y nunca se imprimen.
    parsed = urlsplit(url.get_secret_value())
    if parsed.hostname:
        checks.append((name, parsed.hostname, parsed.port or default_port))

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

# -i: evita reposo por inactividad; -s: evita reposo del sistema con alimentación AC.
# Una sola conexión AISStream para poder convivir con `collect-ais.yml` (ADR-0019).
exec /usr/bin/caffeinate -i -s -- env AIS_CANAL_BOUND_ENABLED=false "$REPO_DIR/.venv/bin/python" -m app.workers.ais_consumer
