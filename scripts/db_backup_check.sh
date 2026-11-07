#!/usr/bin/env bash
# Prueba de punta a punta de las copias de seguridad (tarea 7.2, docs/BACKUP.md).
#
#   docker compose up -d --wait && scripts/db_backup_check.sh
#
# 1. crea una base temporal, la migra a `head` y la rellena con datos sintéticos (buques,
#    posiciones viejas en un chunk COMPRIMIDO y recientes, tránsitos, una visita enlazada y los
#    agregados continuos ya refrescados);
# 2. hace una copia cifrada con `scripts/db_backup.sh`;
# 3. la restaura en OTRA base nueva con `scripts/db_restore.sh`;
# 4. compara una huella de cada tabla y agregado (filas y suma MD5 del contenido), los chunks
#    comprimidos, las políticas de TimescaleDB y los permisos de `canal_app`;
# 5. comprueba que se niega a sobrescribir una base existente y que una copia alterada se detecta;
# 6. borra las dos bases y los ficheros temporales (también si algo falla).
#
# No toca `canal_tracker` ni sus datos. Requiere `gpg` y el entorno de `.env`.
set -euo pipefail
cd "$(dirname "$0")/.."

src="canal_bkcheck_src_$$"
dst="canal_bkcheck_dst_$$"
workdir=$(mktemp -d "${TMPDIR:-/tmp}/canal-backup-check.XXXXXX")
BACKUP_PASSPHRASE=$(openssl rand -base64 32)
export BACKUP_PASSPHRASE

su() {
  docker compose exec -T -e PGOPTIONS='-c client_min_messages=warning' db bash -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 -qtA "$@"' _ "$@"
}
cleanup() {
  # `KEEP_DATABASES=1` deja las dos bases para inspeccionarlas (hay que borrarlas a mano luego).
  if [ -n "${KEEP_DATABASES:-}" ]; then echo "Bases conservadas: $src y $dst"; rm -rf "$workdir"; return; fi
  su -d postgres -c "DROP DATABASE IF EXISTS $src WITH (FORCE)" >/dev/null 2>&1 || true
  su -d postgres -c "DROP DATABASE IF EXISTS $dst WITH (FORCE)" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT
failures=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FALLO %s\n' "$1"; failures=$((failures + 1)); }

echo "1. Base de origen"
su -d postgres -c "CREATE DATABASE $src OWNER canal_owner"
# TimescaleDB exige que `CREATE EXTENSION` sea el primer comando de la sesión: va solo y antes.
su -d "$src" -c "CREATE EXTENSION IF NOT EXISTS timescaledb"
su -d "$src" -c "CREATE EXTENSION IF NOT EXISTS postgis"
su -d "$src" -c "GRANT CONNECT ON DATABASE $src TO canal_app" 2>/dev/null || true
# Los permisos por defecto de `canal_app` viven en el esquema: se repiten como en la inicialización.
su -d "$src" -c "GRANT USAGE ON SCHEMA public TO canal_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE canal_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO canal_app"

migrations_url=$(SRC_DB="$src" .venv/bin/python - <<'PY'
import os
from sqlalchemy.engine import make_url
from app.core.config import Settings
url = Settings().migrations_database_url
assert url is not None, "MIGRATIONS_DATABASE_URL no está definida en .env"
print(make_url(url.get_secret_value()).set(database=os.environ["SRC_DB"]).render_as_string(hide_password=False))
PY
)
MIGRATIONS_DATABASE_URL="$migrations_url" .venv/bin/alembic upgrade head >/dev/null 2>&1 &&
  pass "migrada a head" || { fail "no se pudo migrar la base de origen"; exit 1; }

su -d "$src" <<'SQL'
INSERT INTO vessels (mmsi, name, ship_type) VALUES
  (352000001, 'PACIFIC STAR', 70), (352000002, 'ATLANTIC DAWN', 80), (352000003, 'HARBOR TUG', 52);
-- 120 posiciones de hace 30 días (irán a un chunk comprimido) y 30 de las últimas horas.
INSERT INTO positions (received_at, vessel_mmsi, geom, sog, cog, heading, nav_status)
SELECT now() - interval '30 days' + g * interval '7 minutes', 352000001 + (g % 3),
       ST_SetSRID(ST_MakePoint(-79.9 + g * 0.0001, 9.3), 4326)::geography, (g % 10)::real, 180, 180, 0
FROM generate_series(1, 120) g;
INSERT INTO positions (received_at, vessel_mmsi, geom, sog, cog, heading, nav_status)
SELECT now() - g * interval '5 minutes', 352000001 + (g % 3),
       ST_SetSRID(ST_MakePoint(-79.7, 9.1 + g * 0.0001), 4326)::geography, 5, 90, 90, 0
FROM generate_series(1, 30) g;
INSERT INTO transits (id, vessel_mmsi, direction, status, entered_at, exited_at) VALUES
  ('00000000-0000-4000-8000-000000000001', 352000001, 'southbound', 'completed',
   now() - interval '10 hours', now() - interval '3 hours'),
  ('00000000-0000-4000-8000-000000000002', 352000002, 'northbound', 'in_progress',
   now() - interval '2 hours', NULL);
INSERT INTO anchorage_visits (id, vessel_mmsi, anchorage, arrived_at, departed_at, transit_id) VALUES
  ('00000000-0000-4000-8000-0000000000a1', 352000001, 'atlantic',
   now() - interval '20 hours', now() - interval '10 hours 5 minutes',
   '00000000-0000-4000-8000-000000000001');
SQL
# Compresión y refrescos fuera del bloque anterior: el trabajo de la política recién creada puede
# estar refrescando o comprimiendo justo ahora ("concurrent refresh"), así que se reintentan.
retry() {
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    su "$@" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
retry -d "$src" -c "SELECT count(compress_chunk(c, if_not_compressed => true)) FROM show_chunks('positions', older_than => interval '7 days') c"
retry -d "$src" -c "CALL refresh_continuous_aggregate('positions_hourly', NULL, NULL)"
retry -d "$src" -c "CALL refresh_continuous_aggregate('positions_5min', NULL, NULL)"
pass "datos sintéticos, chunk comprimido y agregados refrescados"

fingerprint() {
  su -d "$1" <<'SQL'
SELECT 'vessels', count(*), md5(string_agg(t::text, '|' ORDER BY mmsi)) FROM vessels t
UNION ALL SELECT 'positions', count(*), md5(string_agg(t::text, '|' ORDER BY received_at, vessel_mmsi)) FROM positions t
UNION ALL SELECT 'transits', count(*), md5(string_agg(t::text, '|' ORDER BY id)) FROM transits t
UNION ALL SELECT 'anchorage_visits', count(*), md5(string_agg(t::text, '|' ORDER BY id)) FROM anchorage_visits t
UNION ALL SELECT 'positions_hourly', count(*), md5(string_agg(t::text, '|' ORDER BY bucket, vessel_mmsi)) FROM positions_hourly t
UNION ALL SELECT 'positions_5min', count(*), md5(string_agg(t::text, '|' ORDER BY bucket, vessel_mmsi)) FROM positions_5min t
UNION ALL SELECT 'alembic_version', count(*), max(version_num) FROM alembic_version
UNION ALL SELECT 'compressed_chunks', count(*), '' FROM timescaledb_information.chunks WHERE hypertable_name = 'positions' AND is_compressed
UNION ALL SELECT 'policy_jobs', count(*), string_agg(proc_name || ':' || hypertable_name, ',' ORDER BY proc_name, hypertable_name) FROM timescaledb_information.jobs WHERE hypertable_name IS NOT NULL
UNION ALL SELECT 'canal_app_can_read', count(*), '' FROM information_schema.tables WHERE table_schema = 'public' AND has_table_privilege('canal_app', quote_ident(table_name), 'SELECT') AND table_name IN ('vessels', 'positions', 'transits', 'anchorage_visits')
ORDER BY 1;
SQL
}

echo "2. Copia cifrada"
backup=$(DB_NAME="$src" scripts/db_backup.sh "$workdir" 2>&1 | tail -1) && [ -f "$backup" ] && pass "copia creada ($(wc -c <"$backup" | tr -d ' ') bytes)" || { fail "no se pudo hacer la copia: $backup"; exit 1; }
if grep -aq 'PGDMP' "$backup"; then fail "la copia lleva el volcado en claro"; else pass "no contiene el volcado en claro"; fi

echo "3. Restauración"
scripts/db_restore.sh "$backup" "$dst" >/dev/null 2>&1 && pass "restaurada en una base nueva" || { fail "falló la restauración"; exit 1; }

echo "4. Comparación"
expected=$(fingerprint "$src")
actual=$(fingerprint "$dst")
if [ "$expected" = "$actual" ]; then
  pass "filas, contenido, agregados, chunks comprimidos, políticas y permisos coinciden"
  echo "$expected" | sed 's/^/        /'
else
  fail "la base restaurada no coincide con el origen"
  diff <(echo "$expected") <(echo "$actual") | sed 's/^/        /' || true
fi

# La prueba no vale nada si no puede fallar: se altera un dato de la base restaurada y la huella
# tiene que cambiar.
su -d "$dst" -c "UPDATE vessels SET name = 'ALTERADO' WHERE mmsi = 352000001"
if [ "$(fingerprint "$dst")" != "$expected" ]; then
  pass "la comparación detecta un dato alterado"
else
  fail "la comparación no detecta un dato alterado: la prueba no sirve"
fi

echo "5. Salvaguardas"
if scripts/db_restore.sh "$backup" "$dst" >/dev/null 2>&1; then
  fail "sobrescribió una base existente"
else
  pass "se niega a restaurar sobre una base que ya existe"
fi
cp "$backup" "$workdir/alterada.dump.gpg"
cp "$backup.sha256" "$workdir/alterada.dump.gpg.sha256" 2>/dev/null || true
sed -i.bak 's/canal-[^ ]*\.dump\.gpg/alterada.dump.gpg/' "$workdir/alterada.dump.gpg.sha256"
printf 'x' | dd of="$workdir/alterada.dump.gpg" bs=1 seek=200 conv=notrunc 2>/dev/null
if scripts/db_restore.sh "$workdir/alterada.dump.gpg" "${dst}_x" >/dev/null 2>&1; then
  fail "restauró una copia alterada"
else
  pass "una copia alterada se rechaza"
fi
# Sin fichero de suma, la integridad la comprueba el propio gpg (cifrado autenticado).
cp "$workdir/alterada.dump.gpg" "$workdir/sin-suma.dump.gpg"
if scripts/db_restore.sh "$workdir/sin-suma.dump.gpg" "${dst}_z" >/dev/null 2>&1; then
  fail "restauró una copia alterada sin fichero de suma"
else
  pass "una copia alterada se rechaza también sin fichero de suma"
fi
if BACKUP_PASSPHRASE="otra contraseña distinta de la buena" scripts/db_restore.sh "$backup" "${dst}_y" >/dev/null 2>&1; then
  fail "restauró con una contraseña equivocada"
else
  pass "una contraseña equivocada no restaura nada"
fi
for leftover in "${dst}_x" "${dst}_y" "${dst}_z"; do
  [ "$(su -d postgres -c "SELECT count(*) FROM pg_database WHERE datname = '$leftover'")" = 0 ] ||
    fail "quedó la base a medias $leftover"
done

echo
[ "$failures" -eq 0 ] && echo "Todo correcto: la copia se restaura y los datos coinciden." || { echo "$failures comprobaciones fallaron"; exit 1; }
