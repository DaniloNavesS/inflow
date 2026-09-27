-- Identidade do fornecedor sem colapsar documentos ausentes numa entidade unica.

ALTER TABLE fornecedores ALTER COLUMN cnpj_cpf DROP NOT NULL;
ALTER TABLE fornecedores DROP CONSTRAINT fornecedores_cnpj_cpf_key;
ALTER TABLE fornecedores ADD COLUMN tipo_identificador VARCHAR(20);
ALTER TABLE fornecedores ADD COLUMN identificador_normalizado VARCHAR(20);
ALTER TABLE fornecedores ADD COLUMN nome_normalizado VARCHAR(255);
ALTER TABLE fornecedores ADD COLUMN chave_deduplicacao VARCHAR(600);

UPDATE fornecedores
SET tipo_identificador = CASE
        WHEN cnpj_cpf = 'SEM_DOCUMENTO' THEN 'AUSENTE'
        WHEN regexp_replace(cnpj_cpf, '\D', '', 'g') ~ '^\d{14}$' THEN 'CNPJ'
        WHEN cnpj_cpf LIKE '%*%' THEN 'CPF_MASCARADO'
        ELSE 'OUTRO'
    END,
    identificador_normalizado = NULLIF(regexp_replace(cnpj_cpf, '\D', '', 'g'), ''),
    nome_normalizado = upper(trim(regexp_replace(razao_social, '\s+', ' ', 'g'))),
    chave_deduplicacao = CASE
        WHEN cnpj_cpf = 'SEM_DOCUMENTO'
            THEN 'AUSENTE:' || upper(trim(regexp_replace(razao_social, '\s+', ' ', 'g'))) || ':' || id
        ELSE 'LEGADO:' || cnpj_cpf
    END;

ALTER TABLE fornecedores ALTER COLUMN tipo_identificador SET NOT NULL;
ALTER TABLE fornecedores ALTER COLUMN nome_normalizado SET NOT NULL;
ALTER TABLE fornecedores ALTER COLUMN chave_deduplicacao SET NOT NULL;
ALTER TABLE fornecedores ADD CONSTRAINT unq_fornecedor_chave UNIQUE (chave_deduplicacao);
ALTER TABLE fornecedores ADD CONSTRAINT chk_fornecedor_tipo CHECK (
    tipo_identificador IN ('CNPJ', 'CPF', 'CPF_MASCARADO', 'AUSENTE', 'OUTRO')
);

CREATE INDEX idx_fornecedores_nome_normalizado ON fornecedores(nome_normalizado);

COMMENT ON COLUMN fornecedores.chave_deduplicacao IS
    'CNPJ/CPF quando completo; documento mascarado mais nome; ou nome mais id da despesa quando ausente.';
