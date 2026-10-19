# 0002 — Adotamos CDC via Debezium sobre recarga periódica e Delta Lake (delta-rs) como formato de tabela

- **Status:** aceita para a captura de mudanças; proposta para o formato de tabela, até a
  revisão de quem implementa a camada analítica
- **Data:** 2026-10-12
- **Decisores:** Squad InFlow

## Contexto

A E2 pede duas decisões: como as mudanças saem do OLTP e em que formato elas ficam na camada
analítica. O ponto de partida das duas é a mesma advertência: "INSERT...SELECT agendado
resolve muitos domínios". Antes de adotar um componente novo, é preciso mostrar o que ele
entrega que uma cópia agendada não entrega.

Pela carga medida em [Caracterização da carga](../metrics/workload.md), este domínio é um dos
que a cópia agendada resolve:

- a origem publica o CEAPS mensalmente e o frescor tolerado é de 1 mês;
- a carga completa grava cerca de 34 mil linhas em 90,6 s, contra 10 min tolerados;
- há um único escritor em lote e poucos leitores analíticos;
- `despesas` tem 21.430 linhas por ano, e a agregação mais pesada leva 12,0 ms.

A origem também não oferece um fluxo de mudanças: o Postgres só muda quando o lote diário
roda. Capturar o WAL, portanto, **não deixa o dado mais fresco**. O que a cópia agendada não
entrega é outra coisa: o registro de **o que mudou**. O upsert sobrescreve a linha, e a
[caracterização da carga](../metrics/workload.md#sazonalidade) aponta o fim de exercício como
o momento em que correções retroativas mais destroem informação. É esse histórico de
correções, e não latência, que as duas decisões abaixo precisam preservar.

Um pré-requisito já foi entregue. `atualizado_em` marcava que o ingestor passou pela linha, não
que a origem mudou algo: o upsert de `oltp.despesas` reescrevia as 21.430 linhas a cada carga.
Os upserts de `despesas` e `fornecedores` passaram a ser condicionais
(`WHERE ... IS DISTINCT FROM ...`), comparando todas as colunas vindas da origem. Uma linha
só é reescrita, e só gera evento, quando algum valor muda de fato.

## Alternativas consideradas

### Decisão 1: como as mudanças saem do OLTP

**A. Opção nula: só a recarga periódica completa.**
É o `INSERT...SELECT` agendado, e é o que a E1 já entrega: upsert idempotente, diário, sem
nenhum componente além do Postgres. Atende frescor, volume e latência com folga. Não atende
ao requisito de fluxo de mudanças a partir do OLTP da E2 e não guarda o valor anterior de uma
linha corrigida: depois da carga, só se sabe que a linha é diferente.

**B. Recarga incremental via filtro de ano/mês na API do CEAPS.**
Reduziria o volume reprocessado, mas continua sendo *pull-based* e sem histórico. A aplicação
precisaria adivinhar quando reprocessar, e a CEAPS corrige lançamentos de anos anteriores sem
aviso. Não existe endpoint de "o que mudou desde X" na fonte.

**C. CDC via Debezium + Kafka Connect sobre logical decoding do Postgres (escolhida).**
Captura toda alteração (`INSERT`/`UPDATE`/`DELETE`) direto do WAL via `pgoutput`, plugin
nativo do Postgres 15. Cada evento traz a imagem anterior e a posterior da linha, de forma
assíncrona e sem acoplar o ingestor a nada além do upsert condicional. Custa três contêineres
a mais (Zookeeper, Kafka, Kafka Connect) e um replication slot para vigiar.

### Decisão 2: formato da tabela na camada analítica

**D. Opção nula: Parquet puro, reescrito a cada carga.**
Um arquivo por tabela, gerado por `COPY ... TO` ou PyArrow; é o `INSERT...SELECT` agendado da
camada analítica. É o mais simples e o mais rápido de ler. Não tem commit atômico nem versão
anterior: aplicar uma correção é reescrever o arquivo, e o valor antigo se perde, que é
justamente o que a decisão 1 se propôs a preservar.

**E. Apache Iceberg via PyIceberg.**
Especificação neutra entre motores, com particionamento oculto e evolução de partição. Exige
um catálogo mesmo para uma tabela local (SQLite ou o próprio Postgres), ou seja, mais um
componente com estado.

**F. Delta Lake via delta-rs (escolhida).**
A tabela é um diretório com os arquivos Parquet e o log de transações em `_delta_log`; não há
catálogo nem serviço. Tem `MERGE` para aplicar eventos de CDC pela chave e leitura de versões
anteriores.

## Medição

### Captura de mudanças

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

### Formato de tabela

`scripts/adr/0002_formatos_tabela.py` lê `oltp.despesas`, grava nos três formatos com
compressão zstd, aplica um lote de CDC simulado (1 despesa corrigida e 1 nova) e consulta pelo
DuckDB a agregação senador x tipo de despesa:

```bash
docker compose run --rm -v "$PWD/scripts:/scripts:ro" ingestion sh -c 'pip install -q pyarrow deltalake "pyiceberg[sql-sqlite]" duckdb && python /scripts/adr/0002_formatos_tabela.py --ano 2024'
```

Resultado para as 21.430 despesas de 2024, com PyArrow 26.0.0, deltalake 1.6.6, PyIceberg
0.12.0 e DuckDB 1.5.6. Três execuções variaram no máximo 15 ms entre si.

| Formato | Escrita inicial | Arquivos e tamanho | Lote de CDC | Arquivos e tamanho após o lote | Consulta no DuckDB | Versão anterior legível |
|---|---:|---:|---:|---:|---:|---|
| Parquet puro | 16 ms | 1 arquivo, 445 kB | 72 ms (reescrita total) | 1 arquivo, 444 kB | 5,8 ms | não |
| Delta (delta-rs) | 30 ms | 2 arquivos, 452 kB | 58 ms (`MERGE`) | 4 arquivos, 903 kB | 9,2 ms | sim |
| Iceberg (PyIceberg) | 74 ms | 6 arquivos, 477 kB | 132 ms (`upsert`) | 17 arquivos, 961 kB | 7,8 ms | sim |

Os três devolveram as mesmas 21.431 linhas depois do lote. Em Delta e Iceberg, a leitura da
primeira versão devolveu o valor original da despesa corrigida.

Leitura dos números:

- **Desempenho não decide.** Tudo fica abaixo de 150 ms na escrita e de 10 ms na consulta,
  contra 10 min e 2 s tolerados.
- **Histórico decide contra o Parquet puro.** É o único que perde o valor anterior.
- **Peso operacional decide entre Delta e Iceberg.** Delta precisou de 2 arquivos e nenhum
  catálogo; Iceberg, de 6 arquivos e um catálogo SQLite, e chegou a 17 arquivos depois de um
  único lote.
- **Os dois formatos reescrevem o arquivo de dados a cada lote.** Com uma só correção o tamanho
  dobrou (452 para 903 kB em Delta, 477 para 961 kB em Iceberg).

A tabela acima foi medida em Windows, contra um PostgreSQL 16 local carregado pelo job
`expenses`. O mesmo script foi reproduzido em 13/10/2026 no Docker com PostgreSQL 15 e
21.430 despesas: os três formatos terminaram com 21.431 linhas após o lote, e as versões
anteriores continuaram legíveis em Delta e Iceberg. Os tempos variaram entre ambientes.

## Decisão

**1. Adotamos Debezium + Kafka Connect (Zookeeper, Kafka, Kafka Connect) capturando mudanças
de `oltp.despesas` via logical decoding (`pgoutput`), com publication dedicada e upsert
condicional como pré-requisito.** A recarga periódica continua sendo o que alimenta o OLTP; o
CDC é adotado pelo histórico de correções e pelo requisito da E2, não por frescor.

- `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10` e
  `max_slot_wal_keep_size=1GB` no serviço `postgres`.
- `PUBLICATION inflow_despesas_pub FOR TABLE oltp.despesas` + `REPLICA IDENTITY FULL`.
- Conector reaproveita o usuário do Postgres (já superuser da imagem, com `REPLICATION`
  implícito), sem role dedicada, por simplicidade dado o escopo acadêmico.
- Dados do Kafka e do Zookeeper em volumes nomeados, para preservar tópicos e offsets.
- Tópico resultante: `inflow.oltp.despesas`.

**2. Adotamos Delta Lake via delta-rs para tabelas que recebem correções (`despesas`) e Parquet
puro para as que são reescritas por inteiro a cada carga.** Iceberg fica descartado nesta
etapa: no cenário de um escritor Python, um leitor DuckDB e disco local, o catálogo é custo
sem contrapartida.

## Consequências

**Ganhos.** Trilha assíncrona e granular de cada mudança real em `despesas`, com valor anterior
e posterior, sem acoplar o Kafka ao pipeline de ingestão (roda em paralelo, não bloqueia
`make ingestion`). Na camada analítica, commit atômico e versões anteriores legíveis sem
nenhum serviço novo.

**Limitação conhecida.** Ainda não há um consumidor que leve os eventos do tópico para a tabela
Delta: a captura e o formato estão decididos, a ligação entre eles não está construída. Com o
conector parado, o replication slot retém WAL até o limite de 1 GB; passado esse limite, o
Postgres invalida o slot, e o conector precisa ser registrado de novo, com um novo snapshot.
`REPLICA IDENTITY FULL` também aumenta o WAL escrito por mudança em `despesas`.

**Perdas.** Três contêineres a mais para operar, em troca de um ganho que neste volume é de
rastreabilidade, não de desempenho. A tabela Delta cresce a cada lote, porque cada `MERGE`
reescreve o arquivo de dados: é preciso agendar `vacuum`, e o que o `vacuum` remove deixa de
ser legível como versão anterior. Ficamos sem o particionamento oculto e a neutralidade entre
motores do Iceberg.

**Irreversibilidade.** Baixa. `DROP PUBLICATION`/`pg_drop_replication_slot` revertem a
configuração do Postgres; desligar os serviços Kafka não afeta o pipeline de ingestão. Os dados
de uma tabela Delta são arquivos Parquet comuns, legíveis por qualquer motor e regraváveis em
Iceberg sem perda.

## Gatilho de revisão

Reafirmamos o gatilho já definido para a modelagem da origem (migrar para insert-only quando
mais de 1% das linhas de `despesas` mudarem de valor entre cargas) como sinal de que capturar
mudanças continua sendo necessário.

Voltamos à opção nula da decisão 1, ou a uma captura mais simples (logical decoding direto via
`psycopg2`, sem Kafka), quando:
- o overhead de manter Zookeeper + Kafka + Connect não se justificar pelo volume real de
  eventos (hoje, só mudanças genuínas em `despesas`, tipicamente poucas por dia);
- for preciso semântica *exactly-once* ponta a ponta. Esta etapa entrega *at-least-once*
  (Kafka Connect pode reentregar em caso de falha antes do commit de offset).

Revisamos a decisão 2 em favor do Iceberg quando houver um segundo motor escrevendo na mesma
tabela, quando a camada analítica sair do disco local para um armazenamento de objetos com
catálogo compartilhado, ou quando `despesas` precisar de particionamento que mude com o tempo.
