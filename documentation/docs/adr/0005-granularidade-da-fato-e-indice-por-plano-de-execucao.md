---
title: "0005: Granularidade da fato de despesas e índice decididos por plano de execução"
sidebar_label: "0005: Granularidade e índice da fato"
sidebar_position: 5
---

# 0005: Granularidade da fato de despesas e índice decididos por plano de execução

- **Status:** proposto
- **Data:** 2026-11-08
- **Decisor:** Vilmar Fagundes, frente de otimização
- **Entrega:** E3, consulta otimizada a partir do plano de execução e decisão de granularidade

## Contexto

A [ADR 0004](./0004-modelagem-dimensional-com-dbt.md) publicou as despesas em granularidades
complementares e deixou para a frente de otimização a comparação de custo e a consulta com
planos antes/depois. A E3 pergunta em que granularidade o fato vive: fina demais explode o
volume, grossa demais impede a pergunta. Esta ADR mede as duas e registra a otimização.

As granularidades publicadas pelo dbt em `analytics_marts` são:

| Modelo | Uma linha representa |
|---|---|
| `fct_despesas` | Um lançamento CEAPS (detalhada) |
| `agg_despesas_mensais_fornecedor_categoria` | Senador × competência × fornecedor × categoria |
| `agg_despesas_mensais` | Senador × competência × categoria |
| `fct_despesas_mensais` | Senador × competência (mensal) |

As medições usam a série **2020–2025**, carregada como descrito em
[Como executar](../como-executar.mdx#reexecutar-e-ampliar-o-recorte): **111.837 despesas**.
O volume ultrapassa o gatilho de **100 mil despesas** da ADR 0004 e corresponde ao crescimento
previsto na [caracterização da carga](../metrics/workload.md#volume). A tolerância de consulta
de gestão é de **2 segundos**. Todos os tempos medidos ficam abaixo de 100 ms, portanto esta
decisão não corrige uma violação atual: trata de como o custo cresce com a série histórica.

Antes desta ADR, nenhum mart tinha índice. A materialização `table` do dbt recria a tabela a
cada `dbt build` com `CREATE TABLE AS`; um índice criado à mão desaparece na execução seguinte.

## Alternativas consideradas

### A. Opção nula: manter os marts sem índice

Funciona hoje e não custa nada a mais na publicação. Toda consulta sobre `fct_despesas`
percorre a tabela inteira, e o custo de uma consulta seletiva cresce com a série histórica,
não com o tamanho da resposta.

### B. Fato apenas mensal

Responde às consultas amplas com uma fração das páginas, mas perde `fornecedor_id`,
`data_despesa` e o lançamento individual. Não responde quais fornecedores receberam de um
senador, gastos por data ou a auditoria de uma nota, e impede a reconciliação com a origem.

### C. Fato detalhada com índice de cobertura e agregados mensais derivados

Mantém o lançamento como fonte da verdade, resolve a consulta seletiva com um índice declarado
no dbt e entrega as consultas amplas pelos agregados já publicados na ADR 0004.

### D. Índices também nos agregados mensais

Foi medido com um índice criado numa transação desfeita. Reduz a Q1 sobre a agregação por
categoria de 270 para 4 buffers, porém essa consulta já é atendida pela fato detalhada indexada.

## Medição e evidências

O script `scripts/adr/0005_planos_execucao.sh` executa cada cenário **7 vezes após uma leitura
de aquecimento**, com cache aquecido, e registra a mediana, a faixa e os buffers do nó raiz.
Antes de medir, aplica `VACUUM ANALYZE` aos marts. O cenário sem índice desliga o uso de índices
apenas na sessão. Ambiente: PostgreSQL 15.19 em Docker, notebook Windows, 2026-11-09T02:30Z.

Os buffers se repetiram exatamente em três execuções completas do script; os tempos variaram
entre execuções por ruído da máquina. As conclusões se apoiam nos buffers, e os tempos indicam
a ordem de grandeza.

Antes de comparar custos, o script confere que as granularidades devolvem **exatamente o mesmo
resultado** para cada pergunta, com `EXCEPT ALL`. As três comparações têm zero linhas diferentes.

### Consultas

- **Q1, seletiva:** gasto mensal por categoria do senador 581 em 2025 (771 lançamentos, 54 linhas).
- **Q2, ampla:** média mensal por senador e ano, como no modelo `gestao_media_mensal` (539 linhas).
- **Q3, ampla:** total mensal por senador em 2024, base da pergunta central (974 linhas).

| Consulta | Granularidade | Acesso | Buffers | Mediana |
|---|---|---|---:|---:|
| Q1 | Detalhada, sem índice | Seq Scan | 3.029 | 11,8 ms |
| Q1 | **Detalhada, com índice** | **Index Only Scan** | **10** | **0,66 ms** |
| Q1 | Mensal por categoria, sem índice | Seq Scan | 270 | 1,2 ms |
| Q1 | Mensal por categoria, índice transitório | Index Only Scan | 4 | 0,19 ms |
| Q2 | Detalhada | Seq Scan | 3.029 | 63,1 ms |
| Q2 | Mensal por categoria | Seq Scan | 270 | 14,9 ms |
| Q2 | **Mensal** | Seq Scan | **98** | **2,9 ms** |
| Q3 | Detalhada | Seq Scan | 3.029 | 24,6 ms |
| Q3 | Mensal por categoria | Seq Scan | 270 | 5,1 ms |
| Q3 | **Mensal** | Seq Scan | **98** | **0,89 ms** |

Na Q1, o índice na detalhada reduz as páginas lidas **303 vezes** e o tempo cerca de 18 vezes;
trocar de granularidade sem índice reduz as páginas 11 vezes. Com índice, a diferença entre
detalhada e agregada deixa de ser relevante. Nas consultas amplas, o índice não ajuda (o
planejador mantém Seq Scan) e o ganho vem de agregar menos linhas: a fato mensal lê **31 vezes
menos páginas** e é cerca de 20 a 30 vezes mais rápida. O índice também não atende a Q3, que
filtra só por `ano`, porque a chave começa por `senador_id`.

### Volume

A Q1 foi repetida em cópias temporárias da fato com 1, 3 e 6 anos, cada uma com o mesmo índice.

| Anos | Linhas | Sem índice | Com índice |
|---:|---:|---|---|
| 1 | 23.866 | 634 buffers, 2,3 ms | 11 buffers, 0,63 ms |
| 3 | 64.118 | 1.730 buffers, 4,9 ms | 10 buffers, 0,59 ms |
| 6 | 111.837 | 3.029 buffers, 10,0 ms | 10 buffers, 0,54 ms |

Sem índice, as páginas crescem na proporção da tabela. Com índice, ficam constantes, porque
dependem só das linhas da resposta. Os tempos absolutos desta seção usam tabelas temporárias
e não se comparam diretamente aos da tabela anterior; a comparação válida é entre linhas.

### Armazenamento e publicação

| Modelo | Linhas | Tabela | Índice | Publicação (mediana de 3) |
|---|---:|---:|---:|---:|
| `fct_despesas` | 111.837 | 24 MB | 7,3 MB | 304 ms + 141 ms do índice |
| `agg_despesas_mensais_fornecedor_categoria` | 71.431 | 7,5 MB | — | não medido |
| `agg_despesas_mensais` | 21.828 | 2,1 MB | — | 106 ms |
| `fct_despesas_mensais` | 5.657 | 824 kB | — | 19 ms, sem a junção de contexto |

O índice aumenta em cerca de 30% o espaço da fato e em cerca de 46% o tempo de criá-la.
Os agregados são derivados da fato, portanto somam custo à publicação em vez de substituí-la.

### Estatísticas após a publicação

Logo após um `dbt build`, a fato recriada não tinha estatísticas: o planejador estimou
**3 linhas** onde havia 771. Também não tinha mapa de visibilidade, e a consulta usou Bitmap Heap
Scan em vez de Index Only Scan. Com `analyze {{ this }}` no `post_hook`, a estimativa passou a
699 linhas na primeira execução após o build. `VACUUM` não pode ser executado no hook, porque
o dbt o roda dentro de uma transação; o mapa de visibilidade fica a cargo do autovacuum.

Planos completos, inclusive o original antes do índice: [resumo](/data/adr-0005/resumo.txt),
[antes](/data/adr-0005/planos/Q1_original_antes_do_indice.txt),
[depois](/data/adr-0005/planos/Q1_depois_detalhada_com_indice.txt),
[logo após o build sem estatísticas](/data/adr-0005/planos/Q1_logo_apos_build_sem_analyze.txt) e
[com estatísticas](/data/adr-0005/planos/Q1_logo_apos_build_com_analyze.txt). A análise
detalhada está em [Otimização de consultas](../otimizacao-consultas.mdx).

## Decisão

Adotamos a alternativa **C**.

- **O fato vive na granularidade do lançamento** (`fct_despesas`). É a única que responde a
  todas as perguntas, inclusive por fornecedor e data, e a base da reconciliação dos agregados.
- **Consultas amplas por senador e mês usam `fct_despesas_mensais`**, e as que precisam de
  categoria usam `agg_despesas_mensais`. Esses modelos continuam derivados da fato.
- **A consulta seletiva por senador e ano usa o índice** `(senador_id, ano, mes, categoria_id, valor)`
  em `fct_despesas`, declarado no `config` do modelo. A ordem da chave segue os filtros de
  igualdade, depois a ordem do `GROUP BY`; `valor` completa a cobertura. A dbt-postgres 1.9.1
  não oferece `INCLUDE`, por isso `valor` entra como última coluna da chave.
- **`fct_despesas` executa `analyze {{ this }}` após cada publicação.**
- **Os agregados mensais ficam sem índice** enquanto suas consultas lerem menos de 300 páginas.

## Consequências

**O que ganhamos:** a consulta do painel por senador passa a ler 10 páginas em vez da tabela
inteira, e esse custo não cresce com novos anos. A decisão de granularidade passa a se apoiar
em medição equivalente das quatro representações, com respostas conferidas.

**O que perdemos:** 7,3 MB de índice e cerca de 0,15 s a mais em cada publicação. Cada mudança
na consulta precisa ser conferida contra a ordem da chave: um filtro só por ano ou por
fornecedor não usa este índice. O Index Only Scan depende do autovacuum após cada publicação;
até lá, o plano usa Bitmap Heap Scan, ainda muito abaixo do custo sem índice.

**O que custa reverter:** baixo. Retirar o `config` do modelo remove o índice no próximo build,
sem efeito sobre dados ou consumidores. Os resultados das consultas não mudam.

## Gatilho de revisão

- Uma consulta de gestão sobre os marts ultrapassar **2 segundos em três medições**.
- Uma consulta seletiva sobre um agregado ultrapassar **300 páginas** lidas: indexar o agregado.
- O painel filtrar a fato por outra combinação, como fornecedor ou só período: medir um índice
  próprio em vez de reordenar este.
- A publicação passar a ser incremental: rever o `post_hook`, porque o `ANALYZE` integral
  deixaria de ser proporcional à alteração.

## Evidências no repositório

- [Modelo `fct_despesas` com índice e `post_hook`](https://github.com/DaniloNavesS/inflow/blob/develop/analytics/dbt/models/marts/fct_despesas.sql).
- Script de medição: `scripts/adr/0005_planos_execucao.sh`.
- Planos e resumo versionados em `documentation/static/data/adr-0005/`.
- [Otimização de consultas](../otimizacao-consultas.mdx).
