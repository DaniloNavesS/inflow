# Mandato Aberto

Fonte transacional de dados públicos do Senado Federal para analisar CEAPS, fornecedores,
histórico parlamentar, comissões, presença plenária e estrutura de gabinete.

## Executar

Requer Docker, Docker Compose e GNU Make.

```bash
cp .env.example .env
make ingestion
```

O comando inicia o PostgreSQL, aplica as migrations pendentes e executa a carga. O banco fica em
`localhost:5433` por padrão. Para reprocessar, execute novamente `make ingestion`.

## Testar

```bash
make test              # Testes unitários e de qualidade dos dados
make cdc-test          # Teste de propagação de eventos CDC (Postgres -> Kafka)
make cdc-semantics     # Teste de semântica de entrega e replay (At-least-once vs. Effectively-once)
make cdc-replay-demo   # Demonstração comparativa de replay no terminal
```

## Documentação

Use `make docs` para servir o Docusaurus em `http://localhost:3000`. Perguntas, fontes, endpoints,
modelagem, limitações e decisões arquiteturais estão na
[documentação completa](https://danilonavess.github.io/inflow/docs/intro).
O **Mandato Aberto** é um projeto acadêmico de Engenharia de Dados voltado para coleta, processamento e análise de dados públicos do Senado Federal.


## Como executar

### Pré-requisitos

- Docker
- Docker Compose
- GNU Make

### 1. Clone o repositório

```bash
git clone https://github.com/DaniloNavesS/inflow.git
cd inflow
```

### 2. Configure o ambiente

```bash
cp .env.example .env
```

### 3. Suba a infraestrutura

```bash
make up
```

Esse comando inicia o PostgreSQL.

### 4. Execute a ingestão

```bash
make ingestion
```

O pipeline consulta as APIs do Senado Federal, processa os dados e os persiste no PostgreSQL.

---

## Comandos principais

```bash
make start            # Sobe o PostgreSQL e aguarda healthcheck
make ingestion        # Executa a carga do banco
make cdc-up           # Sobe infraestrutura CDC (Zookeeper, Kafka, Kafka Connect)
make cdc-register     # Registra conector Debezium de despesas
make cdc-test         # Roda teste de propagação de eventos CDC
make cdc-semantics    # Roda teste de replay e deduplicação
make cdc-replay-demo  # Executa demonstração formatada de replay no terminal
make test             # Executa a suíte de testes de qualidade
make db-shell         # Acessa o PostgreSQL via psql
make logs             # Exibe os logs dos contêineres
make ps               # Lista os contêineres ativos
make down             # Encerra o ambiente
make clean            # Remove contêineres e volumes persistentes
```

---

## Banco de dados

Configuração padrão:

```text
Host: localhost
Porta: 5432
Database: inflow_db
Usuário: inflow_user
Senha: inflow_pass
```

Para acessar pelo terminal:

```bash
make db-shell
```

---

## Estrutura de dados

Atualmente o banco possui dois schemas principais:

```text
oltp
monitoring
```

- `oltp`: dados transacionais provenientes das APIs do Senado;
- `monitoring`: métricas das execuções do pipeline.

---

## Documentação

A documentação completa do projeto, arquitetura, ADRs, modelo de dados e decisões técnicas está disponível no GitHub Pages do projeto.
