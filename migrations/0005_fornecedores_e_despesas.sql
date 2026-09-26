-- Fornecedores e lancamentos da cota parlamentar (CEAPS).

CREATE TABLE IF NOT EXISTS fornecedores (
    id BIGSERIAL PRIMARY KEY,
    cnpj_cpf VARCHAR(20) NOT NULL UNIQUE,
    razao_social VARCHAR(255) NOT NULL,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fornecedores_razao_social ON fornecedores(razao_social);

DROP TRIGGER IF EXISTS trg_fornecedores_atualizado_em ON fornecedores;
CREATE TRIGGER trg_fornecedores_atualizado_em
    BEFORE UPDATE ON fornecedores
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE fornecedores IS 'Pessoas fisicas ou juridicas pagas via cota parlamentar.';

CREATE TABLE IF NOT EXISTS despesas (
    id BIGINT PRIMARY KEY, -- id oficial do lancamento no Senado
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE RESTRICT,
    fornecedor_id BIGINT NOT NULL REFERENCES fornecedores(id) ON DELETE RESTRICT,
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

CREATE INDEX IF NOT EXISTS idx_despesas_senador_data ON despesas(senador_id, data_despesa);
CREATE INDEX IF NOT EXISTS idx_despesas_fornecedor_id ON despesas(fornecedor_id);
CREATE INDEX IF NOT EXISTS idx_despesas_tipo_despesa ON despesas(tipo_despesa);
CREATE INDEX IF NOT EXISTS idx_despesas_ano_mes ON despesas(ano, mes);

DROP TRIGGER IF EXISTS trg_despesas_atualizado_em ON despesas;
CREATE TRIGGER trg_despesas_atualizado_em
    BEFORE UPDATE ON despesas
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE despesas IS 'Gastos executados por meio da cota parlamentar.';
COMMENT ON COLUMN despesas.data_despesa IS 'Tempo de evento: data do documento fiscal.';
COMMENT ON COLUMN despesas.valor IS 'Valor liquido reembolsado em reais.';
