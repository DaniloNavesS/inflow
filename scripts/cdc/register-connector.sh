#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

CONNECTOR=inflow-despesas-connector
API=http://localhost:8083/connectors
TIMEOUT_SECONDS=120

connect_api() {
  docker compose exec -T kafka-connect curl "$@"
}

echo "Aguardando Kafka Connect ficar disponível..."
until connect_api -sf "${API}" >/dev/null; do
  sleep 2
done

echo "Registrando (ou atualizando) o conector ${CONNECTOR}..."
connect_api -sf -X PUT \
  -H "Content-Type:application/json" \
  "${API}/${CONNECTOR}/config" \
  -d @- < scripts/cdc/despesas-connector.json >/dev/null

echo "Aguardando conector e task ficarem RUNNING..."
deadline=$((SECONDS + TIMEOUT_SECONDS))
while true; do
  state=$(connect_api -sf "${API}/${CONNECTOR}/status" 2>/dev/null | python3 -c '
import json, sys
s = json.load(sys.stdin)
states = [s["connector"]["state"]] + [t["state"] for t in s["tasks"]]
if "FAILED" in states:
    print("failed")
elif s["tasks"] and all(st == "RUNNING" for st in states):
    print("ok")
else:
    print("wait")
' || echo wait)

  case "${state}" in
    ok)
      echo "Conector ${CONNECTOR} RUNNING."
      exit 0
      ;;
    failed)
      echo "Conector ${CONNECTOR} falhou:" >&2
      connect_api -s "${API}/${CONNECTOR}/status" >&2
      exit 1
      ;;
  esac

  if (( SECONDS >= deadline )); then
    echo "Tempo esgotado esperando o conector ${CONNECTOR} ficar RUNNING." >&2
    exit 1
  fi
  sleep 2
done
