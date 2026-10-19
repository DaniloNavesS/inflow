# 0003: Adotamos DuckDB com Deltalake

- **Status:** aceito
- **Data:** 2026-10-19
- **Decisores:** Squad InFlow
## Contexto

Precisamos decidir como consumir a cópia analítica das despesas da CEAPS e quando separar
seus arquivos por ano e mês. O PostgreSQL continua sendo a origem transacional. A
[ADR 0002](./0002-adotamos-cdc-via-debezium-sobre-recarga-periodica.md) trata da captura de
mudanças e do histórico; esta ADR complementa aquela decisão com medições de leitura,
exportação inicial e particionamento. Não afirma que já existe consumo do Kafka pelo lake.

A base real possui **21.430 despesas de 2024**. A escala sintética usa **10.000, 100.000 e
1.000.000 de despesas**, com distribuição determinística, diferente da real. As restrições
atuais são um escritor Python em lote, poucos leitores, disco local e Docker. A caracterização
anterior tolera **10 minutos para carga**, **2 segundos por consulta** e frescor de **um mês**.
Apenas o volume atual não exige outro armazenamento para atender à latência.

A primeira versão do experimento particionava somente Parquet; Delta e Iceberg ficavam sem
partições. Os tempos eram válidos para aquelas configurações, mas não isolavam o efeito de
separar por ano/mês. **Repetimos todas as medições com duas organizações equivalentes nos
três formatos:** todos sem partição e todos particionados por identidade nas colunas `ano`
e `mes`. Os resultados anteriores não entram nas tabelas e figuras desta revisão.

Parquet é um formato de arquivo. Delta e Iceberg são formatos de tabela sobre arquivos.
DuckDB é o motor SQL que os consulta. O particionamento separa conjuntos de arquivos por
chaves; não é um índice B-tree. PostgreSQL conserva seus índices em todos os testes.

## Alternativas consideradas

### A. Opção nula: consultar somente o PostgreSQL

É viável, evita cópias e mantém o dado imediatamente consistente com a origem. A tabela
possui chave primária e índices, incluindo `(ano, mes)`. Na base real, PostgreSQL foi o mais
rápido no filtro mensal e na busca por ID. Todas as alternativas medidas ficaram abaixo do
limite de dois segundos.

Não é a única opção proposta porque buscamos também uma cópia aberta independente da
conexão com o OLTP e histórico de correções. PostgreSQL permanece como origem e caminho para
acessos pontuais; não medimos aqui uma implementação de histórico no próprio PostgreSQL.

### B. Parquet puro, escrito e consultado com DuckDB

Oferece uma cópia compacta, leitura colunar e exportação simples. Comparamos dois layouts:
um arquivo sem partições e pastas `ano=AAAA/mes=M/`. O formato puro não fornece, sozinho,
transações e versões da tabela. Sua aplicação precisa substituir a cópia ao reprocessar.

Sem partição, Parquet foi mais rápido nas três consultas da base real do que sua versão
particionada. Nesse volume, abrir mais arquivos não trouxe vantagem medida. Em um milhão
de linhas sintéticas, Parquet sem partição também venceu sua versão particionada na
agregação e no filtro mensal. Portanto, não escolhemos ano/mês apenas por ser uma prática
comum: é necessário verificar se há ganho no perfil de consultas.

### C. Delta Lake escrito com delta-rs e consultado com DuckDB

Usa Parquet e um log transacional. A implementação de `lake/delta/despesas` possui `MERGE`
por `id` e permite reler versões anteriores a uma correção. Na implantação local testada,
a tabela pode ser aberta por caminho sem catálogo separado.

Medimos sem partições e com `partition_by=["ano", "mes"]`. Em um milhão de linhas, ano/mês
reduziu o tempo do filtro mensal de **21,872 ms para 6,698 ms**. A vantagem não foi uniforme
nos menores volumes. O benefício principal para o projeto continua sendo histórico e
atualização, não uma promessa de que Delta sempre consulta mais rápido.

### D. Apache Iceberg escrito com PyIceberg e consultado com DuckDB

PyIceberg cria o catálogo SQLite e a tabela, escreve os arquivos e os metadados. DuckDB
executa SQL usando `iceberg_scan`. Isso distingue a ferramenta de escrita do motor de leitura.

Medimos sem partições e com transformações **identity** em `ano` e `mes`, sem usar um mês
transformado de outra coluna. Em um milhão de linhas, ano/mês reduziu o filtro mensal de
**23,224 ms para 5,701 ms**. Iceberg oferece snapshots e evolução de esquema/partições,
mas o cenário atual não requer outro motor escritor ou catálogo compartilhado. Mantemos a
alternativa no experimento, sem adicioná-la ao pipeline normal.

## Medição

### Condições e reprodução

Código: `analytics/src/benchmark.py`, **versão 2 do experimento**. Os dois relatórios possuem
o mesmo SHA-256 do script, registrado em seus metadados. Ambiente: Linux
`7.1.13-200.fc44.x86_64`, **12 CPUs visíveis**, PostgreSQL **15.17**, DuckDB **1.5.6**,
PyArrow **26.0.0**, deltalake **1.6.6** e PyIceberg **0.12.0**. As versões estão fixadas em
`scripts/adr/requirements.txt`.

1. Lemos uma projeção comum de **11 colunas** de despesas, ordenada por ID, uma vez por volume.
   Os seis caminhos recebem os mesmos dados Arrow, sem JOINs de enriquecimento.
2. Escrevemos Parquet, Delta e Iceberg com ZSTD nos dois layouts. A ordem de escrita é
   embaralhada com semente 42. O código verifica as definições de partição Delta/Iceberg e
   registra arquivos, bytes e número esperado de partições. Foram **12 partições** na base
   real e **72** em cada cenário sintético; cada caso particionado produziu um arquivo de
   dados por combinação ano/mês. Os casos sem partição produziram um arquivo cada.
3. Executamos uma consulta de aquecimento por caminho e depois **sete repetições**, alternando
   a ordem dos **sete caminhos**: PostgreSQL e os seis de arquivo. Existe uma única amostra
   PostgreSQL por consulta/repetição, compartilhada pelos dois layouts.
4. As consultas são agregação completa por senador/categoria, soma por senador em junho de
   2024 e busca por ID existente. Todos os resultados completos são comparados exatamente
   contra o PostgreSQL, inclusive durante as repetições.
5. Reportamos medianas com `fetch`, sem abertura de conexão ou exportação. Salvamos as amostras
   e os planos `EXPLAIN` em JSON. Os planos são estimados, não tempos instrumentados com
   `EXPLAIN ANALYZE`. O PostgreSQL real usa o índice `idx_despesas_ano_mes` no filtro mensal;
   o plano Parquet particionado mostra **Scanning Files: 1/12** nessa consulta.

A base real é lida com sessão PostgreSQL e conexão DuckDB somente leitura. Não aplicamos
DDL, índices novos ou `VACUUM` nela. No banco sintético descartável criamos índices e
executamos `VACUUM ANALYZE`. Não comparamos dados reais com sintéticos como se fossem uma
única série de crescimento.

```bash
# Base real já carregada; não modifica oltp.despesas.
make benchmark-lake-real BENCHMARK_REPETITIONS=7

# Banco descartável, com os mesmos dois layouts em todos os formatos.
make benchmark-lake BENCHMARK_ROWS="10000 100000 1000000" BENCHMARK_REPETITIONS=7
```

As evidências atuais são [base-real.json](/data/adr-0003/base-real.json), medida em
**2026-10-19T03:39:50Z**, e [escala-sintetica.json](/data/adr-0003/escala-sintetica.json), medida
em **2026-10-19T03:42:13Z**. Os JSONs anteriores foram preservados na pasta
`documentation/static/data/adr-0003/historico-layout-desigual/` como histórico, sem uso nas
novas figuras. Cada execução reproduzida gera uma nova pasta em `resultados/benchmark-lake/`.

### Exportação inicial

**Exportação inicial = leitura da origem para Arrow + criação e primeira escrita do formato.**
A leitura é medida uma vez por volume e somada ao custo de escrita de cada alternativa.
No Iceberg, agora incluímos também a inicialização do catálogo SQLite, namespace, tabela e
configuração das partições. Os arquivos incluem ZSTD; não há exportação no caminho PostgreSQL.

Esse custo é uma **medição única**, não a mediana das sete repetições de consulta. Ele pode
ser influenciado pela primeira inicialização da biblioteca e por caches. Não usamos esses
números para concluir que um layout sempre escreve mais rápido. Eles não representam o custo
de aplicar uma correção ou de executar os JOINs do exportador enriquecido do pipeline.

### Base real: 21.430 despesas

Todos os tempos abaixo estão em **milissegundos**; menor é melhor. A referência PostgreSQL
é a mesma nos dois layouts, não duas execuções escolhidas separadamente.

| Alternativa | Layout | Agregação | Filtro mensal | Busca por ID | Exportação inicial | Agregações para amortizar |
|---|---|---:|---:|---:|---:|---:|
| PostgreSQL | índices existentes | 10,679 | 1,472 | 0,430 | não se aplica | não se aplica |
| DuckDB + Parquet | sem partição | 4,716 | 2,857 | 2,318 | 202,450 | 34 |
| DuckDB + Parquet | ano/mês | 5,753 | 3,074 | 2,516 | 215,665 | 44 |
| DuckDB + Delta | sem partição | 6,669 | 5,980 | 5,076 | 412,013 | 103 |
| DuckDB + Delta | ano/mês | 6,629 | 4,964 | 4,531 | 199,453 | 50 |
| DuckDB + Iceberg | sem partição | 6,400 | 3,983 | 3,742 | 631,744 | 148 |
| DuckDB + Iceberg | ano/mês | 6,769 | 3,666 | 2,954 | 473,275 | 122 |

Parquet sem partição teve o menor tempo de agregação entre os caminhos medidos: **4,716 ms**
contra **10,679 ms** do PostgreSQL. Separá-lo por ano/mês elevou a mediana para **5,753 ms**.
No filtro mensal, Parquet passou de **2,857 ms sem partição para 3,074 ms com partição**;
PostgreSQL levou **1,472 ms**. Essa diferença pequena entre os dois Parquets não estabelece
significância estatística: indica que não observamos vantagem de particionar nessa rodada.

A economia de aproximadamente **5,963 ms por agregação** do Parquet sem partição amortizaria
a exportação experimental em **34 consultas iguais**; a versão particionada exigiria **44**.
Para filtro mensal e busca por ID, não há amortização pelo tempo medido na base real.

```text
consultas_para_amortizar = teto(exportacao_inicial /
                               (tempo_postgresql - tempo_arquivo))
```

A fórmula só vale quando há economia positiva, para consultas iguais entre exportações.
Não inclui operação, retenção, concorrência nem a mistura real das consultas.

### Escala sintética: comparação dentro do mesmo layout

Tempos em milissegundos. Todos os formatos de uma linha usam a organização indicada.

| Linhas sintéticas | Consulta | Layout | PostgreSQL | Parquet | Delta | Iceberg |
|---:|---|---|---:|---:|---:|---:|
| 10.000 | Agregação | sem partição | 3,695 | 3,481 | 4,920 | 4,201 |
| 10.000 | Agregação | ano/mês | 3,695 | 11,041 | 9,175 | 9,660 |
| 10.000 | Filtro mensal | sem partição | 0,816 | 2,249 | 5,418 | 3,490 |
| 10.000 | Filtro mensal | ano/mês | 0,816 | 7,693 | 5,704 | 5,651 |
| 10.000 | Busca por ID | sem partição | 0,469 | 2,137 | 5,413 | 3,739 |
| 10.000 | Busca por ID | ano/mês | 0,469 | 8,847 | 8,671 | 7,640 |
| 100.000 | Agregação | sem partição | 29,114 | 6,887 | 9,070 | 9,855 |
| 100.000 | Agregação | ano/mês | 29,114 | 12,802 | 10,151 | 10,464 |
| 100.000 | Filtro mensal | sem partição | 2,234 | 3,397 | 7,078 | 5,797 |
| 100.000 | Filtro mensal | ano/mês | 2,234 | 7,807 | 5,422 | 5,201 |
| 100.000 | Busca por ID | sem partição | 0,475 | 11,361 | 10,125 | 12,866 |
| 100.000 | Busca por ID | ano/mês | 0,475 | 9,532 | 8,609 | 8,017 |
| 1.000.000 | Agregação | sem partição | 126,461 | 11,081 | 48,952 | 51,941 |
| 1.000.000 | Agregação | ano/mês | 126,461 | 17,798 | 17,938 | 17,797 |
| 1.000.000 | Filtro mensal | sem partição | 17,221 | 5,896 | 21,872 | 23,224 |
| 1.000.000 | Filtro mensal | ano/mês | 17,221 | 8,269 | 6,698 | 5,701 |
| 1.000.000 | Busca por ID | sem partição | 0,441 | 20,359 | 45,495 | 50,912 |
| 1.000.000 | Busca por ID | ano/mês | 0,441 | 11,159 | 11,617 | 10,263 |

Na agregação de um milhão, os três caminhos particionados ficaram próximos de **17,8–17,9 ms**;
as diferenças não sustentam declarar um vencedor. Parquet sem partição levou **11,081 ms**.
No filtro mensal desse volume, separar Delta e Iceberg trouxe ganhos expressivos; para
Parquet, a versão sem partição permaneceu mais rápida. PostgreSQL venceu todas as buscas
por ID nos três volumes sintéticos, independentemente do layout de arquivos.

### Efeito de separar por ano/mês

A tabela isola a mudança de layout no **filtro mensal**. Razão acima de 1 indica menor tempo
com ano/mês; abaixo de 1 indica menor tempo sem partições. A comparação não equivale a um
índice novo no PostgreSQL.

| Origem | Formato | Sem partição | Ano/mês | Razão sem ÷ com |
|---|---|---:|---:|---:|
| Real 21.430 | Parquet | 2,857 | 3,074 | 0,93× |
| Real 21.430 | Delta | 5,980 | 4,964 | 1,20× |
| Real 21.430 | Iceberg | 3,983 | 3,666 | 1,09× |
| Sintética 10.000 | Parquet | 2,249 | 7,693 | 0,29× |
| Sintética 10.000 | Delta | 5,418 | 5,704 | 0,95× |
| Sintética 10.000 | Iceberg | 3,490 | 5,651 | 0,62× |
| Sintética 100.000 | Parquet | 3,397 | 7,807 | 0,44× |
| Sintética 100.000 | Delta | 7,078 | 5,422 | 1,31× |
| Sintética 100.000 | Iceberg | 5,797 | 5,201 | 1,11× |
| Sintética 1.000.000 | Parquet | 5,896 | 8,269 | 0,71× |
| Sintética 1.000.000 | Delta | 21,872 | 6,698 | 3,27× |
| Sintética 1.000.000 | Iceberg | 23,224 | 5,701 | 4,07× |

Em um milhão, a razão foi **3,27× para Delta** e **4,07× para Iceberg**. Parquet ficou em
**0,71×**, favorecendo a ausência de partições. Em 10 mil, abrir 72 arquivos pequenos trouxe
mais custo que benefício nos três formatos. A organização muda número/tamanho dos arquivos,
paralelismo e metadados além de permitir descartar partições: não atribuimos toda diferença
exclusivamente à quantidade de linhas descartadas.

### Gráficos

**Base real:** a primeira linha mostra todos sem partições; a segunda, os três por ano/mês.
Cada coluna usa a mesma escala vertical nos dois painéis. A barra PostgreSQL é repetida
apenas como referência visual e contém exatamente as mesmas amostras.

![Comparação de três consultas na base real com os três formatos sem partições e por ano/mês, mantendo uma referência PostgreSQL única.](/img/adr-0003/base-real-particionamento.svg)


![Comparação de três consultas em 10 mil, 100 mil e um milhão de despesas sintéticas, separando os dois layouts nos três formatos.](/img/adr-0003/escala-sintetica-particionamento.svg)


Pontos e barras representam medianas; os traços de erro mostram mínimo e máximo observados,
**não intervalos de confiança**. O [CSV das figuras](/img/adr-0003/medicoes.csv) registra 96
pontos, incluindo as referências PostgreSQL repetidas nos painéis. Para regenerar os gráficos:

```bash
python -m venv /tmp/inflow-adr-grafico
/tmp/inflow-adr-grafico/bin/pip install -r scripts/adr/requirements-grafico.txt
/tmp/inflow-adr-grafico/bin/python scripts/adr/0003_grafico_benchmark.py
```

### Limites da evidência

A comparação mede **motor + transporte + escritor + organização dos arquivos**. PostgreSQL
é consultado pela rede Docker; DuckDB lê arquivos locais. Igualamos dados, ZSTD e chaves
lógicas de partição; não forçamos igualdade de tamanho dos row groups, tamanho-alvo de
arquivo ou algoritmo de metadados entre escritores distintos. Os padrões das bibliotecas
podem influenciar a leitura. Partição configurada não garante que cada leitor explore o
mesmo mecanismo de descarte; os planos estão disponíveis para inspeção.

Há sete repetições em uma sessão por conjunto, com cache aquecido. Não medimos cache frio,
concorrência, escrita contínua, atualização, crescimento de logs ou armazenamento remoto.
A distribuição sintética tem correlação entre senador e categoria e não reproduz fielmente
a CEAPS real. Não existe um número universal de linhas que torne Parquet ou ano/mês vantajoso.
O pequeno ganho de Parquet sem partição sobre PostgreSQL na agregação sintética de 10 mil
linhas (cerca de 1,06×) exige novas sessões antes de ser tratado como vantagem estável.

## Decisão

Para a carga real atual, o layout **sem partição é o candidato preferido quando o critério
é tempo de leitura**: a separação por ano/mês não mostrou vantagem em Parquet. A exportação
operacional atual ainda usa ano/mês; esta ADR permanece proposta e não reconfigura esse
exportador. Uma alteração operacional deve preservar os testes e medir também os JOINs
de enriquecimento, cujo custo não está nesta projeção de 11 colunas.

Mantemos **Delta via delta-rs para histórico e MERGE por ID**, em continuidade à ADR 0002.
O resultado em um milhão mostra que particioná-lo pode ajudar, mas não exige essa organização
na base real atual. Iceberg permanece uma alternativa medida: com o mesmo particionamento,
seu desempenho não justifica descartá-lo como inerentemente mais lento; o custo operacional
do catálogo continua sendo o motivo para não adicioná-lo ao cenário local desta etapa.

Os ganhos de agregação e a portabilidade sustentam a cópia; não alegamos que o PostgreSQL
seja insuficiente para a meta atual de latência. O pipeline `make ingestion && make lake`
continua por snapshots completos e registra a execução em `monitoring.pipeline_runs`.
Suas consultas de gestão e JOINs são diferentes das consultas controladas desta medição.

## Consequências

**O que ganhamos:** decisão de formato e layout sustentada por comparações equivalentes;
leitura analítica independente da conexão permanente ao OLTP; possibilidade de reduzir o
custo de muitos arquivos pequenos; histórico Delta; amostras, planos, tabelas e gráficos
reproduzíveis. O requisito de particionamento deixa de ser uma suposição de desempenho.

**O que perdemos:** simplicidade de uma única cópia e de uma única configuração universal.
Mantemos materialização, defasagem entre cargas e verificação de consistência. Um layout
que favorece uma consulta pode piorar outra. Abrir muitas partições custa metadados e I/O;
um arquivo único grande também pode limitar paralelismo conforme o escritor. O custo de
exportação pode superar a economia das consultas reais. Delta exige retenção e manutenção;
`VACUUM` pode remover a possibilidade de reler versões antigas. Parquet e Delta não são
publicados como uma única transação do pipeline.

**O que se torna irreversível:** trocar formato ou particionamento é possível, mas custa
reextração, reescrita, armazenamento temporário e revalidação de consultas. Recriar a cópia
atual a partir do OLTP não recupera correções históricas já sobrescritas. Uma migração Delta
deve respeitar o log; ler todos os Parquets da pasta pode incluir versões removidas. Preservar
histórico exige migrar versões e sua sequência. A remoção definitiva de logs e arquivos
antigos é a parte irreversível, não a escolha de layout em si.

## Gatilho de revisão

Os critérios abaixo são **propostas de operação**, não limites estatísticos derivados de
uma única sessão de sete repetições:

- Reavaliar Parquet se o número de consultas entre exportações ficar abaixo da amortização
  medida por **três ciclos consecutivos**. A referência experimental atual é 34 agregações
  sem partição ou 44 por ano/mês; recalcular com os JOINs e a mistura real de consultas.
- Repetir os dois layouts quando a base real atingir **100 mil despesas**, ou mudarem índices,
  hardware, distribuição, leitores concorrentes ou armazenamento. É um marco de teste da
  camada analítica, não um limiar obrigatório de migração nem substituição do gatilho da ADR 0001.
- Propor a troca de layout quando o ganho na carga real se repetir em **três sessões
  independentes**, e a economia no conjunto de consultas entre cargas superar o custo de
  reescrita. Não decidir por um único filtro mais rápido.
- Rever a materialização se a mediana da consulta ultrapassar **2 segundos**, o lake exceder
  **10 minutos** ou a defasagem exceder **um mês**.
- Reavaliar Iceberg quando houver segundo motor escritor, catálogo compartilhado ou necessidade
  de evoluir particionamento sem reescrita completa, medindo esses requisitos antes da troca.
- Se for necessário preservar **cada evento de mudança**, implementar e validar consumo CDC,
  ordenação, deduplicação, checkpoint e retenção: snapshots completos podem perder estados
  intermediários.
