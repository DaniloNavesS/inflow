CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.payloads_brutos (
    id BIGSERIAL PRIMARY KEY,
    tipo_entidade VARCHAR(100) NOT NULL,
    nome_fonte VARCHAR(100) NOT NULL,
    url_fonte TEXT NOT NULL,
    tipo_midia VARCHAR(100) NOT NULL,
    payload_json JSONB,
    payload_binario BYTEA,
    sha256 CHAR(64) NOT NULL,
    status_http SMALLINT,
    ano_ingestao INTEGER,
    primeira_execucao_id UUID REFERENCES monitoring.pipeline_runs(run_id) ON DELETE SET NULL,
    ultima_execucao_id UUID REFERENCES monitoring.pipeline_runs(run_id) ON DELETE SET NULL,
    recebido_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    visto_por_ultimo_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_bronze_um_payload CHECK (
        (payload_json IS NOT NULL AND payload_binario IS NULL)
        OR (payload_json IS NULL AND payload_binario IS NOT NULL)
    ),
    CONSTRAINT uq_bronze_origem_conteudo UNIQUE (url_fonte, sha256)
);

CREATE INDEX IF NOT EXISTS idx_bronze_tipo_entidade
    ON bronze.payloads_brutos(tipo_entidade);
CREATE INDEX IF NOT EXISTS idx_bronze_primeira_execucao
    ON bronze.payloads_brutos(primeira_execucao_id);
CREATE INDEX IF NOT EXISTS idx_bronze_recebido_em
    ON bronze.payloads_brutos(recebido_em);

COMMENT ON TABLE bronze.payloads_brutos IS
    'Respostas originais das fontes, preservadas antes de qualquer transformação de domínio.';
COMMENT ON COLUMN bronze.payloads_brutos.sha256 IS
    'Hash do conteúdo original; torna o reprocessamento idempotente por URL e conteúdo.';

