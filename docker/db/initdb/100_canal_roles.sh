#!/usr/bin/env bash
# Roles de la base de datos (AGENTS.md §8.16). Solo se ejecuta al crear el volumen por primera vez;
# para aplicar cambios: `docker compose down -v` (borra los datos locales) y `docker compose up -d`.
#
# - canal_owner: dueño de la base y del esquema `public`; ejecuta las migraciones (DDL).
# - canal_app:   el rol de la API. Lee y escribe datos en las tablas de canal_owner, sin DDL.
# Las extensiones las crea el superusuario y siguen siendo suyas: canal_owner no puede borrarlas.
set -euo pipefail

: "${CANAL_OWNER_PASSWORD:?}" "${CANAL_APP_PASSWORD:?}"

# Las contraseñas viajan como variables de psql (:'var' las escapa), nunca concatenadas en el SQL.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" \
  -v owner_password="$CANAL_OWNER_PASSWORD" \
  -v app_password="$CANAL_APP_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE ROLE canal_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  PASSWORD :'owner_password';
CREATE ROLE canal_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  PASSWORD :'app_password';

-- En PostgreSQL 15+ el esquema `public` pertenece a pg_database_owner: al pasar la base a
-- canal_owner, el esquema también es suyo. PUBLIC ya no puede crear objetos en él.
ALTER DATABASE :"db" OWNER TO canal_owner;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO canal_app;
GRANT USAGE ON SCHEMA public TO canal_app;

-- Lo que canal_owner cree a partir de ahora (las tablas de las migraciones) será accesible
-- para canal_app solo con permisos de datos.
ALTER DEFAULT PRIVILEGES FOR ROLE canal_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO canal_app;
ALTER DEFAULT PRIVILEGES FOR ROLE canal_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO canal_app;
SQL
