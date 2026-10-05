COMPOSE=docker compose

.PHONY: up down stop restart ps logs ingestion build-ingestion cnpj test docs docs-build db-shell clean

up:
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

ingestion: up
	$(COMPOSE) run --rm ingestion


cnpj: up
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
