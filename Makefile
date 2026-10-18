COMPOSE=docker compose

.DEFAULT_GOAL := help

.PHONY: help start down stop restart ps logs ingestion test cnpj-test build-ingestion cnpj migrate-cnpj migrate-cdc migrate-janela janela janela-reset janela-test cdc-up cdc-register cdc-status cdc-test cdc-semantics cdc-replay-demo docs docs-build db-shell clean

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
		'  make cnpj-test        Roda a integração CNPJ em PostgreSQL descartável' \
		'  make migrate-cnpj     Aplica o esquema CNPJ em banco existente' \
		'  make migrate-cdc      Cria a publication de CDC em banco existente' \
		'  make migrate-janela   Cria o esquema das janelas de despesas em banco existente' \
		'  make janela           Processa um lote das janelas de despesas (dado atrasado)' \
		'  make janela-reset     Recomeça as janelas do zero e reprocessa tudo' \
		'  make janela-test      Roda o teste da regra de dado atrasado' \
		'  make cdc-up           Sobe Zookeeper, Kafka e Kafka Connect' \
		'  make cdc-register     Registra o conector Debezium para despesas' \
		'  make cdc-status       Mostra o status do conector Debezium' \
		'  make cdc-test         Roda o teste de propagação de CDC (UPDATE -> Kafka)' \
		'  make cdc-semantics    Roda o teste de semântica de entrega (replay e deduplicação)' \
		'  make cdc-replay-demo  Executa a demonstração formatada de replay do CDC' \
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

migrate-janela: start
	$(COMPOSE) exec -T postgres sh -c 'psql --single-transaction -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -f /migrations/015_janela_despesas.sql'

janela: migrate-janela build-ingestion
	$(COMPOSE) run --rm ingestion python main.py janela

janela-reset: migrate-janela build-ingestion
	$(COMPOSE) run --rm ingestion python main.py janela --reiniciar

janela-test: migrate-janela build-ingestion
	$(COMPOSE) run --rm ingestion pytest -v -p no:cacheprovider /tests/test_janela_dado_atrasado.py

cdc-up: migrate-cdc
	$(COMPOSE) up -d --wait zookeeper kafka kafka-connect

cdc-register: cdc-up
	bash scripts/cdc/register-connector.sh

cdc-status:
	$(COMPOSE) exec -T kafka-connect curl -s http://localhost:8083/connectors/inflow-despesas-connector/status | python3 -m json.tool

cdc-test: cdc-register
	$(COMPOSE) run --rm -e CDC_INTEGRATION_TEST=1 ingestion pytest -q -p no:cacheprovider /tests/test_cdc_integration.py

cdc-semantics: cdc-register build-ingestion
	$(COMPOSE) run --rm -e CDC_INTEGRATION_TEST=1 ingestion pytest -v -p no:cacheprovider /tests/test_delivery_semantics.py

cdc-replay-demo: cdc-register build-ingestion
	$(COMPOSE) run --rm -v ./scripts:/scripts:ro -e KAFKA_HOST=kafka ingestion python /scripts/cdc/replay_demo.py

ingestion: migrate-cnpj migrate-janela build-ingestion
	$(COMPOSE) run --rm ingestion

cnpj: migrate-cnpj
	$(COMPOSE) run --rm ingestion python main.py cnpj

test:
	@set -e; \
	compose='$(COMPOSE) -p inflow-test-suite -f docker-compose.yml -f tests/docker-compose.test.yml'; \
	trap "$$compose down --volumes --remove-orphans" EXIT; \
	$$compose up -d --build --wait postgres; \
	$$compose run --build --rm ingestion; \
	$$compose run --rm ingestion pytest -q -p no:cacheprovider --ignore=/tests/test_cnpj_integration.py /tests
	$(MAKE) cnpj-test

cnpj-test:
	@set -e; \
	compose='$(COMPOSE) -p inflow-cnpj-integration -f tests/docker-compose.cnpj.yml'; \
	trap "$$compose down --volumes --remove-orphans" EXIT; \
	$$compose run --build --rm integration pytest -q -p no:cacheprovider /tests/test_cnpj_integration.py

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
