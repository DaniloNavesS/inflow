#!/usr/bin/env bash
# ADR 0005: planos de execução da consulta otimizada e custo das granularidades.
#
# Mede com EXPLAIN (ANALYZE, BUFFERS) as mesmas perguntas sobre a fato detalhada e as
# agregações mensais publicadas pelo dbt, além do custo de materialização e do efeito
# do volume. Não altera os marts: o cenário "sem índice" desliga o uso de índices só
# na sessão, o índice da agregação mensal é criado numa transação desfeita e as cópias
# por volume são tabelas temporárias.
#
# Requer o PostgreSQL do Compose ativo e os modelos publicados (make models).
# Uso, na raiz do repositório:
#   bash scripts/adr/0005_planos_execucao.sh
#   REPETICOES=11 SAIDA=resultados/adr-0005-b bash scripts/adr/0005_planos_execucao.sh
set -euo pipefail

REPETICOES=${REPETICOES:-7}
SAIDA=${SAIDA:-resultados/adr-0005}
SENADOR=${SENADOR:-581}
ANO=${ANO:-2025}
mkdir -p "$SAIDA/planos"
RESUMO="$SAIDA/resumo.md"

psql_() {
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q -v ON_ERROR_STOP=1 "$@"' psql "$@"
}

M=analytics_marts
SEM_INDICE="SET enable_indexscan = off; SET enable_bitmapscan = off; SET enable_indexonlyscan = off;"

# Q1, seletiva: gasto mensal por categoria de um senador num ano (consulta otimizada).
q1_detalhada() {
  echo "SELECT mes, categoria_id, sum(valor) AS valor_total, count(*) AS quantidade
FROM $1 WHERE senador_id = $SENADOR AND ano = $ANO
GROUP BY mes, categoria_id ORDER BY mes, categoria_id;"
}
Q1_MENSAL="SELECT mes, categoria_id, sum(valor_total) AS valor_total, sum(quantidade_despesas) AS quantidade
FROM $M.agg_despesas_mensais WHERE senador_id = $SENADOR AND ano = $ANO
GROUP BY mes, categoria_id ORDER BY mes, categoria_id;"

# Q2, ampla: média mensal por senador e ano (modelo gestao_media_mensal).
Q2_DETALHADA="WITH mensal AS (SELECT senador_id, ano, mes, sum(valor) AS total
  FROM $M.fct_despesas GROUP BY senador_id, ano, mes)
SELECT senador_id, ano, sum(total) AS valor_total, count(*) AS meses_com_despesas,
       sum(total) / count(*) AS media_mensal
FROM mensal GROUP BY senador_id, ano;"
Q2_CATEGORIA="WITH mensal AS (SELECT senador_id, ano, mes, sum(valor_total) AS total
  FROM $M.agg_despesas_mensais GROUP BY senador_id, ano, mes)
SELECT senador_id, ano, sum(total) AS valor_total, count(*) AS meses_com_despesas,
       sum(total) / count(*) AS media_mensal
FROM mensal GROUP BY senador_id, ano;"
Q2_MENSAL="SELECT senador_id, ano, sum(valor_total) AS valor_total, count(*) AS meses_com_despesas,
       sum(valor_total) / count(*) AS media_mensal
FROM $M.fct_despesas_mensais GROUP BY senador_id, ano;"

# Q3, ampla: total mensal por senador em 2024 (base da pergunta central).
Q3_DETALHADA="SELECT senador_id, mes, sum(valor) AS valor_total, count(*) AS quantidade
FROM $M.fct_despesas WHERE ano = 2024 GROUP BY senador_id, mes;"
Q3_CATEGORIA="SELECT senador_id, mes, sum(valor_total) AS valor_total, sum(quantidade_despesas) AS quantidade
FROM $M.agg_despesas_mensais WHERE ano = 2024 GROUP BY senador_id, mes;"
Q3_MENSAL="SELECT senador_id, mes, valor_total, quantidade_despesas
FROM $M.fct_despesas_mensais WHERE ano = 2024;"

# Executa: preparo, uma leitura de aquecimento e REPETICOES planos. Grava o primeiro plano
# e acrescenta uma linha ao resumo com a mediana, o mínimo, o máximo e os buffers.
medir() {
  local nome=$1 preparo=$2 consulta=$3 final=${4:-}
  local bruto="$SAIDA/planos/$nome.saida"
  {
    echo "$preparo"
    echo '\o /dev/null'
    echo "$consulta"
    echo '\o'
    for _ in $(seq "$REPETICOES"); do echo "EXPLAIN (ANALYZE, BUFFERS) $consulta"; done
    echo "$final"
  } | psql_ > "$bruto"
  local tempos mediana minimo maximo buffers acesso
  tempos=$(grep 'Execution Time' "$bruto" | awk '{print $3}' | sort -n)
  mediana=$(echo "$tempos" | awk '{v[NR]=$1} END {print v[int((NR+1)/2)]}')
  minimo=$(echo "$tempos" | awk 'NR==1')
  maximo=$(echo "$tempos" | awk 'END {print}')
  buffers=$(awk '/QUERY PLAN/{f=1} f && /Buffers:/{sub(/.*Buffers: /,""); print; exit}' "$bruto")
  acesso=$(awk 'match($0, /(Index Only Scan|Index Scan|Bitmap Heap Scan|Seq Scan)/) {
    print substr($0, RSTART, RLENGTH); exit }' "$bruto")
  {
    echo "-- Cenário: $nome ($(date -u +%Y-%m-%dT%H:%M:%SZ), $REPETICOES execuções)"
    echo "-- Tempos (ms): $(echo "$tempos" | tr '\n' ' ')"
    [ -n "$preparo" ] && echo "-- Preparo: $(echo "$preparo" | tr '\n' ' ')"
    echo "$consulta" | sed 's/^/-- /'
    echo
    awk '/QUERY PLAN/{c++} c==1' "$bruto" | sed '/Execution Time/q'
  } > "$SAIDA/planos/$nome.txt"
  rm -f "$bruto"
  printf '| %s | %s | %s | %s | %s–%s |\n' "$nome" "$acesso" "$buffers" "$mediana" "$minimo" "$maximo" | tee -a "$RESUMO"
}

# Igualdade das respostas: a comparação só vale se as granularidades respondem o mesmo.
conferir() {
  local nome=$1 a=$2 b=$3 diferencas
  diferencas=$(echo "SELECT count(*) FROM ((${a%;}) EXCEPT ALL (${b%;})) d;" | psql_ -tA)
  echo "| $nome | $diferencas |" | tee -a "$RESUMO"
  [ "$diferencas" = 0 ] || { echo "Respostas diferentes em $nome" >&2; exit 1; }
}

echo "Estabilizando estatísticas e mapa de visibilidade dos marts medidos..."
for t in fct_despesas agg_despesas_mensais fct_despesas_mensais; do
  echo "VACUUM ANALYZE $M.$t;"
done | psql_

{
  echo "# ADR 0005: resultados de $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "Senador $SENADOR, ano $ANO, $REPETICOES execuções por cenário após uma leitura de aquecimento."
  echo
  echo '## Tabelas'
  echo
  echo '| Tabela | Linhas | Páginas | Tabela | Índices | Bytes por linha |'
  echo '|---|---|---|---|---|---|'
} > "$RESUMO"
psql_ -tA -F ' | ' -c "
SELECT c.relname AS tabela, c.reltuples::bigint AS linhas, c.relpages AS paginas,
       pg_size_pretty(pg_table_size(c.oid)) AS tabela_tamanho,
       pg_size_pretty(pg_indexes_size(c.oid)) AS indices_tamanho,
       round(pg_table_size(c.oid)::numeric / greatest(c.reltuples, 1)) AS bytes_por_linha
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = '$M' AND c.relname IN
  ('fct_despesas', 'agg_despesas_mensais_fornecedor_categoria', 'agg_despesas_mensais', 'fct_despesas_mensais')
ORDER BY c.reltuples DESC;" | sed 's/^/| /; s/$/ |/' | tee -a "$RESUMO"

printf '\n## Respostas idênticas entre granularidades\n\n| Comparação | Linhas diferentes |\n|---|---|\n' | tee -a "$RESUMO"
conferir Q1_detalhada_x_categoria "$(q1_detalhada $M.fct_despesas)" "$Q1_MENSAL"
conferir Q2_detalhada_x_mensal "$Q2_DETALHADA" "$Q2_MENSAL"
conferir Q3_detalhada_x_mensal "$Q3_DETALHADA" "$Q3_MENSAL"

printf '\n## Consultas\n\n| Cenário | Acesso | Buffers | Mediana (ms) | Faixa (ms) |\n|---|---|---|---|---|\n' | tee -a "$RESUMO"
medir Q1_antes_detalhada_sem_indice "$SEM_INDICE" "$(q1_detalhada $M.fct_despesas)"
medir Q1_depois_detalhada_com_indice "" "$(q1_detalhada $M.fct_despesas)"
medir Q1_categoria_sem_indice "" "$Q1_MENSAL"
medir Q1_categoria_com_indice_transitorio \
  "BEGIN; CREATE INDEX ON $M.agg_despesas_mensais (senador_id, ano, mes, categoria_id, valor_total, quantidade_despesas);" \
  "$Q1_MENSAL" "ROLLBACK;"
medir Q2_detalhada "" "$Q2_DETALHADA"
medir Q2_categoria "" "$Q2_CATEGORIA"
medir Q2_mensal "" "$Q2_MENSAL"
medir Q3_detalhada "" "$Q3_DETALHADA"
medir Q3_categoria "" "$Q3_CATEGORIA"
medir Q3_mensal "" "$Q3_MENSAL"

# Pergunta central: as consultas de 001_pergunta_central.sql, lidas do próprio arquivo.
printf '\n## Pergunta central (001_pergunta_central.sql)\n\n| Cenário | Acesso | Buffers | Mediana (ms) | Faixa (ms) |\n|---|---|---|---|---|\n' | tee -a "$RESUMO"
mapfile -t CENTRAL < <(awk 'BEGIN { RS = ";" } { gsub(/--[^\n]*/, ""); gsub(/\n/, " ");
  if ($0 ~ /[A-Za-z]/) print $0 ";" }' scripts/sql/analytics/001_pergunta_central.sql)
for i in "${!CENTRAL[@]}"; do
  medir "PC$((i + 1))_pergunta_central" "" "${CENTRAL[$i]}"
done

printf '\n## Volume: Q1 em cópias com 1, 3 e 6 anos\n\n| Cenário | Acesso | Buffers | Mediana (ms) | Faixa (ms) |\n|---|---|---|---|---|\n' | tee -a "$RESUMO"
for desde in 2025 2023 2020; do
  anos=$((2026 - desde))
  # temp_buffers padrão (8 MB) não comporta as cópias maiores; sem o ajuste a leitura
  # sairia do cache do sistema e não seria comparável aos marts em shared_buffers.
  copia="SET temp_buffers = '64MB';
CREATE TEMP TABLE fct_volume AS SELECT * FROM $M.fct_despesas WHERE ano >= $desde;
CREATE INDEX ON fct_volume (senador_id, ano, mes, categoria_id, valor);
VACUUM ANALYZE fct_volume;"
  medir "V_${anos}anos_sem_indice" "$copia $SEM_INDICE" "$(q1_detalhada fct_volume)"
  medir "V_${anos}anos_com_indice" "$copia" "$(q1_detalhada fct_volume)"
done

# Materialização: os comandos equivalentes ao dbt, em transações desfeitas.
printf '\n## Materialização (3 execuções, transação desfeita)\n\n| Passo | Mediana (ms) | Faixa (ms) |\n|---|---|---|\n' | tee -a "$RESUMO"
{
  for _ in 1 2 3; do cat <<SQL
BEGIN;
\timing on
CREATE TEMP TABLE m_fct AS SELECT d.*, current_timestamp AS materializado_em FROM analytics_intermediate.int_despesas d;
CREATE INDEX ON m_fct (senador_id, ano, mes, categoria_id, valor);
CREATE TEMP TABLE m_agg AS SELECT senador_id, ano, mes, competencia, categoria_id, sum(valor) AS valor_total,
  count(*) AS quantidade_despesas, max(materializado_em) AS materializado_em
  FROM m_fct GROUP BY senador_id, ano, mes, competencia, categoria_id;
CREATE TEMP TABLE m_mensal AS SELECT senador_id, ano, mes, competencia, sum(valor_total) AS valor_total
  FROM m_agg GROUP BY senador_id, ano, mes, competencia;
\timing off
ROLLBACK;
SQL
  done
} | psql_ | awk '/^Time:/{print $2}' > "$SAIDA/materializacao.tmp"
passo=0
for rotulo in "fct_despesas (CREATE TABLE AS)" "índice de fct_despesas" "agg_despesas_mensais" "fct_despesas_mensais (sem o contexto)"; do
  passo=$((passo + 1))
  awk -v p=$passo 'NR % 4 == p % 4' "$SAIDA/materializacao.tmp" | sort -n \
    | awk -v r="$rotulo" '{v[NR]=$1} END {printf "| %s | %s | %s–%s |\n", r, v[2], v[1], v[NR]}' | tee -a "$RESUMO"
done
rm -f "$SAIDA/materializacao.tmp"

echo
echo "Resumo em $RESUMO; planos completos em $SAIDA/planos/."
