COMPOSE=docker compose

.PHONY: up down stop restart ps logs ingestion build-ingestion db-shell clean benchmark benchmark-up benchmark-clean mariadb-shell

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
	$(COMPOSE) logs -f postgres migrate ingestion

build-ingestion:
	$(COMPOSE) build ingestion

ingestion: up
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

benchmark-up:
	$(COMPOSE) --profile benchmark up -d postgres mariadb

benchmark: benchmark-up
	$(COMPOSE) --profile benchmark run --rm --build db-benchmark

mariadb-shell:
	$(COMPOSE) --profile benchmark exec mariadb \
		mariadb -u$${MARIADB_USER:-inflow_user} \
		-p$${MARIADB_PASSWORD:-inflow_pass} \
		$${MARIADB_DATABASE:-benchmark}

benchmark-clean:
	$(COMPOSE) --profile benchmark down
	docker volume rm inflow_mariadb_data

clean:
	$(COMPOSE) down -v
