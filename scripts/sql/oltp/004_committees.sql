-- ------------------------------------------------------------------------------
-- TABELA: comissoes
-- Órgãos colegiados técnicos e temáticos do Senado e do Congresso Nacional
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.comissoes (
    id INT PRIMARY KEY, -- CodigoComissao oficial do Senado
    sigla VARCHAR(50) NOT NULL,
    nome VARCHAR(255) NOT NULL,
    casa VARCHAR(20) NOT NULL DEFAULT 'SF', -- 'SF' (Senado Federal) ou 'CN' (Congresso Nacional)
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TRIGGER trg_comissoes_atualizado_em
    BEFORE UPDATE ON oltp.comissoes
    FOR EACH ROW
    EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

COMMENT ON TABLE oltp.comissoes IS
    'Comissões permanentes, temporárias ou mistas do Senado e Congresso.';
