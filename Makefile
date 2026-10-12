COMPOSE=docker compose

ifneq (,$(wildcard .env))
	include .env
	export
endif

.DEFAULT_GOAL := help

.PHONY: help start down stop restart ps logs ingestion test build-ingestion cnpj migrate-cnpj migrate-cdc cdc-up cdc-register cdc-status cdc-test docs docs-build db-shell clean

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
		'  make migrate-cdc      Cria a publication de CDC em banco existente' \
		'  make cdc-up           Sobe Zookeeper, Kafka e Kafka Connect' \
		'  make cdc-register     Registra o conector Debezium para despesas' \
		'  make cdc-status       Mostra o status do conector Debezium' \
		'  make cdc-test         Roda o teste de propagação de CDC (UPDATE -> Kafka)' \
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

migrate-cdc: start
	$(COMPOSE) exec -T postgres sh -c 'psql --single-transaction -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -f /migrations/014_cdc_publication.sql'

cdc-up: migrate-cdc
	$(COMPOSE) up -d --wait zookeeper kafka kafka-connect

cdc-register: cdc-up
	KAFKA_CONNECT_PORT=$${KAFKA_CONNECT_PORT:-8083} bash scripts/cdc/register-connector.sh

cdc-status:
	curl -s http://localhost:$${KAFKA_CONNECT_PORT:-8083}/connectors/inflow-despesas-connector/status | python3 -m json.tool

cdc-test: cdc-register
	$(COMPOSE) run --rm -e CDC_INTEGRATION_TEST=1 ingestion pytest -q -p no:cacheprovider /tests/test_cdc_integration.py

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
