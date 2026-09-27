-- ------------------------------------------------------------------------------
-- TABELA: participacoes_comissao
-- Relaciona senadores e comissões, mantendo o histórico de cargos exercidos
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.participacoes_comissao (
    id BIGSERIAL PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES oltp.senadores(id) ON DELETE CASCADE,
    comissao_id INT NOT NULL REFERENCES oltp.comissoes(id) ON DELETE CASCADE,
    cargo VARCHAR(100) NOT NULL, -- Ex: Titular, Suplente, Presidente, Vice-Presidente
    data_inicio DATE,
    data_fim DATE,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_datas_participacao CHECK (data_fim IS NULL OR data_fim >= data_inicio),
    CONSTRAINT unq_senador_comissao_cargo UNIQUE (
        senador_id,
        comissao_id,
        cargo,
        data_inicio
    )
);

CREATE INDEX IF NOT EXISTS idx_participacoes_senador_id
    ON oltp.participacoes_comissao(senador_id);
CREATE INDEX IF NOT EXISTS idx_participacoes_comissao_id
    ON oltp.participacoes_comissao(comissao_id);

COMMENT ON TABLE oltp.participacoes_comissao IS
    'Histórico de assentos e papéis desempenhados pelos senadores em comissões.';
