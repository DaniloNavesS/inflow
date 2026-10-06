COMPOSE=docker compose

.DEFAULT_GOAL := help

.PHONY: help start down stop restart ps logs ingestion test build-ingestion cnpj migrate-cnpj docs docs-build db-shell clean

help:
	@printf '%s\n' \
		'Comandos disponíveis:' \
		'  make start            Sobe e aguarda o PostgreSQL ficar saudável' \
		'  make down             Derruba os contêineres' \
		'  make stop             Para os contêineres sem removê-los' \
		'  make restart          Reinicia o PostgreSQL' \
		'  make ps               Lista os contêineres' \
		'  make logs             Acompanha os logs' \
		'  make ingestion        Executa a ingestão' \
		'  make migrate-cnpj     Aplica o esquema CNPJ em banco existente' \
		'  make test             Executa a ingestão e os testes' \
		'  make build-ingestion  Reconstrói a imagem do ingestor' \
		'  make cnpj             Executa a carga de empresas e sócios da RFB' \
		'  make docs             Serve a documentação' \
		'  make docs-build       Constrói a imagem da documentação' \
		'  make db-shell         Abre o psql' \
		'  make clean            Derruba os contêineres e remove os volumes'

start:
	$(COMPOSE) up -d --wait postgres

down:
	$(COMPOSE) down

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart postgres

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f postgres ingestion

build-ingestion:
	$(COMPOSE) build ingestion

migrate-cnpj: start
	$(COMPOSE) exec -T postgres sh -c 'psql --single-transaction -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -f /migrations/012_cnpj_owners.sql -f /migrations/013_donos_finais.sql'

ingestion: migrate-cnpj
	$(COMPOSE) run --rm ingestion

cnpj: migrate-cnpj
	$(COMPOSE) run --rm ingestion python main.py cnpj

test: ingestion
	$(COMPOSE) run --rm ingestion pytest -q -p no:cacheprovider /tests

docs:
	$(COMPOSE) --profile docs up --build docs

docs-build:
	$(COMPOSE) --profile docs build docs

db-shell:
	$(COMPOSE) exec postgres \
		psql -U $${POSTGRES_USER:-inflow_user} \
		-d $${POSTGRES_DB:-inflow_db}

clean:
	$(COMPOSE) down -v
