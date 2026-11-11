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
INSERT INTO oltp.sessao_plenaria (id, numero, data_sessao, tipo) VALUES
(1, 1, '2023-10-10', 'Deliberativa'), (2, 2, '2023-10-17', 'Deliberativa'),
(3, 3, '2023-10-24', 'Deliberativa'), (4, 4, '2023-10-25', 'Deliberativa');
INSERT INTO oltp.documento_dsf (id, sessao_id, codigo_diario, numero_diario, data_publicacao, url_documento, pagina_inicial, pagina_final, sha256, status_parser) VALUES
(1, 1, 1, 1, '2023-10-11', 'https://example.org/dsf/1', 1, 2, repeat('a',64), 'SUCESSO'),
(2, 2, 2, 2, '2023-10-18', 'https://example.org/dsf/2', 1, 2, repeat('b',64), 'PARCIAL'),
(3, 3, 3, 3, '2023-10-25', 'https://example.org/dsf/3', 1, 2, repeat('c',64), 'FALHA'),
(4, 1, 4, 4, '2023-10-11', 'https://example.org/dsf/4', 1, 2, repeat('d',64), 'SUCESSO'),
(5, 4, 5, 5, '2023-10-26', 'https://example.org/dsf/5', 1, 2, repeat('e',64), 'FALHA');
INSERT INTO oltp.registro_presenca (id, sessao_id, documento_dsf_id, senador_id, nome_documento, partido_documento, uf_documento, situacao, voto_registrado, pagina, resolucao) VALUES
(1, 1, 1, 1, 'Teste', 'ANTIGO', 'DF', 'PRESENTE', false, 1, 'EXATA'),
(2, 1, 4, 1, 'Teste', 'ANTIGO', 'DF', 'PRESENTE', true, 1, 'EXATA'),
(3, 2, 2, 1, 'Teste', 'ANTIGO', 'DF', 'PRESENTE', true, 1, 'EXATA'),
(4, 1, 1, NULL, 'Não identificado', 'ANTIGO', 'DF', 'PRESENTE', NULL, 1, 'NAO_RESOLVIDA'),
(5, 3, 3, 2, 'Teste zero', 'TESTE', 'SP', 'PRESENTE', true, 1, 'EXATA'),
(6, 1, 1, 2, 'Teste zero', 'TESTE', 'SP', 'DESCONHECIDO', NULL, 1, 'EXATA'),
(7, 3, 1, 1, 'Sessão inconsistente', 'ANTIGO', 'DF', 'PRESENTE', true, 1, 'EXATA'),
(8, 2, 2, NULL, 'Identificação ambígua', NULL, NULL, 'PRESENTE', NULL, 1, 'AMBIGUA');
INSERT INTO oltp.senadores (id,nome,partido,uf) VALUES (3,'Sem contexto histórico','ATUAL','DF');
INSERT INTO oltp.despesas (id,senador_id,fornecedor_id,ano,mes,data_despesa,tipo_despesa,valor)
VALUES (5,3,1,2024,1,'2024-01-01','Outros',900);
