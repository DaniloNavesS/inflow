-- ------------------------------------------------------------------------------
-- TABELA: estrutura_gabinete
-- Consolida a equipe e os benefícios habitacionais dos gabinetes por ano
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.estrutura_gabinete (
    id BIGSERIAL PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES oltp.senadores(id) ON DELETE CASCADE,
    ano SMALLINT NOT NULL CHECK (ano >= 2000 AND ano <= 2100),
    qtd_pessoal_gabinete INT NOT NULL DEFAULT 0 CHECK (qtd_pessoal_gabinete >= 0),
    qtd_pessoal_escritorio INT NOT NULL DEFAULT 0 CHECK (qtd_pessoal_escritorio >= 0),
    qtd_total_servidores INT GENERATED ALWAYS AS (
        qtd_pessoal_gabinete + qtd_pessoal_escritorio
    ) STORED,
    auxilio_moradia BOOLEAN NOT NULL DEFAULT FALSE,
    imovel_funcional BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unq_senador_ano_estrutura UNIQUE (senador_id, ano)
);

CREATE INDEX IF NOT EXISTS idx_estrutura_gabinete_senador
    ON oltp.estrutura_gabinete(senador_id);

CREATE TRIGGER trg_estrutura_gabinete_atualizado_em
    BEFORE UPDATE ON oltp.estrutura_gabinete
    FOR EACH ROW
    EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

COMMENT ON TABLE oltp.estrutura_gabinete IS
    'Estrutura quantitativa de servidores em gabinete/escritórios de apoio e benefícios habitacionais.';
