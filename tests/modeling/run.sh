#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
compose=(docker compose -p inflow-modeling-tests -f tests/modeling/compose.yml)
trap '"${compose[@]}" down --volumes --remove-orphans' EXIT
"${compose[@]}" up -d --wait postgres
"${compose[@]}" run --build --rm modeling build
"${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 < tests/modeling/fixture.sql
"${compose[@]}" run --build --rm modeling build
"${compose[@]}" run --rm modeling build
"${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 < tests/modeling/assert_initial.sql
"${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 -c "UPDATE oltp.fornecedores SET razao_social = 'Nome corrigido' WHERE id = 1"
"${compose[@]}" run --rm modeling build
"${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 < tests/modeling/assert_history.sql
"${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 -c "DELETE FROM oltp.despesas; DELETE FROM oltp.fornecedores"
"${compose[@]}" run --rm modeling build
"${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 < tests/modeling/assert_deleted.sql
