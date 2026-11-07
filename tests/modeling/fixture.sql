INSERT INTO oltp.senadores (id, nome, partido, uf) VALUES (1, 'Teste', 'TESTE', 'DF'), (2, 'Teste zero', 'TESTE', 'SP');
INSERT INTO oltp.fornecedores (id, cnpj_cpf, razao_social) VALUES (1, 'SEM_DOCUMENTO', 'Nome original');
INSERT INTO oltp.despesas (id, senador_id, fornecedor_id, ano, mes, data_despesa, tipo_despesa, valor) VALUES
(1, 1, 1, 2024, 1, '2024-01-10', 'Passagens', 100.10),
(2, 1, 1, 2024, 2, '2024-02-10', 'Escritório', 100.10),
(3, 1, 1, 2024, 2, '0202-07-04', 'Outros', 0.00);
INSERT INTO oltp.despesas (id, senador_id, fornecedor_id, ano, mes, data_despesa, tipo_despesa, valor)
VALUES (4, 2, 1, 2024, 1, '2024-01-01', 'Outros', 0);
INSERT INTO oltp.comissoes (id, sigla, nome) VALUES (1, 'TESTE', 'Comissão de teste'), (2, 'INC', 'Vigência incompleta');
INSERT INTO oltp.participacoes_comissao (senador_id, comissao_id, cargo, data_inicio, data_fim) VALUES
(1, 1, 'Titular', '2024-01-01', '2024-12-31'),
(1, 1, 'Presidente', '2024-01-01', '2024-12-31'),
(1, 2, 'Membro', NULL, NULL),
(1, 2, 'Suplente', '2025-01-01', NULL);
INSERT INTO oltp.estrutura_gabinete (senador_id, ano, qtd_pessoal_gabinete, qtd_pessoal_escritorio)
VALUES (1, 2024, 3, 2), (1, 2025, 4, 2);
