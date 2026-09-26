-- Objetos compartilhados pelas migracoes seguintes.

-- Atualiza atualizado_em a cada UPDATE de linha.
CREATE OR REPLACE FUNCTION trigger_set_atualizado_em()
RETURNS TRIGGER AS $$
BEGIN
    NEW.atualizado_em = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
