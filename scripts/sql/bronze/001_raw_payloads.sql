CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_payloads (
    id BIGSERIAL PRIMARY KEY,
    -- Identificação da origem
    entity_type VARCHAR(100) NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    source_url TEXT NOT NULL,
    -- Resposta original da API
    payload JSONB NOT NULL,
    -- Informações da requisição
    http_status SMALLINT,
    ingestion_year INTEGER,
    -- Rastreabilidade
    run_id UUID
        REFERENCES monitoring.pipeline_runs(run_id)
        ON DELETE SET NULL,

    batch_id UUID NOT NULL,
    -- Metadados
    received_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE INDEX IF NOT EXISTS idx_bronze_raw_entity
    ON bronze.raw_payloads(entity_type);

CREATE INDEX IF NOT EXISTS idx_bronze_raw_run
    ON bronze.raw_payloads(run_id);

CREATE INDEX IF NOT EXISTS idx_bronze_raw_batch
    ON bronze.raw_payloads(batch_id);

CREATE INDEX IF NOT EXISTS idx_bronze_raw_received
    ON bronze.raw_payloads(received_at);

CREATE INDEX IF NOT EXISTS idx_bronze_raw_year
    ON bronze.raw_payloads(ingestion_year);