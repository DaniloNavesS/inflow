-- ------------------------------------------------------------------------------
-- TABELA: despesas
-- Registra despesas e reembolsos realizados por meio da cota parlamentar (CEAPS)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.despesas (
    id BIGINT PRIMARY KEY, -- ID oficial do registro de despesa no Senado Federal
    senador_id INT NOT NULL REFERENCES oltp.senadores(id) ON DELETE RESTRICT,
    fornecedor_id BIGINT NOT NULL REFERENCES oltp.fornecedores(id) ON DELETE RESTRICT,
    data_despesa DATE NOT NULL,
    ano SMALLINT NOT NULL CHECK (ano >= 2000 AND ano <= 2100),
    mes SMALLINT NOT NULL CHECK (mes >= 1 AND mes <= 12),
    tipo_despesa VARCHAR(255) NOT NULL,
    tipo_documento VARCHAR(100),
    num_documento VARCHAR(100),
    detalhamento TEXT,
    valor NUMERIC(14, 2) NOT NULL CHECK (valor >= 0),
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Índices B-Tree para suportar a Pergunta de Gestão Central
CREATE INDEX IF NOT EXISTS idx_despesas_senador_data
    ON oltp.despesas(senador_id, data_despesa);
CREATE INDEX IF NOT EXISTS idx_despesas_fornecedor_id
    ON oltp.despesas(fornecedor_id);
CREATE INDEX IF NOT EXISTS idx_despesas_tipo_despesa
    ON oltp.despesas(tipo_despesa);
CREATE INDEX IF NOT EXISTS idx_despesas_ano_mes
    ON oltp.despesas(ano, mes);

CREATE TRIGGER trg_despesas_atualizado_em
    BEFORE UPDATE ON oltp.despesas
    FOR EACH ROW
    EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

COMMENT ON TABLE oltp.despesas IS
    'Detalhamento dos gastos executados por meio da Cota Parlamentar (CEAPS).';
COMMENT ON COLUMN oltp.despesas.valor IS 'Valor líquido reembolsado em Reais (BRL).';
