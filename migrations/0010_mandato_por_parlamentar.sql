-- CodigoMandato identifica a cadeira e pode aparecer para titular e suplentes.
-- A identidade do registro de mandato e o par cadeira + parlamentar.

ALTER TABLE exercicios_mandato
    DROP CONSTRAINT exercicios_mandato_codigo_mandato_fkey;

ALTER TABLE mandatos DROP CONSTRAINT mandatos_pkey;
ALTER TABLE mandatos ADD COLUMN id BIGSERIAL;
ALTER TABLE mandatos ADD CONSTRAINT mandatos_pkey PRIMARY KEY (id);
ALTER TABLE mandatos ADD CONSTRAINT unq_mandato_parlamentar
    UNIQUE (codigo_mandato, senador_id);

-- Versoes anteriores guardavam uma unica linha por cadeira. Preserva os exercicios
-- existentes criando o par parlamentar correspondente; a proxima carga atualiza os dados.
INSERT INTO mandatos (
    codigo_mandato, senador_id, uf, participacao, data_inicio, data_fim,
    timestamp_ingestao, atualizado_em
)
SELECT DISTINCT
    e.codigo_mandato, e.senador_id, m.uf, 'Exercício associado',
    m.data_inicio, m.data_fim, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM exercicios_mandato e
JOIN mandatos m ON m.codigo_mandato = e.codigo_mandato
LEFT JOIN mandatos alvo
    ON alvo.codigo_mandato = e.codigo_mandato AND alvo.senador_id = e.senador_id
WHERE alvo.id IS NULL;

ALTER TABLE exercicios_mandato ADD CONSTRAINT fk_exercicio_mandato_parlamentar
    FOREIGN KEY (codigo_mandato, senador_id)
    REFERENCES mandatos(codigo_mandato, senador_id)
    ON DELETE CASCADE;
