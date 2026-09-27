COMPOSE := docker compose

.PHONY: up down stop restart ps logs build-ingestion ingestion test docs docs-build db-shell

up:
	$(COMPOSE) up -d postgres migrate

down:
	$(COMPOSE) down

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart postgres

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f postgres migrate ingestion

build-ingestion:
	$(COMPOSE) build ingestion

ingestion: up
	$(COMPOSE) run --rm ingestion

test: up
	$(COMPOSE) run --rm ingestion pytest -q -p no:cacheprovider /tests

docs:
	$(COMPOSE) --profile docs up --build docs

docs-build:
	$(COMPOSE) --profile docs build docs

db-shell: up
	$(COMPOSE) exec postgres psql \
		-U $${POSTGRES_USER:-inflow_user} \
		-d $${POSTGRES_DB:-inflow_db}

