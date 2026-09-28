# Benchmark PostgreSQL × MariaDB

Este teste isola a parcela de banco dos jobs do InFlow. Ele recria os upserts dos jobs
`senators`, `committees`, `sessions`, `expenses` e `staff`, usando por padrão as
cardinalidades observadas no projeto. Chamadas HTTP, parsing e pausas dos coletores não entram
na medição.

## Executar

```bash
make benchmark
```

O comando sobe PostgreSQL 15 e MariaDB 11.4, recria somente o namespace `benchmark`, executa
a carga e grava dois arquivos ignorados pelo Git em `benchmark/results/`: um JSON com os dados
brutos e um Markdown pronto para incorporar à ADR.

Para aumentar o volume em dez vezes:

```bash
docker compose --profile benchmark run --rm db-benchmark --scale 10
```

Para repetir de forma comparável, feche aplicações pesadas, registre CPU/RAM/armazenamento e
execute o teste ao menos cinco vezes. Use a mediana das execuções e não apenas a melhor.

## O que é medido

- carga inicial das tabelas;
- reprocessamento dos mesmos dados por upsert idempotente;
- throughput por job em linhas/s;
- p50 e p95 de três consultas representativas;
- tamanho da tabela `despesas`, incluindo índices.

O resultado não é o tempo ponta a ponta do pipeline. Essa separação é intencional: o pipeline
real inclui latência das APIs do Senado, download e parsing de PDFs e `sleep(0.12)` entre
requisições, fatores idênticos para os dois bancos e muito maiores que várias operações SQL.

## Leitura responsável para a ADR

Além dos números, registre diferenças que afetam a decisão: o projeto hoje usa `JSONB`, `BYTEA`,
`UUID`, schemas, PL/pgSQL, `ON CONFLICT` e `RETURNING`. A migração para MariaDB exige adaptar
DDL e consultas (`ON DUPLICATE KEY UPDATE`, tipos JSON/binário, geração de IDs e triggers). O
benchmark mede desempenho; não elimina esse custo de portabilidade.
