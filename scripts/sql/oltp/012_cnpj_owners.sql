-- ------------------------------------------------------------------------------
-- DADOS ABERTOS DO CNPJ (Receita Federal)
-- Empresas e quadro de sócios (QSA) dos fornecedores da CEAPS.
-- Layout oficial: https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf
--
-- A RFB publica um retrato por mês. data_referencia faz parte da chave, então
-- cada mês carregado é preservado (insert-only por mês): é possível perguntar
-- quem era sócio em um retrato anterior, coisa que a fonte não guarda.
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.qualificacoes_socio (
    codigo SMALLINT PRIMARY KEY,
    descricao VARCHAR(255) NOT NULL,
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.naturezas_juridicas (
    codigo SMALLINT PRIMARY KEY,
    descricao VARCHAR(255) NOT NULL,
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.empresas (
    cnpj_basico CHAR(8) NOT NULL,
    data_referencia DATE NOT NULL, -- primeiro dia do mês do retrato da RFB
    razao_social VARCHAR(255) NOT NULL,
    natureza_juridica SMALLINT REFERENCES oltp.naturezas_juridicas(codigo),
    qualificacao_responsavel SMALLINT REFERENCES oltp.qualificacoes_socio(codigo),
    capital_social NUMERIC(18, 2),
    porte CHAR(2),
    ente_federativo VARCHAR(150),
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cnpj_basico, data_referencia),
    CONSTRAINT chk_empresas_cnpj_basico CHECK (cnpj_basico ~ '^[0-9]{8}$'),
    CONSTRAINT chk_empresas_data_referencia CHECK (EXTRACT(DAY FROM data_referencia) = 1),
    CONSTRAINT chk_empresas_capital CHECK (capital_social IS NULL OR capital_social >= 0),
    CONSTRAINT chk_empresas_porte CHECK (porte IS NULL OR porte IN ('00', '01', '03', '05'))
);

CREATE TABLE IF NOT EXISTS oltp.socios (
    id BIGSERIAL PRIMARY KEY,
    cnpj_basico CHAR(8) NOT NULL,
    data_referencia DATE NOT NULL,
    tipo_socio SMALLINT NOT NULL, -- 1 PJ, 2 PF, 3 estrangeiro
    nome_socio VARCHAR(255) NOT NULL,
    documento_socio VARCHAR(14), -- CPF chega mascarado da fonte (***NNNNNN**)
    qualificacao SMALLINT NOT NULL REFERENCES oltp.qualificacoes_socio(codigo),
    data_entrada DATE,
    pais SMALLINT,
    documento_representante VARCHAR(14),
    nome_representante VARCHAR(255),
    qualificacao_representante SMALLINT REFERENCES oltp.qualificacoes_socio(codigo),
    faixa_etaria SMALLINT,
    timestamp_ingestao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cnpj_basico, data_referencia)
        REFERENCES oltp.empresas(cnpj_basico, data_referencia) ON DELETE CASCADE,
    CONSTRAINT chk_socios_tipo CHECK (tipo_socio IN (1, 2, 3)),
    CONSTRAINT chk_socios_faixa_etaria CHECK (faixa_etaria IS NULL OR faixa_etaria BETWEEN 0 AND 9),
    CONSTRAINT unq_socios_retrato UNIQUE NULLS NOT DISTINCT (
        cnpj_basico, data_referencia, tipo_socio, nome_socio, documento_socio, qualificacao
    )
);

CREATE INDEX IF NOT EXISTS idx_socios_nome ON oltp.socios(nome_socio);
CREATE INDEX IF NOT EXISTS idx_socios_documento ON oltp.socios(documento_socio);

DROP TRIGGER IF EXISTS trg_qualificacoes_socio_atualizado_em ON oltp.qualificacoes_socio;
CREATE TRIGGER trg_qualificacoes_socio_atualizado_em
    BEFORE UPDATE ON oltp.qualificacoes_socio
    FOR EACH ROW EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

DROP TRIGGER IF EXISTS trg_naturezas_juridicas_atualizado_em ON oltp.naturezas_juridicas;
CREATE TRIGGER trg_naturezas_juridicas_atualizado_em
    BEFORE UPDATE ON oltp.naturezas_juridicas
    FOR EACH ROW EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

DROP TRIGGER IF EXISTS trg_empresas_atualizado_em ON oltp.empresas;
CREATE TRIGGER trg_empresas_atualizado_em
    BEFORE UPDATE ON oltp.empresas
    FOR EACH ROW EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

-- Sócios de cada fornecedor com CNPJ, no retrato mais recente carregado.
CREATE OR REPLACE VIEW oltp.vw_socios_fornecedores AS
WITH documento AS (
    SELECT
        f.id AS fornecedor_id,
        f.cnpj_cpf,
        f.razao_social,
        regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g') AS digitos
    FROM oltp.fornecedores f
    WHERE f.cnpj_cpf NOT LIKE '%*%'
),
ultimo AS (
    SELECT cnpj_basico, max(data_referencia) AS data_referencia
    FROM oltp.empresas
    GROUP BY cnpj_basico
)
SELECT
    d.fornecedor_id,
    d.cnpj_cpf,
    d.razao_social AS razao_social_ceaps,
    e.razao_social AS razao_social_rfb,
    e.data_referencia,
    s.tipo_socio,
    s.nome_socio,
    s.documento_socio,
    s.qualificacao,
    q.descricao AS qualificacao_descricao,
    s.data_entrada,
    s.faixa_etaria
FROM documento d
JOIN ultimo u ON u.cnpj_basico = left(d.digitos, 8)
JOIN oltp.empresas e
    ON e.cnpj_basico = u.cnpj_basico AND e.data_referencia = u.data_referencia
LEFT JOIN oltp.socios s
    ON s.cnpj_basico = e.cnpj_basico AND s.data_referencia = e.data_referencia
LEFT JOIN oltp.qualificacoes_socio q ON q.codigo = s.qualificacao
WHERE length(d.digitos) = 14;

COMMENT ON TABLE oltp.empresas IS
    'Dados cadastrais da RFB das empresas fornecedoras da CEAPS, um retrato por mês.';
COMMENT ON TABLE oltp.socios IS
    'Quadro de sócios e administradores (QSA) da RFB das empresas fornecedoras, um retrato por mês.';
COMMENT ON COLUMN oltp.socios.documento_socio IS
    'CPF mascarado pela própria RFB (sem os 3 primeiros dígitos e os 2 verificadores) ou CNPJ do sócio PJ.';
