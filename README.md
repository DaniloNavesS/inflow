# InFlow — Execução do Ambiente (E1)

Guia rápido para inicializar o banco de dados PostgreSQL e executar a carga automatizada de dados (Seed) do Senado Federal via Docker.

---

## 🚀 Como Executar

### Pré-requisitos
* [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/)


---

### Passo a Passo Rápido

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/DaniloNavesS/inflow.git
   cd inflow
   ```

2. **Configure as variáveis de ambiente (opcional):**
   ```bash
   cp .env.example .env
   ```

3. **Suba o banco e execute o seed automaticamente:**
   ```bash
   docker compose up --build
   ```

---

## 🌱 Carga de Dados (Seed)

O processo de **Seed** consome diretamente as APIs públicas do Senado Federal, trata os dados em memória e realiza o *upsert* idempotente no PostgreSQL.

### 1. Execução Automática (Padrão)
Ao executar `docker compose up --build`, o serviço `ingestor` roda o seed automaticamente assim que o PostgreSQL estiver pronto (*healthy*).

### 2. Como reexecutar o Seed sob demanda
Se o contêiner do banco já estiver rodando e você quiser rodar o seed novamente (ou atualizar os dados):
```bash
docker compose run --rm ingestor
```

### 3. Como rodar o Seed para outro ano fiscal (ex: 2023)
```bash
# Via variável inline no Docker:
docker compose run --rm -e INGESTION_YEAR=2023 ingestor
```

### 4. Executar o Seed localmente via Python (Opcional, sem Docker para o script)
Caso queira rodar o script de seed diretamente na máquina hospedeira apontando para o PostgreSQL:
```bash
# 1. Instale as dependências
pip install -r ingestor/requirements.txt

# 2. Execute o seed apontando para a porta exposta (5433)
DB_HOST=localhost DB_PORT=5433 python ingestor/main.py
```

---

## 📊 Acesso e Validação do Banco

### Dados de Conexão (DBeaver / pgAdmin / psql):
* **Host:** `localhost`
* **Porta:** `5433` (ou a definida no `.env`)
* **Database:** `inflow_db`
* **Usuário:** `inflow_user`
* **Senha:** `inflow_pass`

---

### Validar se os dados foram populados (via Terminal)

Execute o comando abaixo para verificar a contagem de registros em cada tabela:

```bash
docker exec -it inflow_postgres psql -U inflow_user -d inflow_db -c "
SELECT 'senadores' AS tabela, COUNT(*) AS total FROM senadores
UNION ALL
SELECT 'comissoes', COUNT(*) FROM comissoes
UNION ALL
SELECT 'participacoes_comissao', COUNT(*) FROM participacoes_comissao
UNION ALL
SELECT 'sessoes', COUNT(*) FROM sessoes
UNION ALL
SELECT 'sessoes_presenca', COUNT(*) FROM sessoes_presenca
UNION ALL
SELECT 'fornecedores', COUNT(*) FROM fornecedores
UNION ALL
SELECT 'despesas', COUNT(*) FROM despesas
UNION ALL
SELECT 'estrutura_gabinete', COUNT(*) FROM estrutura_gabinete;
"
```

---

## 🛑 Como Parar o Ambiente

Para parar os contêineres:
```bash
docker compose down
```

Para parar e remover o volume persistente (resetando o banco do zero):
```bash
docker compose down -v
```
