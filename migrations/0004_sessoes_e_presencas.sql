-- Sessoes plenarias e a presenca/voto de cada senador nelas.

CREATE TABLE IF NOT EXISTS sessoes (
    id BIGINT PRIMARY KEY, -- codigoSessao da API do Senado
    data_sessao DATE NOT NULL,
    tipo_sessao VARCHAR(50),
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

DROP TRIGGER IF EXISTS trg_sessoes_atualizado_em ON sessoes;
CREATE TRIGGER trg_sessoes_atualizado_em
    BEFORE UPDATE ON sessoes
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

CREATE INDEX IF NOT EXISTS idx_sessoes_data ON sessoes(data_sessao);

COMMENT ON TABLE sessoes IS 'Sessoes plenarias identificadas pelo codigo oficial.';
COMMENT ON COLUMN sessoes.data_sessao IS 'Tempo de evento: data em que a sessao ocorreu.';

CREATE TABLE IF NOT EXISTS sessoes_presenca (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL REFERENCES sessoes(id) ON DELETE CASCADE,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    presenca VARCHAR(50) NOT NULL, -- Presente, Votou, Ausente, Licenca
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unq_sessao_senador UNIQUE (sessao_id, senador_id)
);

CREATE INDEX IF NOT EXISTS idx_sessoes_presenca_senador ON sessoes_presenca(senador_id);
CREATE INDEX IF NOT EXISTS idx_sessoes_presenca_sessao ON sessoes_presenca(sessao_id);

COMMENT ON TABLE sessoes_presenca IS 'Presenca ou voto de um senador em uma sessao.';
