# InFlow

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
make test
```

## Comparar PostgreSQL e MariaDB

```bash
make benchmark
```

O benchmark reproduz a carga SQL dos jobs nos dois bancos, sem incluir a latência das APIs, e
gera tabelas em Markdown/JSON para uso na ADR. Detalhes em
[`benchmark/README.md`](benchmark/README.md).

## Documentação

Use `make docs` para servir o Docusaurus em `http://localhost:3000`. Perguntas, fontes, endpoints,
modelagem, limitações e decisões arquiteturais estão na
[documentação completa](https://danilonavess.github.io/inflow/docs/intro).
O **InFlow** é um projeto acadêmico de Engenharia de Dados voltado para coleta, processamento e análise de dados públicos do Senado Federal.


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
make up          # Sobe a infraestrutura
make ingestion   # Executa a ingestão
make build       # Reconstrói o ingestor
make db-shell    # Acessa o PostgreSQL
make logs        # Exibe os logs
make ps          # Lista os containers
make down        # Encerra o ambiente
make clean       # Remove containers e volumes
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
