#!/usr/bin/env bash
# Crea (o completa) la base de los tests de integración en un volumen que ya existe, sin borrar
# datos. En un volumen nuevo no hace falta: la crea docker/db/initdb/110_canal_test_database.sh.
# Uso: docker compose up -d --wait && scripts/create_test_database.sh
set -euo pipefail

docker compose exec -T db bash /docker-entrypoint-initdb.d/110_canal_test_database.sh
echo "Base de test lista"
