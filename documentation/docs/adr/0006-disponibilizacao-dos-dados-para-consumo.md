---
title: "0006: Disponibilização dos dados para consumo"
sidebar_label: "0006: Disponibilização dos dados"
sidebar_position: 6
---

# 0006: Disponibilização dos dados para consumo

- **Status:** proposto
- **Data:** 2026-11-25
- **Decisor:** Vilmar Fagundes, a validar com o squad
- **Entrega:** E4, disponibilização por consumo analítico e ETL reverso

## Contexto

Os marts respondem à pergunta central da E1, mas a E4 pede que o dado chegue a quem decide e
volte a um sistema em que alguém age. Esta ADR decide duas coisas:

1. **Leitura:** de onde o consumidor analítico lê as métricas.
2. **ETL reverso:** como a métrica chega ao sistema de destino, e o que acontece quando ele está
   fora do ar.

A ferramenta que guarda a definição das métricas pertence à frente da camada semântica. Aqui, toda
alternativa parte da mesma definição publicada pelo dbt.

### Carga

| Característica | Valor | Origem |
|---|---|---|
| Despesas carregadas | 21.430 em 2024; 111.837 na série 2020–2025 | [Carga](../metrics/workload.md) e [ADR 0005](./0005-granularidade-da-fato-e-indice-por-plano-de-execucao.md) |
| Grão entregue aos consumidores | Senador × mês: 974 linhas em 2024; 5.657 na série | [ADR 0004](./0004-modelagem-dimensional-com-dbt.md) e [ADR 0005](./0005-granularidade-da-fato-e-indice-por-plano-de-execucao.md) |
| Publicação | Uma por dia, às 06h | [Guia do Airflow](https://github.com/DaniloNavesS/inflow/blob/develop/orchestration/README.md) |
| SLA dos modelos | 26 horas | [Guia do Airflow](https://github.com/DaniloNavesS/inflow/blob/develop/orchestration/README.md) |
| Consulta de gestão | Até 2 s | [Carga](../metrics/workload.md) |
| Concorrência | Um escritor e poucos leitores | [Carga](../metrics/workload.md) |

### Consumidores

- **Analista de gestão:** explora o gasto e a comparação com os pares no [painel](../painel.mdx).
- **Sistema de destino:** recebe as competências em que o senador gastou acima da média dos pares,
  para que alguém as verifique. É a premissa desta medição, pois o destino ainda não foi
  confirmado pelo squad. Estar acima da média é um indicador aritmético, não indica irregularidade.

### Restrições

- Execução local em Docker Compose, por uma equipe pequena.
- O consumidor não pode depender do usuário dono do banco, usado hoje por todos os serviços.
- O destino pode estar fora do ar no momento da publicação.

## Alternativas consideradas

### Leitura

| | Alternativa | O que oferece | O que cobra |
|---|---|---|---|
| L0 | **Opção nula: CSV agendado** | Nenhum serviço novo; abre em qualquer ferramenta; o leitor não acessa o banco | Cópia defasada até a próxima exportação; perde os tipos; o arquivo entregue sai do controle de acesso do banco |
| L1 | **Warehouse:** consulta aos marts no PostgreSQL | Caminho atual do painel; dado publicado visível de imediato; controle de acesso do banco | Consumidor acoplado ao esquema e à disponibilidade do banco |
| L2 | **Federação:** DuckDB com o PostgreSQL anexado | Junta o banco a arquivos na mesma consulta, sem copiar | Mais um motor; continua dependendo do banco e transfere linhas a cada consulta |
| L3 | **Cópia em Parquet** | Preserva os tipos e é lida sem o banco | A mesma defasagem do CSV, e exige leitor de Parquet |

A [ADR 0003](./0003-consumo-analitico-duckdb-parquet-e-delta.md) comparou Parquet e Delta com o
PostgreSQL sobre o lançamento. Aqui o objeto é outro: a métrica pronta, no grão mensal.

### ETL reverso

| | Alternativa | O que oferece | O que cobra |
|---|---|---|---|
| R0 | **Opção nula: CSV agendado** | O arquivo espera o destino; sem credencial entre sistemas | O destino precisa detectar o arquivo novo, importá-lo e evitar duplicação |
| R1 | **Empurrar:** o pipeline grava no destino após publicar | Chega logo após a publicação; a falha aparece no Airflow | O pipeline guarda credencial do destino e precisa repetir quando ele cai |
| R2 | **Puxar:** o destino lê os marts em intervalos | O destino retoma quando volta; o pipeline não o conhece | O destino acessa o banco e depende do esquema; atraso de até um intervalo |

## Critérios de decisão

Definidos **antes da medição**, para que o resultado não escolha a régua. Uma alternativa só é
elegível se atender a todos os critérios que se aplicam a ela:

| Critério | Limite | Vale para |
|---|---|---|
| Mesma resposta | Zero linhas diferentes em relação ao mart | Leitura e ETL reverso |
| Latência da consulta | Mediana de até 2 s | Leitura |
| Defasagem | Até 26 horas após a publicação | Leitura e ETL reverso |
| Reenvio | Nenhuma linha duplicada ao repetir a mesma carga | ETL reverso |
| Destino fora do ar | Nenhuma linha perdida depois que ele volta, sem correção manual | ETL reverso |
| Privilégio mínimo | Funciona sem o usuário dono do banco | Leitura e ETL reverso |

Entre as elegíveis, escolhemos a **mais simples de operar**: menos serviços, credenciais e cópias
do dado. A velocidade além do limite não desempata, porque a carga não precisa dela.

## Medição

Ainda não realizada. As próximas etapas medem a leitura e o ETL reverso com a série 2020–2025 e
registram o script, o ambiente e os resultados.

## Decisão

Pendente da medição.
