-- ------------------------------------------------------------------------------
-- TABELA: sessoes_presenca
-- Registra a presença e o voto de cada senador em sessões do Plenário
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.sessoes_presenca (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL, -- Código identificador da sessão plenária
    senador_id INT NOT NULL REFERENCES oltp.senadores(id) ON DELETE CASCADE,
    data_sessao DATE NOT NULL,
    presenca VARCHAR(50) NOT NULL, -- Ex: 'Presente', 'Votou', 'Ausente', 'Licença'
    tipo_sessao VARCHAR(50), -- Ex: 'Deliberativa Ordinária', 'Não-Deliberativa', 'Solenidade'
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unq_sessao_senador UNIQUE (sessao_id, senador_id, data_sessao)
);

CREATE INDEX IF NOT EXISTS idx_sessoes_presenca_senador_data
    ON oltp.sessoes_presenca(senador_id, data_sessao);
CREATE INDEX IF NOT EXISTS idx_sessoes_presenca_data
    ON oltp.sessoes_presenca(data_sessao);

COMMENT ON TABLE oltp.sessoes_presenca IS
    'Atuação legislativa e registros de presença/voto em sessões plenárias.';
