---
title: "0004: Modelagem dimensional no PostgreSQL com dbt"
sidebar_label: "0004: Modelagem dimensional com dbt"
sidebar_position: 4
---

# 0004: Modelagem dimensional no PostgreSQL com dbt

- **Status:** aceito na implementação integrada pelo PR #35
- **Data:** 2026-11-08
- **Decisores:** Ana Luiza e Danilo Naves, frente de modelagem e transformações
- **Entrega:** E3, camada analítica transformada, testada e orquestrada

## Contexto

A pergunta central da E1 pede os gastos mensais de CEAPS de 2024 por senador, categoria
e fornecedor, com comparação entre parlamentares do mesmo partido e da mesma UF.
O projeto já possui PostgreSQL, ingestão em lote, Bronze e exportações Parquet/Delta.
Precisamos transformar essa base em modelos de consumo com regras explícitas e histórico,
sem reconstruir a plataforma nem confundir cadastro atual com situação parlamentar passada.

A carga validada contém **21.430 despesas**, com **R$ 32.290.271,35**. São quatro datas
fiscais fora da faixa válida; por isso a competência é o `ano`/`mes` publicado no CEAPS,
não uma derivação de `data_despesa`. Partido e UF no cadastro de senadores representam
o retrato coletado, insuficiente para classificar automaticamente os gastos de 2024.

As restrições são execução local em Docker Compose, equipe pequena, poucos leitores e
atualização em lote. A caracterização da carga admite consultas de até **2 segundos**
e carga de até **10 minutos**. Esses valores são referências de projeto; esta ADR não
os transforma em um SLA já monitorado.

A [ADR 0003](./0003-consumo-analitico-duckdb-parquet-e-delta.md) mantém as decisões do lake.
Esta decisão trata da transformação e dos modelos dimensionais, sem substituir o lake
ou declarar consumo dos eventos Kafka pelo dbt.

## Alternativas consideradas

### A. Opção nula: consultas SQL diretamente sobre o OLTP

O PostgreSQL já atende ao volume atual. Manter consultas e scripts SQL avulsos evita uma
nova ferramenta e outra cópia, mas deixa dependências, testes e contratos de consumo
espalhados. As junções e as regras de competência e classificação histórica precisariam
ser repetidas por quem constrói o painel. É uma alternativa viável em desempenho; não
foi descartada por suposta incapacidade do banco.

### B. Uma tabela larga de despesas enriquecidas

O Parquet `despesas_enriquecidas` já demonstra esse formato no projeto. Uma linha por
lançamento simplifica leituras, mas repete atributos de senador e fornecedor e não
substitui uma dimensão histórica. O enriquecimento existente usa cadastro parlamentar
atual e retrato empresarial recente, não a vigência na competência CEAPS. Usá-lo como
resposta histórica exigiria novas regras, sem resolver sozinho os grãos institucionais.

### C. Modelo dimensional com fatos detalhados e agregações mensais, em dbt

Separa identidade, histórico e medidas; mantém a despesa auditável por ID e oferece
agregados com granularidade declarada. O dbt expressa dependências por `ref`, executa os
testes no grafo e gera catálogo e linhagem. Os marts permanecem no PostgreSQL, que já
está disponível ao painel e à frente de otimização. O custo é manter materializações,
uma ferramenta adicional e regras de consumo para evitar junções entre fatos incompatíveis.

### D. Modelo dimensional em SQLMesh

É outro caminho declarativo admitido na E3. Exigiria configurar o projeto, seu fluxo de
execução e testes. Não fizemos um comparativo de desempenho ou operação entre SQLMesh e
dbt; portanto, a escolha por dbt não afirma superioridade medida sobre SQLMesh. Nesta
etapa, mantemos o caminho já implementado, versionado e validado com o banco do projeto.

## Medição e evidências

A evidência é funcional e de granularidade sobre a base real, não um benchmark entre
ferramentas. Os testes sintéticos isolam regras e falhas; não são usados para afirmar
velocidade ou escala em produção.

| Representação validada | Linhas | O que uma linha representa |
|---|---:|---|
| `fct_despesas` | 21.430 | Um lançamento CEAPS, com o ID original |
| `agg_despesas_mensais_fornecedor_categoria` | 13.404 | Senador × competência × fornecedor × categoria |
| `agg_despesas_mensais` | 3.889 | Senador × competência × categoria |
| `fct_despesas_mensais` | 974 | Senador × competência com lançamentos |
| `dim_fornecedor_historico` | 3.516 | Uma versão observada de fornecedor, na primeira carga |
| `dim_contexto_parlamentar_mensal` | 1.056 | Senador × mês de 2024, incluindo meses sem exercício |

Os agregados preservam **R$ 32.290.271,35** e reconciliam os **21.430 lançamentos**.
O mensal por senador possui cerca de **22 vezes menos linhas** que a fato detalhada,
mas perde o detalhamento de fornecedores e categorias. A redução é de cardinalidade;
não implica uma redução equivalente de latência ou armazenamento. A comparação de custo
e a consulta com planos antes/depois permanecem na frente de otimização.

A publicação passou por **60 testes dbt** na base real e no PostgreSQL descartável.
Sete testes Python verificam o contexto temporal e sua gravação. Os cenários incluem
reexecução sem mudança, correção e exclusão de fornecedor, data fiscal inválida, empate,
parser parcial, troca de partido, média zero e ausência de pares. A aprovação desses
testes não substitui os testes adicionais de volume e distribuição da frente de qualidade.

Na comparação real, **938 competências** são comparáveis por partido e **970 por UF**.
No partido, outras 5 têm múltiplas filiações no mês, 27 não têm outros pares e 4 não têm
exercício confirmado. Por UF, 4 ficam sem exercício confirmado. Nenhum desses estados
remove valores da fato.

Para reproduzir a validação:

```bash
# Requer a origem carregada, conforme o README.
make models
make test-models
make models-docs

# Comparação, composição dos gastos e auditoria dos estados de contexto.
docker compose exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' \
  < scripts/sql/analytics/001_pergunta_central.sql
```

As contagens podem ser conferidas com `SELECT count(*)` nos modelos da tabela acima;
os totais, com `sum(valor)` na fato ou `sum(valor_total)` nos agregados. Os arquivos
`analytics/dbt/target/run_results.json` e `manifest.json` descrevem a última execução
local e são ignorados pelo Git. O contexto oficial de 2024 e os testes estão versionados.
As regras completas estão no [guia de modelagem](../modelagem-dbt.mdx).

## Decisão

Adotamos a alternativa **C**, com dbt no PostgreSQL e schemas separados:
`analytics_staging`, `analytics_intermediate`, `analytics_contexto`, `analytics_history`
e `analytics_marts`. A origem `oltp` é preservada; Parquet e Delta continuam independentes.

- **Granularidades complementares:** uma fato por lançamento, agregações mensais por
  categoria/fornecedor e uma fato mensal por senador. Nenhuma substitui a outra.
- **Histórico observado de fornecedor:** snapshot SCD tipo 2 por documento e razão social,
  com chave de versão e intervalos de observação. Reexecução idêntica não cria versão;
  alteração encerra a anterior. Isso não recupera mudanças anteriores à primeira coleta
  nem informa o cadastro vigente na data de uma despesa antiga.
- **Contexto parlamentar histórico:** um seed mensal de 2024, gerado automaticamente a
  partir dos mandatos, exercícios e filiações oficiais. Cada linha guarda URL, hash e
  data da coleta. O script atualiza o recorte solicitado e preserva os outros anos.
- **Comparação mensal:** a média usa os outros senadores do grupo com lançamentos na
  mesma competência e exercício confirmado, excluindo o próprio parlamentar. Meses sem
  lançamentos não viram zero; lançamentos de valor zero participam da média.
- **Classificação conservadora:** exige partido ou UF únicos nos dias em exercício do
  mês. Mudança de partido não recebe atribuição arbitrária; a comparação por UF pode
  continuar válida. Sem pares, a média é nula; com média zero, o percentual é nulo.
- **Presença documental:** sessões e registros são modelados com sua proveniência.
  Não inferimos ausência nem calculamos assiduidade com uma amostra de três sessões.
- **Execução local:** reconstrução integral dos modelos derivados, com histórico de
  fornecedor persistente. O contêiner executa com UID/GID local; Make prepara as saídas
  para permitir edição e limpeza dos artefatos sem sudo.

## Consequências

**O que ganhamos:** contratos de grão explícitos, reconciliação com a origem, uma resposta
reproduzível à pergunta central e modelos que o painel pode consumir sem repetir regras.
O histórico observado e a vigência parlamentar ficam separados, com limites verificáveis.

**O que perdemos:** simplicidade de consultar uma única cópia. Há armazenamento adicional,
custo de reconstrução e defasagem entre ingestão e transformação. Uma média mensal pode
comparar parlamentares com quantidades diferentes de dias em exercício; o número de dias
fica exposto e não projetamos gastos de um mês completo. Valores acima da média não são
classificações de irregularidade ou de atipicidade por LLM.

As publicações dos marts não formam uma única transação. Falha pode deixar modelos de
execuções distintas; o consumo deve ocorrer após execução bem-sucedida e sem ingestão
concorrente. Agendamento, retry, backfill, freshness e SLA precisam da integração da frente
de orquestração. Catálogo dbt não equivale à implantação de governança de toda a plataforma.

**O que custa reverter:** tabelas derivadas podem ser reconstruídas e outro transformador
pode executar as regras SQL, mas mudar chaves ou granularidade exige revisar testes e
consumidores. Apagar snapshots perde versões observadas que o OLTP já sobrescreveu. O
seed é um recorte versionado, sujeito a correções oficiais; ampliar ano ou população
exige atualizá-lo e revisar os estados de cobertura antes de republicar os modelos.

## Gatilho de revisão

Os limiares abaixo orientam uma nova avaliação; não são ganhos inferidos de uma única carga:

- Reavaliar reconstrução integral e incrementais quando a origem alcançar **100 mil
  despesas**, ou se a transformação exceder **10 minutos em três execuções consecutivas**.
- Rever os agregados se uma consulta de gestão ultrapassar **2 segundos em três medições**
  no ambiente de uso, ou se o painel exigir uma dimensão perdida no grão mensal.
- Atualizar e revalidar o contexto antes de incluir outro ano ou senadores ainda não
  cobertos; não preencher lacunas com partido e UF atuais.
- Se o consumidor exigir assiduidade, votos nominais ou classificação de atipicidade,
  definir fontes e denominadores próprios antes de reutilizar os indicadores disponíveis.
- Se houver leitores durante a carga ou mais de um escritor, revisar a publicação dos
  marts e a concorrência, em vez de presumir atomicidade do comando `dbt build`.

## Evidências no repositório

- [PR #35: integração da modelagem à develop](https://github.com/DaniloNavesS/inflow/pull/35).
- [Contexto histórico mensal](https://github.com/DaniloNavesS/inflow/commit/9b9742f).
- [Comparação da pergunta central](https://github.com/DaniloNavesS/inflow/commit/ebe90f5).
- [Correção de UID/GID e permissões](https://github.com/DaniloNavesS/inflow/commit/d7b406e).
