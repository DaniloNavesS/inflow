-- ------------------------------------------------------------------------------
-- TABELA: fornecedores
-- Identifica os fornecedores pagos por meio da cota parlamentar (CEAPS)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.fornecedores (
    id BIGSERIAL PRIMARY KEY,
    cnpj_cpf VARCHAR(20) NOT NULL UNIQUE,
    razao_social VARCHAR(255) NOT NULL,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fornecedores_cnpj_cpf
    ON oltp.fornecedores(cnpj_cpf);
CREATE INDEX IF NOT EXISTS idx_fornecedores_razao_social
    ON oltp.fornecedores(razao_social);

CREATE TRIGGER trg_fornecedores_atualizado_em
    BEFORE UPDATE ON oltp.fornecedores
    FOR EACH ROW
    EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

COMMENT ON TABLE oltp.fornecedores IS
    'Pessoas físicas ou jurídicas fornecedoras de bens/serviços contratadas via CEAPS.';
