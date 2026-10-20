#!/usr/bin/env bash
# Comprueba los servicios de `docker compose` (tarea 2.1): roles de la base y contraseña de Redis.
# Uso: docker compose up -d --wait && scripts/check_dev_services.sh
set -euo pipefail

failures=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FALLO %s\n' "$1"; failures=$((failures + 1)); }

# Ejecuta SQL en el contenedor como el rol indicado, por TCP y con contraseña (como lo hará la app).
sql_as() {
  local role=$1 password_var=$2 sql=$3
  docker compose exec -T -e PGOPTIONS='-c client_min_messages=error' db bash -c \
    "PGPASSWORD=\"\$$password_var\" psql -h 127.0.0.1 -U $role -d canal_tracker -v ON_ERROR_STOP=1 -qtA" \
    <<<"$sql" 2>&1
}

expect_ok() {
  local description=$1; shift
  if output=$(sql_as "$@"); then pass "$description"; else fail "$description: $output"; fi
}

expect_denied() {
  local description=$1; shift
  if output=$(sql_as "$@"); then
    fail "$description: se permitió y no debía"
  elif grep -q 'permission denied\|must be owner' <<<"$output"; then
    pass "$description"
  else
    fail "$description: error inesperado: $output"
  fi
}

echo "PostgreSQL"
expect_ok "extensiones postgis y timescaledb instaladas" postgres POSTGRES_PASSWORD \
  "SELECT 1/(count(*) = 2)::int FROM pg_extension WHERE extname IN ('postgis', 'timescaledb');"

for target in "127.0.0.1" "socket"; do
  host_arg=$([ "$target" = socket ] && echo "" || echo "-h $target")
  if docker compose exec -T db bash -c \
    "PGPASSWORD=incorrecta psql $host_arg -U postgres -d canal_tracker -c 'SELECT 1'" \
    >/dev/null 2>&1; then
    fail "contraseña incorrecta rechazada ($target, dentro del contenedor)"
  else
    pass "contraseña incorrecta rechazada ($target, dentro del contenedor)"
  fi
done

# Desde otro contenedor de la red de compose: el camino que usará la API en producción.
network_sql() {
  docker compose --progress quiet run --rm --no-deps -T --entrypoint bash db -c \
    "PGPASSWORD=\"$1\" psql -h db -U canal_app -d canal_tracker -qtAc 'SELECT 1'" 2>&1
}
if [ "$(network_sql '$CANAL_APP_PASSWORD')" = "1" ]; then
  pass "canal_app se conecta por la red de compose"
else
  fail "canal_app se conecta por la red de compose"
fi
if network_sql incorrecta >/dev/null; then
  fail "contraseña incorrecta rechazada por la red de compose"
else
  pass "contraseña incorrecta rechazada por la red de compose"
fi

expect_ok "canal_app se conecta" canal_app CANAL_APP_PASSWORD "SELECT 1;"
# La base de los tests de integración (docker/db/initdb/110_canal_test_database.sh).
if [ "$(docker compose exec -T db bash -c \
  'PGPASSWORD="$CANAL_APP_PASSWORD" psql -h 127.0.0.1 -U canal_app -d canal_tracker_test -qtAc "SELECT 1"' \
  2>&1)" = "1" ]; then
  pass "canal_app se conecta a la base de test"
else
  fail "canal_app se conecta a la base de test (ejecuta scripts/create_test_database.sh)"
fi
expect_denied "canal_app no puede crear tablas" canal_app CANAL_APP_PASSWORD \
  "CREATE TABLE check_app_ddl (id int);"
expect_denied "canal_app no puede crear esquemas" canal_app CANAL_APP_PASSWORD \
  "CREATE SCHEMA check_app_schema;"

expect_ok "canal_owner puede crear tablas (migraciones)" canal_owner CANAL_OWNER_PASSWORD \
  "DROP TABLE IF EXISTS check_roles; CREATE TABLE check_roles (id serial PRIMARY KEY, v text);"
expect_ok "canal_app lee y escribe datos en tablas de canal_owner" canal_app CANAL_APP_PASSWORD \
  "INSERT INTO check_roles (v) VALUES ('x'); UPDATE check_roles SET v = 'y';
   SELECT count(*) FROM check_roles; DELETE FROM check_roles;"
expect_denied "canal_app no puede alterar tablas" canal_app CANAL_APP_PASSWORD \
  "ALTER TABLE check_roles ADD COLUMN extra int;"
expect_denied "canal_app no puede borrar tablas" canal_app CANAL_APP_PASSWORD \
  "DROP TABLE check_roles;"
expect_denied "canal_owner no puede borrar extensiones del superusuario" canal_owner \
  CANAL_OWNER_PASSWORD "DROP EXTENSION postgis;"
expect_ok "canal_owner limpia la tabla de prueba" canal_owner CANAL_OWNER_PASSWORD \
  "DROP TABLE check_roles;"

echo "Redis"
if docker compose exec -T -e REDISCLI_AUTH= redis redis-cli ping 2>&1 | grep -q NOAUTH; then
  pass "sin contraseña responde NOAUTH"
else
  fail "sin contraseña responde NOAUTH"
fi
if [ "$(docker compose exec -T redis redis-cli ping 2>&1)" = "PONG" ]; then
  pass "con contraseña responde PONG"
else
  fail "con contraseña responde PONG"
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures comprobaciones fallaron"
  exit 1
fi
echo "Todo correcto"
