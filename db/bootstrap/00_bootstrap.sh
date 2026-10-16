#!/bin/sh
# Executado automaticamente pela imagem do Postgres somente na criacao de um volume novo.
set -eu

# Falha cedo se a senha do role da aplicacao nao foi repassada pelo docker compose
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD nao definido}"

# Cria o role optime_app usando o script psql versionado (sem nenhuma senha no repositorio)
psql -v ON_ERROR_STOP=1 \
    -v app_password="$APP_DB_PASSWORD" \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -f /docker-entrypoint-initdb.d/create_app_role.psql
