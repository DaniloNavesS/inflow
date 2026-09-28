# ADR 0002: Modelagem do sistema de origem

## Decisão: espelhamos a origem em modelo CRUD normalizado, com carimbo de ingestão próprio

- **Status:** aceita
- **Data:** 2026-09-26
- **Decisores:** Squad InFlow

## Contexto

A origem combina APIs públicas do Senado Federal (cadastro por legislatura, mandatos,
exercícios, filiações, comissões, CEAPS e recursos de gabinete) com o Diário do Senado
Federal (DSF), fonte documental oficial das listas de comparecimento.

A origem é híbrida. CEAPS devolve o ano inteiro reprocessado e pode sobrescrever correções, mas
`senador/{codigo}/mandatos` e `senador/{codigo}/filiacoes` expõem intervalos históricos. O DSF é
publicado como documento imutável e precisa ser rastreado por código, URL, páginas e hash. O modelo
preserva o histórico que a fonte fornece e aplica upsert apenas aos retratos reprocessados.

Carga de trabalho medida (detalhe em [`docs/workload.md`](../workload.md)):

| Tabela | Linhas | Tamanho |
|---|---|---|
| `despesas` | 21.430 | 13 MB |
| `participacoes_comissao` | 7.189 | 1,4 MB |
| `fornecedores` | 3.516 | 944 kB |
| `registro_presenca` (prova) | 220 | não medido |

Escrita em lote (~33 mil linhas em 90 s, uma vez por dia no pior caso) contra leitura analítica
frequente. Cardinalidade baixa nas colunas de filtro: 88 senadores, 8 tipos de despesa, 469 datas
distintas. Latência tolerada: segundos.

## Alternativas consideradas

**A. Consulta sob demanda, sem banco.**
Essa alternativa não exige modelagem nem carga. Foi descartada porque a agregação por senador ×
tipo × período exigiria varrer 21 mil lançamentos a cada pergunta. A API não aceita filtro por senador
no endpoint de CEAPS, e sem persistência não é possível detectar quando o valor de um lançamento muda.
Isso inviabiliza a E2.

**B. Insert-only / append, com versionamento de linha.**
Cada resposta da API gera uma nova versão da linha; a leitura pega a mais recente. Preserva o
histórico de correções que a origem apaga, o que é justamente a informação interessante do domínio.
Descartada **para a E1**: a origem reprocessa o ano inteiro a cada chamada, então sem comparação
campo a campo cada execução geraria 21 mil versões idênticas. Fazer isso direito é o problema da
E2 (CDC) e depende de um estado anterior confiável, construído nesta entrega.

**C. Espelhar a origem em CRUD normalizado, com upsert idempotente (escolhida).**
Uma linha por entidade da origem, chaveada pelo identificador oficial (`CodigoParlamentar`,
`CodigoComissao`, `id` do lançamento). Reexecutar a carga converge para o mesmo estado.

## Medição

Ambiente reproduzível: `docker compose down -v && docker compose up --build`, PostgreSQL 15,
dados reais de 2024 (`INGESTION_YEAR=2024`).

- **Carga completa do zero:** 90,6 s (81 senadores, 21.430 despesas, 3.516 fornecedores).
- **Idempotência:** duas cargas completas seguidas deixam as contagens por tabela idênticas
  (96 / 425 / 7.189 / 190 / 1.086 / 3.516 / 21.430 / 81).
- **Agregação por senador × tipo de despesa no ano:** `Execution Time: 12,0 ms`.
- **Recorte por senador e período** (`idx_despesas_senador_data`): `Execution Time: 0,198 ms`.
- **Restrições barram lixo da origem:** `valor` negativo, UF inexistente e `data_fim < data_inicio`
  são rejeitados; o ingestor normaliza esses casos antes do insert.

Normalizar `fornecedores` em tabela própria permite responder quanto cada entidade recebeu e de
quais senadores. CNPJ e CPF completos são chaves fortes; CPF mascarado usa documento mais nome
normalizado; documento ausente usa nome mais identificador da despesa. Assim, ausências de documento
não são colapsadas numa entidade genérica.

### Presença não é voto

Durante a avaliação da cobertura das APIs do Senado, Yan Guimarães testou os endpoints públicos
para verificar se respondiam às perguntas de gestão. Os testes identificaram lacunas nas perguntas 5,
6 e 10, que dependem de dados de comparecimento. A partir dessa constatação, o squad avaliou o DSF
como fonte documental oficial para presença.

Votação nominal não é fonte suficiente para medir assiduidade. Um senador pode comparecer sem votar,
e um registro de voto não representa a presença durante toda a sessão. Por isso, a fonte escolhida é a
seção **Registro de Comparecimento e Voto** (ou **Registro de Comparecimento**) do DSF, conforme o
tutorial oficial do Senado.

Cada registro mantém `documento_dsf_id` e página. O voto é um booleano separado e nunca determina
a presença. Falha do parser fica em `documento_dsf.status_parser`; nome ambíguo fica sem
`senador_id`. Ausência de linha, ausência de voto ou falha de extração nunca gera uma ausência.

## Decisão

Espelhamos a origem em **modelo CRUD normalizado** (7 tabelas, 3FN), com `ON CONFLICT DO UPDATE`
pela chave natural do Senado, e guardamos **três carimbos de tempo com papéis distintos**:

- **Tempo do evento:** `despesas.data_despesa`, `sessao_plenaria.data_sessao` e
  `participacoes_comissao.data_inicio` indicam quando o fato ocorreu no mundo. Esse é o eixo
de qualquer análise temporal.
- **Tempo de ingestão:** `timestamp_ingestao` registra quando a linha entrou no banco e não muda.
- **Tempo de processamento:** `atualizado_em`, mantido por trigger, registra quando o ingestor
  tocou a linha pela última vez. É o sinal bruto de que a origem mudou algo.

Não desnormalizamos nada nesta entrega. `estrutura_gabinete.qtd_total_servidores` é coluna gerada,
não duplicação, e `despesas.ano`/`mes` são redundantes com `data_despesa` de propósito: vêm da
origem e sustentam o índice `(ano, mes)` usado nos recortes mensais.

## Consequências

**Ganhos.** A carga é idempotente e reexecutável sem passo manual. O esquema recusa dado inválido
em vez de aceitar tudo como `TEXT`. As chaves naturais oficiais tornam a reconciliação com a fonte
trivial.

**Limitação conhecida.** O `ON CONFLICT DO UPDATE` atual toca a linha mesmo quando nada mudou:
após a segunda carga, `atualizado_em > timestamp_ingestao` em 21.430 de 21.430 despesas. Ou seja,
`atualizado_em` hoje marca "o ingestor passou aqui", não "a origem mudou". Tornar o UPDATE
condicional (`WHERE valor IS DISTINCT FROM EXCLUDED.valor OR ...`) é pré-requisito do CDC da E2.

**Perdas.** Correções retroativas da CEAPS são **perdidas**: se um lançamento de R$ 10.000 vira
R$ 8.000, sobrescrevemos o valor e a versão antiga desaparece. Também perdemos o histórico de quem
saiu do exercício quando nem a lista por legislatura nem os endpoints históricos registram a pessoa.
Partido e UF desconhecidos ficam nulos; não se fabrica `S/PART` nem `DF`.

**Irreversibilidade.** Nenhuma estrutural: o esquema sobe do zero por migrações. Mas o histórico
não capturado entre hoje e a implantação do CDC é **irrecuperável**, pois a origem não o guarda.

Os 4 lançamentos com data anterior a 2000 (o menor é `0202-07-04`) são erro de digitação na fonte
e ficam preservados como estão; corrigi-los é decisão da camada analítica, não do espelho.

## Gatilho de revisão

Migramos para insert-only (alternativa B) quando **qualquer** limiar for atingido:

- mais de **1% das linhas de `despesas`** mudar de valor entre duas cargas consecutivas;
- a pergunta de gestão passar a exigir "o que a origem dizia na data X";
- `despesas` passar de **5 milhões de linhas**, quando o custo do upsert em massa supera o do append.

Medir o primeiro limiar depende de tornar o UPDATE condicional, conforme a limitação acima; até lá
o gatilho é verificado manualmente, comparando o total reembolsado do ano entre duas cargas.
