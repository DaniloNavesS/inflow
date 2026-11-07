INSERT INTO oltp.senadores (id, nome, partido, uf) VALUES (1, 'Teste', 'TESTE', 'DF');
INSERT INTO oltp.fornecedores (id, cnpj_cpf, razao_social) VALUES (1, 'SEM_DOCUMENTO', 'Nome original');
INSERT INTO oltp.despesas (id, senador_id, fornecedor_id, ano, mes, data_despesa, tipo_despesa, valor) VALUES
(1, 1, 1, 2024, 1, '2024-01-10', 'Passagens', 100.10),
(2, 1, 1, 2024, 2, '2024-02-10', 'Escritório', 100.10),
(3, 1, 1, 2024, 2, '0202-07-04', 'Outros', 0.00);
