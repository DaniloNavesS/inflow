# 0001 — Adotar PostgreSQL como SGBD relacional do Mandato Aberto

- **Status:** aceito
- **Data:** 2026-09-28
- **Decisores:** equipe do projeto Mandato Aberto

## Contexto

O Mandato Aberto necessita de um Sistema Gerenciador de Banco de Dados relacional para armazenar e consultar os dados estruturados processados pelo pipeline de Engenharia de Dados.

O workload atual inclui dados de senadores, comissões, sessões, despesas e pessoal. Na escala utilizada no benchmark, foram processados:

- 81 registros de senadores;
- 7.614 registros de comissões;
- 2.430 registros de sessões;
- 24.946 registros de despesas;
- 81 registros de pessoal.

Além da carga inicial, o pipeline deve permitir reprocessamentos idempotentes dos dados, utilizando operações de inserção e atualização sem gerar duplicidades.

O banco também será utilizado para consultas analíticas, incluindo agregações de despesas por senador e categoria, consultas por senador e período e agregações por fornecedor.

Os principais critérios considerados para a decisão foram:

- desempenho de carga;
- desempenho de reprocessamento;
- latência de consultas analíticas;
- desempenho de consultas indexadas;
- armazenamento ocupado;
- suporte a operações relacionais e agregações;
- adequação ao workload analítico do projeto.

## Alternativas consideradas

### A. PostgreSQL

SGBD relacional open source com suporte a transações ACID, índices, agregações, funções analíticas e recursos avançados de SQL.

Nos testes realizados, apresentou menor latência em todas as consultas medidas, incluindo agregações e consultas indexadas.

Como desvantagem, apresentou menor desempenho que o MariaDB durante o reprocessamento idempotente e ocupou mais espaço para a tabela de despesas no cenário testado.

### B. MariaDB

SGBD relacional open source compatível com grande parte do ecossistema MySQL.

Nos testes realizados, apresentou melhor desempenho nas operações de reprocessamento e em parte das cargas iniciais. Também apresentou menor utilização de armazenamento.

Como desvantagem, apresentou maior latência em todas as consultas analíticas avaliadas, com diferença especialmente significativa na consulta indexada por senador e período.

## Medição

benchmark disponível na branch `benchmark` do repositório.

O benchmark foi executado em `2026-09-28T13:52:50Z`, utilizando escala `1x` e lotes de `500` registros.

Foram utilizados:

- PostgreSQL `15.17`;
- MariaDB `11.4.13`;
- mesmo conjunto de dados;
- mesmas cardinalidades;
- mesmo ambiente de execução.

A medição reproduziu os upserts e consultas relacionais utilizados pelos jobs do pipeline.

Foram excluídos do teste:

- chamadas HTTP;
- parsing de JSON;
- parsing de PDF;
- períodos de espera;
- escrita da camada Bronze.

Portanto, os resultados representam o desempenho do SGBD e de seu respectivo driver, e não o tempo total do pipeline.

Os resultados são locais e não devem ser generalizados para outros ambientes sem repetição do benchmark.

### Carga inicial

| Job | PostgreSQL | MariaDB |
|---|---:|---:|
| senators | 0,009 s | 0,021 s |
| committees | 0,508 s | 0,748 s |
| sessions | 0,145 s | 0,210 s |
| expenses | 2,020 s | 1,380 s |
| staff | 0,014 s | 0,010 s |

O PostgreSQL foi mais rápido nas cargas de senadores, comissões e sessões. O MariaDB apresentou melhor desempenho nas cargas de despesas e pessoal.

Na carga de despesas, que representa o maior conjunto do benchmark, o MariaDB executou a operação aproximadamente **31,7% mais rápido**.

### Reprocessamento idempotente

| Job | PostgreSQL | MariaDB |
|---|---:|---:|
| senators | 0,012 s | 0,010 s |
| committees | 0,335 s | 0,143 s |
| sessions | 0,117 s | 0,048 s |
| expenses | 1,507 s | 0,500 s |
| staff | 0,013 s | 0,002 s |

O MariaDB apresentou menor tempo em todos os testes de reprocessamento.

Para o conjunto de despesas, o MariaDB realizou o reprocessamento em `0,500 s`, enquanto o PostgreSQL levou `1,507 s`, representando redução de aproximadamente **66,8% no tempo de execução**.

### Consultas com cache quente

| Consulta | PostgreSQL p50 | MariaDB p50 | PostgreSQL p95 | MariaDB p95 |
|---|---:|---:|---:|---:|
| aggregate_senator_type | 15,073 ms | 17,410 ms | 15,516 ms | 17,658 ms |
| indexed_senator_period | 0,616 ms | 1,944 ms | 0,745 ms | 2,135 ms |
| supplier_totals | 8,371 ms | 10,581 ms | 8,618 ms | 10,741 ms |

O PostgreSQL apresentou menor latência em todas as consultas avaliadas.

Na mediana (`p50`):

- `aggregate_senator_type`: aproximadamente **13,4% menor latência**;
- `indexed_senator_period`: aproximadamente **68,3% menor latência**;
- `supplier_totals`: aproximadamente **20,9% menor latência**.

A maior diferença ocorreu na consulta indexada por senador e período. O MariaDB apresentou p50 de `1,944 ms`, enquanto o PostgreSQL apresentou `0,616 ms`. Nesse cenário, a consulta no PostgreSQL foi aproximadamente **3,16 vezes mais rápida**.

### Armazenamento

| Banco | Tamanho da tabela `despesas` |
|---|---:|
| PostgreSQL | 10.125.312 bytes |
| MariaDB | 7.946.240 bytes |

O MariaDB utilizou aproximadamente **21,5% menos espaço** para a tabela avaliada.

## Decisão

Adotamos o **PostgreSQL** como SGBD relacional do Mandato Aberto.

Embora o MariaDB tenha apresentado melhor desempenho nas operações de reprocessamento e menor utilização de armazenamento, o PostgreSQL apresentou menor latência em todas as consultas analíticas avaliadas.

A decisão prioriza o desempenho de leitura e consulta, pois o banco será utilizado principalmente como camada estruturada para análises sobre os dados processados pelo pipeline.

A diferença observada nas operações de escrita não representa, no cenário atual, uma limitação operacional relevante. A maior carga testada possui 24.946 registros e foi processada por ambos os bancos em poucos segundos.

Em contrapartida, as consultas constituem operações recorrentes sobre os dados persistidos. O PostgreSQL apresentou vantagem especialmente relevante em consultas indexadas, com p50 de `0,616 ms`, contra `1,944 ms` do MariaDB.

Portanto, considerando o workload atual e o perfil predominantemente analítico do Mandato Aberto, o desempenho superior de leitura e agregação recebeu maior peso na decisão do que a vantagem do MariaDB em carga e reprocessamento.

## Consequências

**O que ganhamos:**

- menor latência nas consultas avaliadas;
- melhor desempenho nas consultas indexadas do benchmark;
- melhor desempenho nas agregações utilizadas pelo projeto;
- SGBD adequado ao perfil analítico do Mandato Aberto;
- suporte amplo a SQL, agregações, índices e recursos analíticos;
- manutenção de uma arquitetura baseada em tecnologia open source.

**O que perdemos:**

- reprocessamentos mais lentos em comparação ao MariaDB no benchmark atual;
- maior utilização de armazenamento;
- menor throughput em determinadas operações de escrita.

No cenário de despesas, por exemplo, o reprocessamento levou `1,507 s` no PostgreSQL e `0,500 s` no MariaDB.

A tabela de despesas também ocupou aproximadamente `10,1 MB` no PostgreSQL contra `7,9 MB` no MariaDB.

Essas diferenças foram consideradas aceitáveis porque o volume atual é pequeno e os tempos absolutos permanecem baixos.

**O que se torna irreversível:**

A decisão não é estritamente irreversível, pois ambos os bancos utilizam modelos relacionais e SQL.

Entretanto, à medida que o projeto evoluir, podem ser utilizados recursos específicos do PostgreSQL, como tipos de dados, funções, índices, sintaxe de upsert e funcionalidades analíticas próprias do SGBD.

Nesse cenário, uma migração futura para MariaDB exigiria:

- revisão do esquema;
- revisão das consultas SQL;
- adaptação dos scripts de carga;
- adequação das operações de upsert;
- testes de integridade;
- repetição dos testes de desempenho;
- migração e validação dos dados existentes.

Portanto, o custo de substituição tende a aumentar conforme o projeto passa a depender de funcionalidades específicas do PostgreSQL.

## Gatilho de revisão

Esta decisão deverá ser revisada caso ocorram mudanças significativas no workload do Mandato Aberto.

A avaliação deverá ser repetida caso:

- o volume de dados cresça em uma ordem de magnitude em relação ao benchmark atual;
- operações de escrita ou reprocessamento passem a representar o principal gargalo do pipeline;
- o tempo de reprocessamento deixe de atender ao SLA definido para o projeto;
- o armazenamento utilizado pelo PostgreSQL passe a representar uma restrição relevante de infraestrutura;
- o padrão de consultas do sistema seja significativamente alterado;
- seja adotada uma infraestrutura diferente da utilizada neste benchmark.

Como referência inicial, um novo benchmark deverá ser considerado quando o conjunto de despesas atingir aproximadamente **250 mil registros**, dez vezes o volume avaliado nesta decisão.

A continuidade do PostgreSQL deverá ser reavaliada com base nos mesmos critérios utilizados neste ADR, preservando a comparação entre carga, reprocessamento, consultas e utilização de armazenamento.
