-- Presenca oficial e rastreavel no Diario do Senado Federal (DSF).

DROP TABLE IF EXISTS sessoes_presenca;
DROP TABLE IF EXISTS sessoes;

CREATE TABLE sessao_plenaria (
    id BIGSERIAL PRIMARY KEY,
    numero INT NOT NULL,
    data_sessao DATE NOT NULL,
    tipo VARCHAR(100) NOT NULL,
    legislatura SMALLINT,
    sessao_legislativa SMALLINT,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unq_sessao_plenaria UNIQUE (numero, data_sessao)
);

CREATE TABLE documento_dsf (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL REFERENCES sessao_plenaria(id) ON DELETE CASCADE,
    codigo_diario BIGINT NOT NULL,
    numero_diario INT NOT NULL,
    data_publicacao DATE NOT NULL,
    url_documento TEXT NOT NULL,
    pagina_inicial INT NOT NULL,
    pagina_final INT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    status_parser VARCHAR(20) NOT NULL,
    mensagem_parser TEXT,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unq_documento_dsf UNIQUE (codigo_diario, pagina_inicial, pagina_final),
    CONSTRAINT chk_documento_paginas CHECK (pagina_final >= pagina_inicial),
    CONSTRAINT chk_documento_status CHECK (status_parser IN ('SUCESSO', 'PARCIAL', 'FALHA'))
);

CREATE TABLE registro_presenca (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL REFERENCES sessao_plenaria(id) ON DELETE CASCADE,
    documento_dsf_id BIGINT NOT NULL REFERENCES documento_dsf(id) ON DELETE CASCADE,
    senador_id INT REFERENCES senadores(id) ON DELETE RESTRICT,
    nome_documento VARCHAR(150) NOT NULL,
    partido_documento VARCHAR(50),
    uf_documento CHAR(2),
    situacao VARCHAR(20) NOT NULL,
    voto_registrado BOOLEAN,
    pagina INT NOT NULL,
    resolucao VARCHAR(20) NOT NULL,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unq_registro_presenca UNIQUE (documento_dsf_id, nome_documento),
    CONSTRAINT chk_presenca_situacao CHECK (situacao IN ('PRESENTE', 'DESCONHECIDO')),
    CONSTRAINT chk_presenca_resolucao CHECK (resolucao IN ('EXATA', 'AMBIGUA', 'NAO_RESOLVIDA'))
);

CREATE TABLE licenca_justificativa (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL REFERENCES sessao_plenaria(id) ON DELETE CASCADE,
    documento_dsf_id BIGINT REFERENCES documento_dsf(id) ON DELETE SET NULL,
    senador_id INT REFERENCES senadores(id) ON DELETE RESTRICT,
    tipo VARCHAR(100) NOT NULL,
    descricao TEXT,
    pagina INT,
    url_fonte TEXT NOT NULL,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sessao_plenaria_data ON sessao_plenaria(data_sessao);
CREATE INDEX idx_registro_presenca_senador ON registro_presenca(senador_id, sessao_id);
CREATE INDEX idx_licenca_senador ON licenca_justificativa(senador_id, sessao_id);

COMMENT ON TABLE registro_presenca IS
    'Presenca extraida do DSF; ausencia de linha ou falha do parser nunca e convertida em ausencia.';
COMMENT ON COLUMN registro_presenca.voto_registrado IS
    'Indicador documental de voto, independente da situacao de presenca.';
