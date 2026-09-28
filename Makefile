COMPOSE=docker compose

.DEFAULT_GOAL := help

.PHONY: help start down stop restart ps logs ingestion test build-ingestion docs docs-build db-shell clean

help:
	@printf '%s\n' \
		'Comandos disponíveis:' \
		'  make start            Sobe o PostgreSQL em segundo plano' \
		'  make down             Derruba os contêineres' \
		'  make stop             Para os contêineres sem removê-los' \
		'  make restart          Reinicia o PostgreSQL' \
		'  make ps               Lista os contêineres' \
		'  make logs             Acompanha os logs' \
		'  make ingestion        Executa a ingestão' \
		'  make test             Executa a ingestão e os testes' \
		'  make build-ingestion  Reconstrói a imagem do ingestor' \
		'  make docs             Serve a documentação' \
		'  make docs-build       Constrói a imagem da documentação' \
		'  make db-shell         Abre o psql' \
		'  make clean            Derruba os contêineres e remove os volumes'

start:
	$(COMPOSE) up -d postgres

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

ingestion: start
	$(COMPOSE) run --rm ingestion

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
