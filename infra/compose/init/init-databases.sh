#!/usr/bin/env bash
# Runs once on first postgres init: extra databases + platform roles.
# The runtime role (dw_app) is deliberately NOT a superuser and has no
# BYPASSRLS — RLS must apply to application queries (blueprint §15.3).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE dw_migrator LOGIN PASSWORD '${DW_DB_MIGRATOR_PASSWORD}' NOSUPERUSER NOBYPASSRLS CREATEDB;
    CREATE ROLE dw_app LOGIN PASSWORD '${DW_DB_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;

    CREATE DATABASE dw OWNER dw_migrator;
    CREATE DATABASE keycloak OWNER "$POSTGRES_USER";
    CREATE DATABASE langfuse OWNER "$POSTGRES_USER";

    GRANT CONNECT ON DATABASE dw TO dw_app;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname dw <<-EOSQL
    GRANT USAGE ON SCHEMA public TO dw_app;
EOSQL
