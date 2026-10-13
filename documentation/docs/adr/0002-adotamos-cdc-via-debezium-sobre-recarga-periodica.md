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

Como pré-requisito desta etapa, os upserts de `despesas` e `fornecedores` passaram a ser
condicionais (`WHERE ... IS DISTINCT FROM ...`). Em `despesas`, a comparação cobre todas as
colunas vindas da origem (senador, fornecedor, data, ano, mês, valor, tipo, documento e
detalhamento), para que uma correção de data ou de fornecedor também seja capturada. Em
`fornecedores`, todos os fornecedores da carga passam pelo upsert, não só os novos, para que
uma correção de razão social chegue ao banco. Uma linha só é reescrita, e só gera evento de
CDC, quando algum desses valores muda de fato.

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
make ingestion
make cdc-register
make cdc-status
make cdc-test
```

- **`wal_level`:** confirmado `logical` via `SHOW wal_level;` (era `replica` por padrão).
- **Publication:** `inflow_despesas_pub` criada para `oltp.despesas`; `REPLICA IDENTITY FULL`
  confirmado via `relreplident = 'f'` em `pg_class`.
- **Conector:** `inflow-despesas-connector` (Debezium `io.debezium.connector.postgresql.PostgresConnector`,
  imagens oficiais `debezium/zookeeper:2.7.3.Final`, `debezium/kafka:2.7.3.Final`,
  `debezium/connect:2.7.3.Final`), status `"state": "RUNNING"` para o connector e para a task.
  O registro usa `PUT /connectors/inflow-despesas-connector/config`: reexecutar
  `make cdc-register` aplica a configuração atual em vez de falhar com conflito.
- **Credenciais:** o conector lê usuário, senha e banco das mesmas variáveis do `.env` que o
  Postgres usa (`EnvVarConfigProvider`). Com `POSTGRES_PASSWORD` diferente do padrão, o
  conector ficou `RUNNING`, e a configuração gravada no Connect guarda só `${env:...}`.
- **Serialização de decimais:** por padrão o Debezium serializa colunas `NUMERIC` como bytes
  (ex. `"Byvw"`, ilegível); foi preciso `decimal.handling.mode: "string"` na config do conector
  para o campo `valor` chegar legível no payload (`"9999.99"`, `"1234.56"`).
- **Snapshot inicial:** 21.430 mensagens no tópico `inflow.oltp.despesas`, uma por despesa.
- **Recarga sem mudança na origem, com CDC ligado:** a segunda carga completa não tocou nenhuma
  das 21.430 despesas nem dos 3.516 fornecedores e não gerou nenhum evento (o tópico seguiu com
  21.430 mensagens). Antes do upsert condicional, cada carga reescrevia todas as linhas.
- **Propagação ponta a ponta (manual):** `UPDATE oltp.despesas SET valor = 1234.56 WHERE id =
  2218170` gerou um evento com `payload.op = "u"`, `payload.before.valor = "9999.99"` e
  `payload.after.valor = "1234.56"`.
- **Propagação ponta a ponta (automatizada):** `tests/test_cdc_integration.py`, rodado via
  `make cdc-test`: `1 passed in 0.99s`. O teste espera o replication slot ficar ativo e o tópico
  existir, se posiciona no fim do tópico, altera uma despesa, confirma o evento de `UPDATE` com
  o novo valor e restaura o valor original. Guardado por `CDC_INTEGRATION_TEST=1`, não roda no
  `make test` padrão.
- **Replay do consumidor (13/10/2026):** o mesmo teste agora volta ao offset do evento,
  relê o payload e comprova duplicação em um destino append-only e convergência em uma
  projeção por `despesas.id` (`1 passed in 1.10s`). A demonstração e seus limites estão em
  [Replay e semântica de entrega](../semantica-entrega-cdc.md).
- **Reinício do ambiente:** depois de `docker compose down` (sem `-v`) e `make cdc-register`, o
  tópico seguiu com 21.430 mensagens: os offsets persistidos no volume do Kafka evitam um novo
  snapshot.

## Decisão

**Adotamos Debezium + Kafka Connect completo (Zookeeper, Kafka, Kafka Connect) capturando
mudanças de `oltp.despesas` via logical decoding (`pgoutput`), com publication dedicada e
upsert condicional como pré-requisito.**
- `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10` e
  `max_slot_wal_keep_size=1GB` no serviço `postgres`.
- `PUBLICATION inflow_despesas_pub FOR TABLE oltp.despesas` + `REPLICA IDENTITY FULL`.
- Conector reaproveita o usuário do Postgres (já superuser da imagem, com `REPLICATION`
  implícito), sem role dedicada, por simplicidade dado o escopo acadêmico.
- Dados do Kafka e do Zookeeper em volumes nomeados, para preservar tópicos e offsets.
- Tópico resultante: `inflow.oltp.despesas`.

## Consequências

**Ganhos.** Trilha de eventos assíncrona e granular de cada mudança real em `despesas`, sem
acoplar o Kafka ao pipeline de ingestão (roda em paralelo, não bloqueia `make ingestion`).
Reaproveita a infraestrutura padrão do ecossistema Debezium em vez de código customizado de
polling ou comparação de snapshots.

**Limitação conhecida.** Ainda não há um consumidor que persista esses eventos numa camada
analítica (Bronze/Silver em Parquet/Iceberg/Delta): esta etapa cobre só a captura, não o
consumo. Com o conector parado, o replication slot retém WAL até o limite de 1 GB; passado
esse limite, o Postgres invalida o slot, e o conector precisa ser registrado de novo, com um
novo snapshot. `REPLICA IDENTITY FULL` também aumenta o WAL escrito por mudança em `despesas`.

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
