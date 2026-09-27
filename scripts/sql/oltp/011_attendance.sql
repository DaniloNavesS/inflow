-- Presença oficial extraída do Diário do Senado Federal (DSF).

CREATE TABLE IF NOT EXISTS oltp.sessao_plenaria (
    id BIGSERIAL PRIMARY KEY,
    numero INTEGER NOT NULL,
    data_sessao DATE NOT NULL,
    tipo VARCHAR(100) NOT NULL,
    legislatura SMALLINT,
    sessao_legislativa SMALLINT,
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unq_oltp_sessao_plenaria UNIQUE (numero, data_sessao)
);

CREATE TABLE IF NOT EXISTS oltp.documento_dsf (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL REFERENCES oltp.sessao_plenaria(id) ON DELETE CASCADE,
    codigo_diario BIGINT NOT NULL,
    numero_diario INTEGER NOT NULL,
    data_publicacao DATE NOT NULL,
    url_documento TEXT NOT NULL,
    pagina_inicial INTEGER NOT NULL,
    pagina_final INTEGER NOT NULL,
    sha256 CHAR(64) NOT NULL,
    status_parser VARCHAR(20) NOT NULL,
    mensagem_parser TEXT,
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unq_oltp_documento_dsf
        UNIQUE (codigo_diario, pagina_inicial, pagina_final),
    CONSTRAINT chk_oltp_documento_paginas CHECK (pagina_final >= pagina_inicial),
    CONSTRAINT chk_oltp_documento_status
        CHECK (status_parser IN ('SUCESSO', 'PARCIAL', 'FALHA'))
);

CREATE TABLE IF NOT EXISTS oltp.registro_presenca (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL REFERENCES oltp.sessao_plenaria(id) ON DELETE CASCADE,
    documento_dsf_id BIGINT NOT NULL REFERENCES oltp.documento_dsf(id) ON DELETE CASCADE,
    senador_id INTEGER REFERENCES oltp.senadores(id) ON DELETE RESTRICT,
    nome_documento VARCHAR(150) NOT NULL,
    partido_documento VARCHAR(50),
    uf_documento CHAR(2),
    situacao VARCHAR(20) NOT NULL,
    voto_registrado BOOLEAN,
    pagina INTEGER NOT NULL,
    resolucao VARCHAR(20) NOT NULL,
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unq_oltp_registro_presenca UNIQUE (documento_dsf_id, nome_documento),
    CONSTRAINT chk_oltp_presenca_situacao
        CHECK (situacao IN ('PRESENTE', 'DESCONHECIDO')),
    CONSTRAINT chk_oltp_presenca_resolucao
        CHECK (resolucao IN ('EXATA', 'AMBIGUA', 'NAO_RESOLVIDA'))
);

CREATE INDEX IF NOT EXISTS idx_oltp_sessao_plenaria_data
    ON oltp.sessao_plenaria(data_sessao);
CREATE INDEX IF NOT EXISTS idx_oltp_registro_presenca_senador
    ON oltp.registro_presenca(senador_id, sessao_id);

COMMENT ON TABLE oltp.registro_presenca IS
    'Presença extraída do DSF; uma falha de parser nunca é convertida em ausência.';
COMMENT ON COLUMN oltp.registro_presenca.voto_registrado IS
    'Indicador documental de voto, independente da situação de presença.';
