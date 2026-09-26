#!/bin/sh
# Aplica em ordem as migracoes ainda nao registradas em schema_migrations.
set -eu

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-inflow_db}"
DB_USER="${DB_USER:-inflow_user}"
DB_PASSWORD="${DB_PASSWORD:-inflow_pass}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

export PGPASSWORD="$DB_PASSWORD"
PSQL="psql -v ON_ERROR_STOP=1 -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"

echo "[migrate] aguardando PostgreSQL em $DB_HOST:$DB_PORT..."
attempt=1
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
    if [ "$attempt" -ge 30 ]; then
        echo "[migrate] PostgreSQL indisponivel apos 30 tentativas." >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 2
done

$PSQL -q -c "CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);"

applied_count=0
for file in "$MIGRATIONS_DIR"/*.sql; do
    version="$(basename "$file")"
    if [ "$($PSQL -tAc "SELECT 1 FROM schema_migrations WHERE version = '$version';")" = "1" ]; then
        echo "[migrate] ja aplicada: $version"
        continue
    fi
    echo "[migrate] aplicando: $version"
    # -1 envolve o arquivo e o registro da versao na mesma transacao.
    $PSQL -1 -q -f "$file" -c "INSERT INTO schema_migrations (version) VALUES ('$version');"
    applied_count=$((applied_count + 1))
done

echo "[migrate] concluido: $applied_count migracao(oes) aplicada(s)."
