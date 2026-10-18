#!/usr/bin/env bash
# Base de datos para los tests de integración: `<POSTGRES_DB>_test`, con los mismos roles,
# permisos y extensiones que la de desarrollo. Los tests migran y desmigran su esquema, así que
# nunca deben tocar la base en la que trabajas.
#
# Se ejecuta solo al crear el volumen. Es idempotente: en un volumen que ya existe, aplícalo con
#   docker compose up -d --wait && scripts/create_test_database.sh
# Necesita los roles de 100_canal_roles.sh.
set -euo pipefail

: "${POSTGRES_DB:?}" "${POSTGRES_USER:?}"
# Durante la inicialización la imagen ya define PGPASSWORD; a mano hay que pasarla.
export PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:?}}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v test_db="${POSTGRES_DB}_test" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER canal_owner', :'test_db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'test_db')
\gexec

REVOKE ALL ON DATABASE :"test_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"test_db" TO canal_app;

\connect :"test_db"
-- Las extensiones las crea el superusuario, igual que en la base de desarrollo.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

-- El esquema `public` de una base nueva pertenece a su dueño (canal_owner).
GRANT USAGE ON SCHEMA public TO canal_app;
ALTER DEFAULT PRIVILEGES FOR ROLE canal_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO canal_app;
ALTER DEFAULT PRIVILEGES FOR ROLE canal_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO canal_app;
SQL
