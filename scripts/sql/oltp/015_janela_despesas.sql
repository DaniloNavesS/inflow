-- Regra de janela e de dado atrasado para despesas da CEAPS (E2).
-- Janela fixa mensal pelo tempo de evento (data_despesa); o watermark segue a maior
-- competência (ano, mes) já vista menos o atraso permitido. Lançamento que cai em janela
-- já fechada não é descartado: fica registrado como ATRASADO, fora do total fechado.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Uma linha por fluxo processado: o watermark e o último lote.
CREATE TABLE IF NOT EXISTS analytics.janela_controle (
    fluxo VARCHAR(50) PRIMARY KEY,
    atraso_permitido_meses SMALLINT NOT NULL CHECK (atraso_permitido_meses >= 0),
    watermark DATE, -- janelas com fim <= watermark estão fechadas; nulo antes do 1º lote
    ultimo_lote INTEGER NOT NULL DEFAULT 0,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- O que cada despesa contribui hoje para as janelas; permite detectar correções.
CREATE TABLE IF NOT EXISTS analytics.janela_despesas_estado (
    fluxo VARCHAR(50) NOT NULL REFERENCES analytics.janela_controle(fluxo) ON DELETE CASCADE,
    despesa_id BIGINT NOT NULL,
    senador_id INT NOT NULL,
    janela_inicio DATE NOT NULL,
    valor NUMERIC(14, 2) NOT NULL,
    PRIMARY KEY (fluxo, despesa_id)
);

-- Razão somente de inserção: cada linha é um delta aplicado a uma janela.
CREATE TABLE IF NOT EXISTS analytics.janela_despesas_lancamentos (
    id BIGSERIAL PRIMARY KEY,
    fluxo VARCHAR(50) NOT NULL REFERENCES analytics.janela_controle(fluxo) ON DELETE CASCADE,
    lote INTEGER NOT NULL,
    despesa_id BIGINT NOT NULL,
    senador_id INT NOT NULL,
    janela_inicio DATE NOT NULL,
    delta_valor NUMERIC(14, 2) NOT NULL,
    delta_quantidade SMALLINT NOT NULL CHECK (delta_quantidade IN (-1, 1)),
    classificacao VARCHAR(10) NOT NULL,
    motivo VARCHAR(10) NOT NULL,
    origem_tempo_evento VARCHAR(12) NOT NULL,
    watermark_no_lote DATE, -- watermark usado para classificar este lançamento
    processado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_janela_lancamento_classificacao
        CHECK (classificacao IN ('NO_PRAZO', 'ATRASADO')),
    CONSTRAINT chk_janela_lancamento_motivo
        CHECK (motivo IN ('INSERCAO', 'CORRECAO')),
    CONSTRAINT chk_janela_lancamento_origem
        CHECK (origem_tempo_evento IN ('DATA_DESPESA', 'COMPETENCIA')),
    CONSTRAINT chk_janela_lancamento_inicio_do_mes
        CHECK (janela_inicio = date_trunc('month', janela_inicio)::date)
);

CREATE INDEX IF NOT EXISTS idx_janela_lancamentos_janela
    ON analytics.janela_despesas_lancamentos(fluxo, janela_inicio, senador_id);
CREATE INDEX IF NOT EXISTS idx_janela_lancamentos_atrasados
    ON analytics.janela_despesas_lancamentos(fluxo, lote)
    WHERE classificacao = 'ATRASADO';

-- Gasto por senador e mês: o total fechado (no prazo) separado do ajuste tardio.
CREATE OR REPLACE VIEW analytics.vw_despesas_janela_mensal AS
SELECT
    l.fluxo,
    l.janela_inicio,
    (l.janela_inicio + INTERVAL '1 month')::date AS janela_fim,
    l.senador_id,
    CASE
        WHEN c.watermark IS NOT NULL
            AND (l.janela_inicio + INTERVAL '1 month')::date <= c.watermark THEN 'FECHADA'
        ELSE 'ABERTA'
    END AS situacao,
    COALESCE(sum(l.delta_quantidade) FILTER (WHERE l.classificacao = 'NO_PRAZO'), 0)
        AS quantidade_no_prazo,
    COALESCE(sum(l.delta_valor) FILTER (WHERE l.classificacao = 'NO_PRAZO'), 0)
        AS total_no_prazo,
    count(*) FILTER (WHERE l.classificacao = 'ATRASADO') AS lancamentos_tardios,
    COALESCE(sum(l.delta_valor) FILTER (WHERE l.classificacao = 'ATRASADO'), 0)
        AS ajuste_tardio,
    sum(l.delta_valor) AS total_revisado
FROM analytics.janela_despesas_lancamentos l
JOIN analytics.janela_controle c ON c.fluxo = l.fluxo
GROUP BY l.fluxo, l.janela_inicio, l.senador_id, c.watermark;

COMMENT ON TABLE analytics.janela_despesas_lancamentos IS
    'Deltas por janela mensal de despesas; ATRASADO é o que chegou com a janela já fechada.';
COMMENT ON COLUMN analytics.janela_controle.watermark IS
    'Primeiro dia do mês da maior competência vista menos o atraso permitido; nunca recua.';
