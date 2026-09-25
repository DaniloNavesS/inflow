-- ==============================================================================
-- PROJETO INTEGRADO: BANCO DE DADOS 2 (UnB - FCTE)
-- Plataforma InFlow: "Do dado bruto à decisão pública"
-- Módulo E1: Fonte Transacional (OLTP) - Dados Abertos do Senado Federal
-- ==============================================================================

-- Configurações iniciais de sessão
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET timezone = 'UTC';

-- ------------------------------------------------------------------------------
-- EXTENSÕES
-- ------------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------------------------
-- FUNÇÕES E PROCEDIMENTOS UTILITÁRIOS
-- ------------------------------------------------------------------------------
-- Função de gatilho para atualização automática de timestamp de modificação
CREATE OR REPLACE FUNCTION trigger_set_atualizado_em()
RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------------------------
-- TABELA: senadores
-- Armazena o perfil parlamentar dos senadores da República
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS senadores (
    id INT PRIMARY KEY, -- CodigoParlamentar oficial do Senado
    nome VARCHAR(150) NOT NULL, -- Nome parlamentar usual
    nome_completo VARCHAR(255),
    partido VARCHAR(50) NOT NULL,
    uf CHAR(2) NOT NULL,
    foto_url TEXT,
    pagina_url TEXT,
    email VARCHAR(150),
    status VARCHAR(50) NOT NULL DEFAULT 'Em Exercício',
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_senadores_uf CHECK (
        uf IN (
            'AC','AL','AP','AM','BA','CE','DF','ES','GO',
            'MA','MT','MS','MG','PA','PB','PR','PE','PI',
            'RJ','RN','RS','RO','RR','SC','SP','SE','TO'
        )
    )
);

CREATE TRIGGER trg_senadores_atualizado_em
    BEFORE UPDATE ON senadores
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE senadores IS 'Entidade principal de perfil parlamentar dos senadores federais.';
COMMENT ON COLUMN senadores.id IS 'Identificador numérico único fornecido pela API do Senado (CodigoParlamentar).';

-- ------------------------------------------------------------------------------
-- TABELA: comissoes
-- Órgãos colegiados técnicos/temáticos do Senado e Congresso Nacional
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comissoes (
    id INT PRIMARY KEY, -- CodigoComissao oficial do Senado
    sigla VARCHAR(50) NOT NULL,
    nome VARCHAR(255) NOT NULL,
    casa VARCHAR(20) NOT NULL DEFAULT 'SF', -- 'SF' (Senado Federal) ou 'CN' (Congresso Nacional)
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TRIGGER trg_comissoes_atualizado_em
    BEFORE UPDATE ON comissoes
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE comissoes IS 'Comissões permanentes, temporárias ou mistas do Senado e Congresso.';

-- ------------------------------------------------------------------------------
-- TABELA: participacoes_comissao
-- Relação associativa n:m entre senadores e comissões com histórico de cargo
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS participacoes_comissao (
    id BIGSERIAL PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    comissao_id INT NOT NULL REFERENCES comissoes(id) ON DELETE CASCADE,
    cargo VARCHAR(100) NOT NULL, -- Ex: Titular, Suplente, Presidente, Vice-Presidente
    data_inicio DATE,
    data_fim DATE,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_datas_participacao CHECK (data_fim IS NULL OR data_fim >= data_inicio),
    CONSTRAINT unq_senador_comissao_cargo UNIQUE (senador_id, comissao_id, cargo, data_inicio)
);

CREATE INDEX IF NOT EXISTS idx_participacoes_senador_id ON participacoes_comissao(senador_id);
CREATE INDEX IF NOT EXISTS idx_participacoes_comissao_id ON participacoes_comissao(comissao_id);

COMMENT ON TABLE participacoes_comissao IS 'Histórico de assentos e papéis desempenhados pelos senadores em comissões.';

-- ------------------------------------------------------------------------------
-- TABELA: sessoes_presenca
-- Registro individualizado de presenças / votos em sessões do Plenário
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessoes_presenca (
    id BIGSERIAL PRIMARY KEY,
    sessao_id BIGINT NOT NULL, -- Código identificador da sessão plenária
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    data_sessao DATE NOT NULL,
    presenca VARCHAR(50) NOT NULL, -- Ex: 'Presente', 'Votou', 'Ausente', 'Licença'
    tipo_sessao VARCHAR(50), -- Ex: 'Deliberativa Ordinária', 'Não-Deliberativa', 'Solenidade'
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unq_sessao_senador UNIQUE (sessao_id, senador_id, data_sessao)
);

CREATE INDEX IF NOT EXISTS idx_sessoes_presenca_senador_data ON sessoes_presenca(senador_id, data_sessao);
CREATE INDEX IF NOT EXISTS idx_sessoes_presenca_data ON sessoes_presenca(data_sessao);

COMMENT ON TABLE sessoes_presenca IS 'Atuação legislativa e registros de presença/voto em sessões plenárias.';

-- ------------------------------------------------------------------------------
-- TABELA: fornecedores
-- Entidades receptoras de pagamentos provenientes da cota parlamentar (CEAPS)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fornecedores (
    id BIGSERIAL PRIMARY KEY,
    cnpj_cpf VARCHAR(20) NOT NULL UNIQUE,
    razao_social VARCHAR(255) NOT NULL,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fornecedores_cnpj_cpf ON fornecedores(cnpj_cpf);
CREATE INDEX IF NOT EXISTS idx_fornecedores_razao_social ON fornecedores(razao_social);

CREATE TRIGGER trg_fornecedores_atualizado_em
    BEFORE UPDATE ON fornecedores
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE fornecedores IS 'Pessoas físicas ou jurídicas fornecedoras de bens/serviços contratadas via CEAPS.';

-- ------------------------------------------------------------------------------
-- TABELA: despesas
-- Lançamentos contábeis e notas de reembolso da cota parlamentar (CEAPS)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS despesas (
    id BIGINT PRIMARY KEY, -- ID oficial do registro de despesa no Senado Federal
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

-- Índices B-Tree para suportar a Pergunta de Gestão Central
CREATE INDEX IF NOT EXISTS idx_despesas_senador_data ON despesas(senador_id, data_despesa);
CREATE INDEX IF NOT EXISTS idx_despesas_fornecedor_id ON despesas(fornecedor_id);
CREATE INDEX IF NOT EXISTS idx_despesas_tipo_despesa ON despesas(tipo_despesa);
CREATE INDEX IF NOT EXISTS idx_despesas_ano_mes ON despesas(ano, mes);

CREATE TRIGGER trg_despesas_atualizado_em
    BEFORE UPDATE ON despesas
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE despesas IS 'Detalhamento dos gastos executados por meio da Cota Parlamentar (CEAPS).';
COMMENT ON COLUMN despesas.valor IS 'Valor líquido reembolsado em Reais (BRL).';

-- ------------------------------------------------------------------------------
-- TABELA: estrutura_gabinete
-- Quantitativo de servidores de gabinete/escritórios e benefícios (Pergunta 14)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS estrutura_gabinete (
    id BIGSERIAL PRIMARY KEY,
    senador_id INT NOT NULL REFERENCES senadores(id) ON DELETE CASCADE,
    ano SMALLINT NOT NULL CHECK (ano >= 2000 AND ano <= 2100),
    qtd_pessoal_gabinete INT NOT NULL DEFAULT 0 CHECK (qtd_pessoal_gabinete >= 0),
    qtd_pessoal_escritorio INT NOT NULL DEFAULT 0 CHECK (qtd_pessoal_escritorio >= 0),
    qtd_total_servidores INT GENERATED ALWAYS AS (qtd_pessoal_gabinete + qtd_pessoal_escritorio) STORED,
    auxilio_moradia BOOLEAN NOT NULL DEFAULT FALSE,
    imovel_funcional BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp_ingestao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unq_senador_ano_estrutura UNIQUE (senador_id, ano)
);

CREATE INDEX IF NOT EXISTS idx_estrutura_gabinete_senador ON estrutura_gabinete(senador_id);

CREATE TRIGGER trg_estrutura_gabinete_atualizado_em
    BEFORE UPDATE ON estrutura_gabinete
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

COMMENT ON TABLE estrutura_gabinete IS 'Estrutura quantitativa de servidores em gabinete/escritórios de apoio e benefícios habitacionais.';

