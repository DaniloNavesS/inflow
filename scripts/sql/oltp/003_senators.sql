-- ------------------------------------------------------------------------------
-- TABELA: senadores
-- Armazena o perfil parlamentar dos senadores da República
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oltp.senadores (
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
            'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO',
            'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI',
            'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
        )
    )
);

CREATE TRIGGER trg_senadores_atualizado_em
    BEFORE UPDATE ON oltp.senadores
    FOR EACH ROW
    EXECUTE FUNCTION oltp.trigger_set_atualizado_em();

COMMENT ON TABLE oltp.senadores IS
    'Entidade principal de perfil parlamentar dos senadores federais.';
COMMENT ON COLUMN oltp.senadores.id IS
    'Identificador numérico único fornecido pela API do Senado (CodigoParlamentar).';
