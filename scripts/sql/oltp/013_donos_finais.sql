-- ------------------------------------------------------------------------------
-- DONOS FINAIS DOS FORNECEDORES DA CEAPS
--
-- Parte do CNPJ do fornecedor e sobe pelo quadro de sócios (QSA) da RFB:
-- enquanto o sócio com participação no capital for uma empresa, repete com os
-- sócios dela. A cadeia termina quando encontra quem não é empresa (pessoa
-- física ou estrangeiro) ou quando não há como continuar; cada término recebe
-- um tipo_dono que diz por quê.
--
-- Limites da fonte: o QSA não traz percentual de participação, então não se
-- calcula quem controla; e sociedades anônimas não publicam acionistas, só
-- administradores, então a cadeia termina nelas como QSA_SEM_SOCIO_COM_CAPITAL.
-- ------------------------------------------------------------------------------

-- Qualificações que indicam participação no capital (dono). Administrador,
-- Diretor, Presidente, Conselheiro, Procurador etc. aparecem no QSA sem serem
-- donos. Ficam de fora também Sócio de Indústria (26) e Sócio sem Capital (53),
-- que não aportam capital, e Cotas em Tesouraria (63), que são da própria empresa.
CREATE OR REPLACE FUNCTION oltp.qualificacao_indica_propriedade(codigo SMALLINT)
RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT codigo IN (
        22, 23, 24, 25, 28, 29, 30, 31, 34, 37, 38, 47, 48, 49, 50, 52,
        55, 56, 57, 58, 65, 66, 67, 68, 69, 74, 78, 79
    );
$$;

CREATE OR REPLACE VIEW oltp.vw_donos_finais AS
WITH RECURSIVE
retrato AS (
    -- Retrato mais recente de cada empresa carregada.
    SELECT DISTINCT ON (cnpj_basico)
        cnpj_basico::text AS cnpj_basico, data_referencia, razao_social, natureza_juridica
    FROM oltp.empresas
    ORDER BY cnpj_basico, data_referencia DESC
),
fornecedor AS (
    SELECT
        f.id AS fornecedor_id,
        f.cnpj_cpf AS cnpj_fornecedor,
        left(regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g'), 8) AS basico
    FROM oltp.fornecedores f
    WHERE f.cnpj_cpf NOT LIKE '%*%'
      AND length(regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g')) = 14
),
cadeia AS (
    -- Nível 0: o próprio fornecedor.
    SELECT fo.fornecedor_id, fo.cnpj_fornecedor, fo.basico AS empresa, 0 AS nivel,
           ARRAY[fo.basico] AS caminho
    FROM fornecedor fo
    UNION ALL
    -- Nível n+1: empresas sócias, com participação, da empresa do nível n.
    SELECT c.fornecedor_id, c.cnpj_fornecedor, s.documento_socio::text, c.nivel + 1,
           c.caminho || s.documento_socio::text
    FROM cadeia c
    JOIN retrato r ON r.cnpj_basico = c.empresa
    JOIN oltp.socios s ON s.cnpj_basico = r.cnpj_basico AND s.data_referencia = r.data_referencia
    JOIN retrato rs ON rs.cnpj_basico = s.documento_socio
    WHERE s.tipo_socio = 1
      AND oltp.qualificacao_indica_propriedade(s.qualificacao)
      AND NOT s.documento_socio::text = ANY (c.caminho)  -- participação circular
      AND c.nivel < 10
),
socio_dono AS (
    -- Sócios com participação de cada empresa da cadeia.
    SELECT c.*, r.data_referencia, s.tipo_socio, s.nome_socio, s.documento_socio, s.qualificacao
    FROM cadeia c
    JOIN retrato r ON r.cnpj_basico = c.empresa
    JOIN oltp.socios s ON s.cnpj_basico = r.cnpj_basico AND s.data_referencia = r.data_referencia
    WHERE oltp.qualificacao_indica_propriedade(s.qualificacao)
),
terminal AS (
    -- Pessoa física ou estrangeiro: a cadeia chegou a quem não é empresa.
    SELECT fornecedor_id, cnpj_fornecedor, nivel + 1 AS nivel, caminho, data_referencia,
           CASE tipo_socio WHEN 2 THEN 'PESSOA_FISICA' ELSE 'ESTRANGEIRO' END AS tipo_dono,
           nome_socio AS nome_dono, documento_socio AS documento_dono, qualificacao
    FROM socio_dono
    WHERE tipo_socio IN (2, 3)

    UNION ALL

    -- Empresa sócia pela qual não dá para continuar subindo.
    SELECT sd.fornecedor_id, sd.cnpj_fornecedor, sd.nivel + 1, sd.caminho, sd.data_referencia,
           CASE
               WHEN sd.documento_socio IS NULL THEN 'PESSOA_JURIDICA_SEM_CNPJ'
               WHEN sd.documento_socio::text = ANY (sd.caminho) THEN 'CICLO'
               WHEN NOT EXISTS (SELECT 1 FROM retrato r WHERE r.cnpj_basico = sd.documento_socio)
                   THEN 'PESSOA_JURIDICA_SEM_DADOS'
               ELSE 'PROFUNDIDADE_MAXIMA'
           END,
           sd.nome_socio, sd.documento_socio, sd.qualificacao
    FROM socio_dono sd
    WHERE sd.tipo_socio = 1
      AND (sd.documento_socio IS NULL
           OR sd.documento_socio::text = ANY (sd.caminho)
           OR NOT EXISTS (SELECT 1 FROM retrato r WHERE r.cnpj_basico = sd.documento_socio)
           OR sd.nivel >= 10)

    UNION ALL

    -- Empresa da cadeia sem nenhum sócio com participação no QSA.
    SELECT c.fornecedor_id, c.cnpj_fornecedor, c.nivel, c.caminho, r.data_referencia,
           CASE
               WHEN r.cnpj_basico IS NULL THEN 'EMPRESA_NAO_ENCONTRADA'
               WHEN r.natureza_juridica = 2135 THEN 'EMPRESARIO_INDIVIDUAL'
               ELSE 'QSA_SEM_SOCIO_COM_CAPITAL'
           END,
           r.razao_social, c.empresa, NULL::smallint
    FROM cadeia c
    LEFT JOIN retrato r ON r.cnpj_basico = c.empresa
    WHERE NOT EXISTS (
        SELECT 1 FROM socio_dono sd
        WHERE sd.fornecedor_id = c.fornecedor_id AND sd.caminho = c.caminho
    )
)
SELECT
    t.fornecedor_id,
    t.cnpj_fornecedor,
    t.nivel,
    t.tipo_dono,
    t.nome_dono,
    t.documento_dono,
    q.descricao AS qualificacao_dono,
    t.caminho AS cadeia_cnpj,
    (
        SELECT string_agg(coalesce(r.razao_social, x.basico), ' > ' ORDER BY x.ordem)
        FROM unnest(t.caminho) WITH ORDINALITY AS x(basico, ordem)
        LEFT JOIN retrato r ON r.cnpj_basico = x.basico
    ) AS cadeia,
    t.data_referencia
FROM terminal t
LEFT JOIN oltp.qualificacoes_socio q ON q.codigo = t.qualificacao;

COMMENT ON VIEW oltp.vw_donos_finais IS
    'Donos finais de cada fornecedor da CEAPS: uma linha por caminho societário até quem não é empresa, '
    'ou até o ponto em que a cadeia não pode continuar (tipo_dono diz o motivo).';
COMMENT ON FUNCTION oltp.qualificacao_indica_propriedade(SMALLINT) IS
    'Verdadeiro para as qualificações da RFB que indicam participação no capital.';
