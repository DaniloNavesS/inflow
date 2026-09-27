# InFlow

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
