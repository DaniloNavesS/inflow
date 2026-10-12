#!/usr/bin/env bash
set -euo pipefail

CONNECT_URL="${KAFKA_CONNECT_URL:-http://localhost:${KAFKA_CONNECT_PORT:-8083}}"
CONFIG_FILE="$(dirname "$0")/despesas-connector.json"

echo "Aguardando Kafka Connect ficar disponível em ${CONNECT_URL}..."
until curl -sf "${CONNECT_URL}/connectors" >/dev/null; do
  sleep 2
done

echo "Registrando conector inflow-despesas-connector..."
curl -i -X POST \
  -H "Accept:application/json" \
  -H "Content-Type:application/json" \
  "${CONNECT_URL}/connectors/" \
  -d @"${CONFIG_FILE}"
echo
