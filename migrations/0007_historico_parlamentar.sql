-- Mandatos, exercicios e filiacoes preservam o valor vigente na data do fato.

ALTER TABLE senadores ALTER COLUMN partido DROP NOT NULL;
ALTER TABLE senadores ALTER COLUMN uf DROP NOT NULL;

CREATE TABLE mandatos (
    codigo_mandato BIGINT PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    uf CHAR(2) NOT NULL,
    participacao VARCHAR(80) NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_mandato_datas CHECK (data_fim >= data_inicio)
);

CREATE INDEX idx_mandatos_senador_periodo ON mandatos(senador_id, data_inicio, data_fim);

CREATE TABLE exercicios_mandato (
    codigo_exercicio BIGINT PRIMARY KEY,
    codigo_mandato BIGINT NOT NULL REFERENCES mandatos(codigo_mandato) ON DELETE CASCADE,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    data_inicio DATE NOT NULL,
    data_fim DATE,
    sigla_causa_afastamento VARCHAR(20),
    descricao_causa_afastamento TEXT,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_exercicio_datas CHECK (data_fim IS NULL OR data_fim >= data_inicio)
);

CREATE INDEX idx_exercicios_senador_periodo
    ON exercicios_mandato(senador_id, data_inicio, data_fim);

CREATE TABLE filiacoes_partidarias (
    id BIGSERIAL PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    codigo_partido INT,
    sigla_partido VARCHAR(50) NOT NULL,
    nome_partido VARCHAR(150),
    data_filiacao DATE NOT NULL,
    data_desfiliacao DATE,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_filiacao_datas CHECK (
        data_desfiliacao IS NULL OR data_desfiliacao >= data_filiacao
    ),
    CONSTRAINT unq_filiacao UNIQUE (senador_id, sigla_partido, data_filiacao)
);

CREATE INDEX idx_filiacoes_senador_periodo
    ON filiacoes_partidarias(senador_id, data_filiacao, data_desfiliacao);

COMMENT ON TABLE mandatos IS 'Mandatos oficiais do parlamentar, inclusive UF vigente.';
COMMENT ON TABLE exercicios_mandato IS 'Intervalos em que o parlamentar exerceu cada mandato.';
COMMENT ON TABLE filiacoes_partidarias IS 'Historico partidario; consultas temporais usam a filiacao vigente no evento.';
