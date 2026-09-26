-- Perfil parlamentar dos senadores.

CREATE TABLE IF NOT EXISTS senadores (
    id INT PRIMARY KEY, -- CodigoParlamentar da API do Senado
    nome VARCHAR(150) NOT NULL,
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

DROP TRIGGER IF EXISTS trg_senadores_atualizado_em ON senadores;
CREATE TRIGGER trg_senadores_atualizado_em
    BEFORE UPDATE ON senadores
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_atualizado_em();

CREATE INDEX IF NOT EXISTS idx_senadores_uf_partido ON senadores(uf, partido);

COMMENT ON TABLE senadores IS 'Perfil parlamentar dos senadores federais.';
COMMENT ON COLUMN senadores.timestamp_ingestao IS 'Tempo de ingestao: quando a linha entrou no banco.';
COMMENT ON COLUMN senadores.atualizado_em IS 'Tempo de processamento: ultimo UPDATE do ingestor.';
