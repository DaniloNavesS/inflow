CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_payloads (
    id BIGSERIAL PRIMARY KEY,
    -- Identificação da origem
    entity_type VARCHAR(100) NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    source_url TEXT NOT NULL,
    -- Resposta original da fonte: JSON ou conteúdo binário, nunca ambos.
    payload JSONB,
    payload_binary BYTEA,
    media_type VARCHAR(100) NOT NULL DEFAULT 'application/json',
    content_sha256 CHAR(64),
    -- Informações da requisição
    http_status SMALLINT,
    ingestion_year INTEGER,
    -- Rastreabilidade
    run_id UUID
        REFERENCES monitoring.pipeline_runs(run_id)
        ON DELETE SET NULL,
    last_run_id UUID
        REFERENCES monitoring.pipeline_runs(run_id)
        ON DELETE SET NULL,

    batch_id UUID NOT NULL,
    -- Metadados
    received_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ
        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_bronze_raw_one_payload CHECK (
        (payload IS NOT NULL AND payload_binary IS NULL)
        OR (payload IS NULL AND payload_binary IS NOT NULL)
    ),
    CONSTRAINT uq_bronze_raw_source_content UNIQUE (source_url, content_sha256)
);

-- Evolução idempotente para volumes criados com a primeira versão da tabela.
ALTER TABLE bronze.raw_payloads ALTER COLUMN payload DROP NOT NULL;
ALTER TABLE bronze.raw_payloads ADD COLUMN IF NOT EXISTS payload_binary BYTEA;
ALTER TABLE bronze.raw_payloads ADD COLUMN IF NOT EXISTS media_type VARCHAR(100)
    NOT NULL DEFAULT 'application/json';
ALTER TABLE bronze.raw_payloads ADD COLUMN IF NOT EXISTS content_sha256 CHAR(64);
ALTER TABLE bronze.raw_payloads ADD COLUMN IF NOT EXISTS last_run_id UUID
    REFERENCES monitoring.pipeline_runs(run_id) ON DELETE SET NULL;
ALTER TABLE bronze.raw_payloads ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ
    NOT NULL DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_bronze_raw_one_payload'
          AND conrelid = 'bronze.raw_payloads'::regclass
    ) THEN
        ALTER TABLE bronze.raw_payloads
            ADD CONSTRAINT chk_bronze_raw_one_payload CHECK (
                (payload IS NOT NULL AND payload_binary IS NULL)
                OR (payload IS NULL AND payload_binary IS NOT NULL)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_bronze_raw_source_content'
          AND conrelid = 'bronze.raw_payloads'::regclass
    ) THEN
        ALTER TABLE bronze.raw_payloads
            ADD CONSTRAINT uq_bronze_raw_source_content
            UNIQUE (source_url, content_sha256);
    END IF;
END
$$;


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

CREATE INDEX IF NOT EXISTS idx_bronze_raw_sha256
    ON bronze.raw_payloads(content_sha256);
