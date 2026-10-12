# 0002 — Adotamos CDC via Debezium sobre recarga periódica, com Iceberg/Delta como opção nula nesta etapa

- **Status:** aceita
- **Data:** 2026-10-12
- **Decisores:** Squad InFlow

## Contexto

A limitação que esta entrega resolve é conhecida desde a modelagem da E1: `atualizado_em`
marca que o ingestor passou pela linha, não que a origem mudou algo de fato. O upsert de
`oltp.despesas` era incondicional: toda carga completa reescrevia as 21.430 linhas, mesmo
quando nenhum valor havia mudado. Já havia um gatilho de revisão definido (migrar para
insert-only quando mais de 1% das linhas de `despesas` mudarem de valor entre cargas), que
depende de conseguir distinguir "mudou" de "não mudou" de forma confiável.

Como pré-requisito desta etapa, o upsert de `despesas` e `fornecedores` passou a ser
condicional (`WHERE ... IS DISTINCT FROM ...`). Validado em ambiente real: uma carga completa
inicial (21.430 despesas, 3.516 fornecedores) seguida de uma segunda carga sem nenhuma mudança
na fonte não tocou nenhuma das 21.430 + 3.516 linhas; antes, a segunda carga reescreveria
todas. Isso elimina o ruído de evento que um CDC baseado nesse upsert geraria.

## Alternativas consideradas

**A. Opção nula: manter apenas a recarga periódica completa diária.**
É o que a E1 já entrega: upsert idempotente, sem nenhuma captura de mudanças. Descartada porque
não atende ao requisito de "fluxo de mudanças a partir do OLTP" da E2, e porque mesmo com o
upsert condicional ainda não há trilha de quando ou quantas vezes uma linha mudou ao longo do
dia; só sabemos que ela é diferente na próxima carga.

**B. Recarga incremental via filtro de ano/mês na API do CEAPS.**
Reduziria o volume reprocessado, mas continua sendo *pull-based*: a aplicação precisaria
adivinhar quando reprocessar, há atraso entre a correção na origem e sua detecção, e a CEAPS
corrige lançamentos de anos anteriores sem aviso. Não existe endpoint de "o que mudou desde
X" na fonte.

**C. CDC via Debezium + Kafka Connect sobre logical decoding do Postgres (escolhida).**
Captura toda alteração (`INSERT`/`UPDATE`/`DELETE`) direto do WAL via `pgoutput` (plugin
nativo do Postgres 15, sem exigir `wal2json`), de forma assíncrona e sem acoplar o pipeline de
ingestão existente a nada além do upsert condicional já feito.

Segunda decisão exigida pelo checklist, **Iceberg vs. Delta: opção nula nesta etapa.** Ainda
não existe nenhum consumidor do tópico Kafka que materialize os eventos em armazenamento
colunar, de modo que decidir entre Iceberg e Delta sem ter o que alimentá-los seria prematuro.
Essa escolha fica para a próxima etapa da E2, quando o consumidor Bronze/Silver for construído.

## Medição

Ambiente reproduzível:
```bash
docker compose down -v
docker compose up --build -d
make migrate-cdc
make cdc-up
make cdc-register
make cdc-status
```

- **`wal_level`:** confirmado `logical` via `SHOW wal_level;` (era `replica` por padrão).
- **Publication:** `inflow_despesas_pub` criada para `oltp.despesas`; `REPLICA IDENTITY FULL`
  confirmado via `relreplident = 'f'` em `pg_class`.
- **Conector:** `inflow-despesas-connector` (Debezium `io.debezium.connector.postgresql.PostgresConnector`,
  imagens oficiais `debezium/zookeeper:2.7.3.Final`, `debezium/kafka:2.7.3.Final`,
  `debezium/connect:2.7.3.Final`), status `"state": "RUNNING"` para o connector e para a task.
- **Serialização de decimais:** por padrão o Debezium serializa colunas `NUMERIC` como bytes
  (ex. `"Byvw"`, ilegível); foi preciso `decimal.handling.mode: "string"` na config do conector
  para o campo `valor` chegar legível no payload (`"9999.99"`, `"1234.56"`).
- **Propagação ponta a ponta (manual):** `UPDATE oltp.despesas SET valor = 1234.56 WHERE id =
  2218170` gerou um evento no tópico `inflow.oltp.despesas` com `payload.op = "u"`,
  `payload.before.valor = "9999.99"` e `payload.after.valor = "1234.56"`.
- **Propagação ponta a ponta (automatizada):** `tests/test_cdc_integration.py`, rodado via
  `make cdc-test`, altera uma despesa, consome o tópico (timeout de 30 s) e confirma o evento:
  `1 passed in 1.75s`. Guardado por `CDC_INTEGRATION_TEST=1`, não roda no `make test` padrão
  (confirmado: aparece como `skipped` quando a variável não está setada).
- **Upsert condicional (pré-requisito):** carga completa (21.430 despesas, 3.516 fornecedores)
  seguida de uma segunda carga idêntica não tocou nenhuma das linhas (antes: 100% delas eram
  reescritas a cada carga).

## Decisão

**Adotamos Debezium + Kafka Connect completo (Zookeeper, Kafka, Kafka Connect) capturando
mudanças de `oltp.despesas` via logical decoding (`pgoutput`), com publication dedicada e
upsert condicional como pré-requisito.**
- `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10` no serviço `postgres`.
- `PUBLICATION inflow_despesas_pub FOR TABLE oltp.despesas` + `REPLICA IDENTITY FULL`.
- Conector reaproveita o usuário `inflow_user` (já superuser da imagem, com `REPLICATION`
  implícito), sem role dedicada, por simplicidade dado o escopo acadêmico.
- Tópico resultante: `inflow.oltp.despesas`.

## Consequências

**Ganhos.** Trilha de eventos assíncrona e granular de cada mudança real em `despesas`, sem
acoplar o Kafka ao pipeline de ingestão (roda em paralelo, não bloqueia `make ingestion`).
Reaproveita a infraestrutura padrão do ecossistema Debezium em vez de código customizado de
polling ou comparação de snapshots.

**Limitação conhecida.** Ainda não há um consumidor que persista esses eventos numa camada
analítica (Bronze/Silver em Parquet/Iceberg/Delta): esta etapa cobre só a captura, não o
consumo. O replication slot do Postgres acumula WAL indefinidamente se o conector cair e não
for monitorado.

**Perdas.** Nenhuma estrutural: é aditivo, não substitui nada da E1.

**Irreversibilidade.** Baixa. `DROP PUBLICATION`/`pg_drop_replication_slot` revertem a
configuração do Postgres; desligar os serviços Kafka não afeta o pipeline de ingestão, que
continua funcionando de forma independente.

## Gatilho de revisão

Reafirmamos o gatilho já definido para a modelagem da origem (migrar para insert-only quando
mais de 1% das linhas de `despesas` mudarem de valor entre cargas) como sinal de que capturar
mudanças continua sendo necessário. Migramos de Debezium/Kafka Connect para uma captura mais
simples (ex. logical decoding direto via `psycopg2`, sem Kafka) quando:
- o overhead operacional de manter Zookeeper + Kafka + Connect não se justificar pelo volume
  real de eventos (hoje, só mudanças genuínas em `despesas`, tipicamente baixo por dia);
- for preciso semântica *exactly-once* ponta a ponta. Esta etapa entrega *at-least-once*
  (Kafka Connect pode reentregar em caso de falha antes do commit de offset), que fica fora de
  escopo aqui.
