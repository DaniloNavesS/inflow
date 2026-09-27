# Caracterização da carga de trabalho

Passo 1 do Método de Decisão. Todos os números vêm de uma execução real, reproduzível com:

```bash
docker compose down -v
docker compose up --build        # migrações + carga completa
docker exec inflow_postgres psql -U inflow_user -d inflow_db -c "ANALYZE;"
```

Ambiente medido: PostgreSQL 15-alpine, `INGESTION_YEAR=2024`, medição de 26/09/2026.

## Volume

| Tabela | Linhas | Tamanho total | Crescimento esperado |
|---|---:|---:|---|
| `despesas` | 21.430 | 13 MB | +1 ano de CEAPS ≈ +21 mil linhas |
| `participacoes_comissao` | 7.189 | 1.384 kB | estável por legislatura |
| `fornecedores` | 3.516 | 944 kB | ~3,5 mil novos por ano, com sobreposição |
| `registro_presenca` | 220 | a medir | prova mínima em 3 sessões deliberativas do DSF |
| `comissoes` | 425 | 136 kB | dezenas por legislatura |
| `sessao_plenaria` | 3 | a medir | ~100 sessões deliberativas por ano |
| `senadores` | 96 | 120 kB | +1/3 do Senado a cada 4 anos |
| `estrutura_gabinete` | 81 | 40 kB | 81 linhas por ano |

Total: ~34 mil linhas e ~16 MB para um único ano fiscal.

Volume da fonte por ano, contado direto na API do CEAPS:

| Ano | Lançamentos |
|---|---:|
| 2020 | 14.088 |
| 2021 | 16.827 |
| 2022 | 16.804 |
| 2023 | 18.822 |
| 2024 | 21.430 |
| 2025 | 23.800 |

Crescimento de ~11% ao ano. Carregar a série 2020–2025 leva `despesas` a ~112 mil linhas
(~70 MB), sem mudar o esquema: basta repetir a carga variando `INGESTION_YEAR`.

## Taxa de escrita e de leitura

- **Escrita:** em lote, não transacional-online. Uma carga completa do zero grava ~34 mil linhas
  em **90,6 s** (~375 linhas/s), em 8 lotes de `execute_batch`/`execute_values`. A origem publica
  o CEAPS mensalmente, então a frequência útil é **1 execução por dia no pior caso**, e o lote
  reprocessa o ano inteiro.
- **Leitura:** dominante. A carga é escrita rara e concentrada; as consultas de gestão são o
  uso contínuo do banco. Razão esperada em operação: **leitura >> escrita**, com a escrita confinada
  a uma janela de ~2 minutos por dia.
- **Concorrência:** baixa. Um ingestor escritor e poucos leitores analíticos. Não há usuário final
  transacionando contra este banco.

## Cardinalidade

Medida sobre `despesas` (21.430 linhas):

| Coluna | Valores distintos |
|---|---:|
| `senador_id` | 88 |
| `fornecedor_id` | 3.516 |
| `tipo_despesa` | 8 |
| `data_despesa` | 469 |

Cardinalidade baixa nas colunas de filtro (88 senadores, 8 tipos) e alta em `fornecedor_id`.
Isso justifica índices B-Tree compostos começando pela coluna seletiva — `(senador_id, data_despesa)`
— em vez de índices isolados por coluna de baixa cardinalidade.

Faixa de valores: R$ 1.506,78 de média, R$ 242.400,00 de máximo, R$ 32.290.271,35 de total em 2024.

## Padrão de acesso

Três formas de consulta, com a latência real medida por `EXPLAIN (ANALYZE, BUFFERS)`:

| Consulta | Índice usado | Tempo de execução |
|---|---|---:|
| Recorte por senador e período | `idx_despesas_senador_data` | **0,198 ms** |
| Agregação senador × tipo de despesa no ano | varredura + hash agg | **12,0 ms** |
| Junção despesa → fornecedor | `fornecedores_pkey` | incluída acima |

O padrão é **analítico sobre volume pequeno**: agregação com `GROUP BY` e `ORDER BY` sobre a tabela
inteira do ano, não busca por chave primária. Os 4 índices de `despesas` cobrem os recortes por
senador, por fornecedor, por tipo e por ano/mês.

Escrita acessa o banco por chave natural: `ON CONFLICT` na PK em todas as tabelas — 42.860 varreduras
de `despesas_pkey` durante a carga (duas por linha, uma de verificação e uma de gravação).

## Latência tolerada

- **Consulta de gestão:** até **2 s**. O consumidor é um analista explorando dados, não uma API.
  A folga sobre os 12 ms medidos é de três ordens de magnitude.
- **Carga:** até **10 min**. Roda em lote, fora de horário de uso; os 90 s atuais ficam bem abaixo.
- **Frescor do dado:** até **1 mês**. A origem publica o CEAPS mensalmente — não há como estar mais
  fresco que a fonte, e não faz sentido buscar tempo real.

## Sazonalidade

- **Recesso parlamentar** (23/12 a 1/2 e 18 a 31/7): sem sessões deliberativas, logo `sessoes` e
  `sessoes_presenca` não crescem nesses períodos, mas `despesas` continua — passagens e aluguel de
  escritório não param.
- **Fechamento mensal do CEAPS:** o volume de lançamentos se concentra nos dias seguintes à
  publicação mensal da origem; é quando a carga tem mais linhas novas para gravar.
- **Fim de exercício:** dezembro concentra prestação de contas e correções retroativas de
  lançamentos anteriores — o momento em que a sobrescrita descrita na
  [ADR 0001](adr/0001-modelagem-do-sistema-de-origem.md) mais destrói informação.
- **Início de legislatura** (a cada 4 anos): troca de 1/3 dos senadores, recomposição de todas as
  comissões — pico de escrita em `senadores`, `comissoes` e `participacoes_comissao`.

## Qualidade do dado na origem

Constatado nesta medição, e relevante para as transformações posteriores:

- **4 lançamentos com data anterior a 2000** (o menor é `0202-07-04`): erro de digitação na fonte.
  Preservados como estão no espelho transacional.
- Senadores históricos são carregados pela lista da 57ª Legislatura; partido e UF desconhecidos
  permanecem nulos, sem preenchimentos artificiais.
- Fornecedores sem documento recebem identidade por nome normalizado mais lançamento. A estratégia
  evita colapsar pessoas distintas e sacrifica deduplicação automática onde a origem não sustenta isso.
