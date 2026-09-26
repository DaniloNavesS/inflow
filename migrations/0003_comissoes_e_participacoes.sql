-- Comissoes e os assentos ocupados pelos senadores.

CREATE TABLE IF NOT EXISTS comissoes (
    id INT PRIMARY KEY, -- CodigoComissao da API do Senado
    sigla VARCHAR(50) NOT NULL,
    nome VARCHAR(255) NOT NULL,
    casa VARCHAR(20) NOT NULL DEFAULT 'SF',
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_comissoes_casa CHECK (casa IN ('SF', 'CN', 'CD'))
);

DROP TRIGGER IF EXISTS trg_comissoes_atualizado_em ON comissoes;
CREATE TRIGGER trg_comissoes_atualizado_em
    BEFORE UPDATE ON comissoes
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE comissoes IS 'Comissoes permanentes, temporarias ou mistas.';

CREATE TABLE IF NOT EXISTS participacoes_comissao (
    id BIGSERIAL PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    comissao_id INT NOT NULL REFERENCES comissoes(id) ON DELETE CASCADE,
    cargo VARCHAR(100) NOT NULL, -- Titular, Suplente, Presidente, Vice-Presidente
    data_inicio DATE,
    data_fim DATE,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_datas_participacao CHECK (data_fim IS NULL OR data_fim >= data_inicio),
    CONSTRAINT unq_senador_comissao_cargo UNIQUE (senador_id, comissao_id, cargo, data_inicio)
);

CREATE INDEX IF NOT EXISTS idx_participacoes_senador_id ON participacoes_comissao(senador_id);
CREATE INDEX IF NOT EXISTS idx_participacoes_comissao_id ON participacoes_comissao(comissao_id);

COMMENT ON TABLE participacoes_comissao IS 'Relacao n:m entre senadores e comissoes, com historico de cargo.';
COMMENT ON COLUMN participacoes_comissao.data_inicio IS 'Tempo de evento: inicio da vigencia do assento na origem.';
