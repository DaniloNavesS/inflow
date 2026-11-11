#!/usr/bin/env bash
set -euo pipefail
export MODELING_UID="${MODELING_UID:-$(id -u)}"
export MODELING_GID="${MODELING_GID:-$(id -g)}"
cd "$(dirname "$0")/../.."
python3 -m unittest discover -s tests/modeling -p 'test_*.py'
compose=(docker compose -p inflow-modeling-tests -f tests/modeling/compose.yml)
# Perfil `fixture`: limites de volume e distribuição proporcionais à base sintética.
VARS='{"data_referencia_comissoes": "2024-12-31", "perfil_qualidade": "fixture"}'
psql_exec() { "${compose[@]}" exec -T postgres psql -U modeling_test -d modeling_test -v ON_ERROR_STOP=1 "$@"; }
trap '"${compose[@]}" down --volumes --remove-orphans' EXIT
"${compose[@]}" up -d --wait postgres
"${compose[@]}" run --build --rm modeling build --vars "$VARS"
psql_exec < tests/modeling/fixture.sql
"${compose[@]}" run --build --rm modeling build --vars "$VARS"
"${compose[@]}" run --rm modeling build --vars "$VARS"
psql_exec < tests/modeling/assert_initial.sql
psql_exec < tests/modeling/assert_presence.sql
psql_exec < tests/modeling/assert_comparison.sql
psql_exec -c "UPDATE oltp.fornecedores SET razao_social = 'Nome corrigido' WHERE id = 1"
"${compose[@]}" run --rm modeling build --vars "$VARS"
psql_exec < tests/modeling/assert_history.sql

# Qualidade: os testes passaram acima; agora cada um precisa FALHAR diante do defeito
# que promete detectar. Erro de compilação ou de SQL não conta como detecção.
psql_exec < tests/modeling/quality_defects.sql
selecoes=(
  "fct_despesas,test_name:esquema_esperado"           # esquema: valor vira float
  "dim_senador,test_name:esquema_esperado"            # esquema: coluna removida
  "gestao_comissoes_senador,test_name:volume_igual"   # volume: linha perdida entre camadas
  "fct_despesas_mensais,test_name:unicidade_combinada" # unicidade: grão duplicado
  "fct_despesas,test_name:relationships"              # integridade: fato órfão
  "fct_registros_presenca,test_name:regra_linha"      # integridade: regra de contagem
  "fornecedor_versao_atual_unica"                     # histórico: duas versões abertas
  "fornecedor_sem_versao_redundante"                  # histórico: versão sem mudança
  "contexto_status_coerente"                          # histórico: status x dias em exercício
  "fct_despesas,test_name:intervalo_valores"          # distribuição: valor implausível
  "fct_despesas,test_name:proporcao"                  # distribuição: datas inválidas
  "competencias_sem_lacunas"                          # distribuição: mês sem lançamentos
)
for selecao in "${selecoes[@]}"; do
  saida=$("${compose[@]}" run --rm modeling test --vars "$VARS" --select "$selecao" 2>&1 || true)
  if ! grep -Eq '(^|[^A-Z])FAIL [0-9]+' <<<"$saida"; then
    printf '%s\n' "$saida" >&2
    echo "Teste de qualidade não detectou o defeito injetado: $selecao" >&2
    exit 1
  fi
  echo "Defeito detectado: $selecao"
done
"${compose[@]}" run --rm modeling build --vars "$VARS"

psql_exec -c "DELETE FROM oltp.despesas; DELETE FROM oltp.fornecedores"
"${compose[@]}" run --rm modeling build --vars "$VARS"
psql_exec < tests/modeling/assert_deleted.sql
