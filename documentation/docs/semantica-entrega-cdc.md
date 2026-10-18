---
sidebar_position: 5
title: CDC e semântica de entrega
---

# CDC de despesas e replay — E2

Na E2, o fluxo de mudanças cobre `oltp.despesas`. A carga em lote continua buscando os dados do Senado; o CDC começa quando uma linha já gravada no PostgreSQL muda. Esta página descreve a captura implementada pela equipe de Ana, Yza e Manu e o teste de replay e deduplicação do [PR 27](https://github.com/DaniloNavesS/inflow/pull/27).

## Caminho da mudança

```text
UPDATE em oltp.despesas
  → WAL lógico do PostgreSQL
  → Debezium no Kafka Connect
  → tópico inflow.oltp.despesas
  → consumidor de teste
```

O PostgreSQL sobe com `wal_level=logical`. A migração `scripts/sql/oltp/014_cdc_publication.sql` cria a publication `inflow_despesas_pub` para `oltp.despesas` e define `REPLICA IDENTITY FULL`, permitindo que o evento de atualização traga os valores anteriores. O conector usa `pgoutput` e o slot `inflow_despesas_slot`; sua configuração está em `scripts/cdc/despesas-connector.json`.

`make cdc-register` aplica a migração, inicia Zookeeper, Kafka e Kafka Connect e registra o conector. O registro pode ser repetido. No tópico, `payload.op = "u"` identifica uma atualização; `payload.before` e `payload.after` mostram os valores antigo e novo. O campo `source.lsn` indica a posição da mudança no WAL. O conector envia `valor` como texto para preservar o decimal legível no JSON.

Na primeira conexão, o Debezium também pode publicar um snapshot das despesas existentes. Depois disso, o tópico recebe as mudanças capturadas. Os upserts da carga foram tornados condicionais: uma recarga sem mudança nos dados não deve reescrever todas as despesas e gerar eventos desnecessários. As medições e a decisão de usar CDC estão no [ADR 0002](./adr/0002-adotamos-cdc-via-debezium-sobre-recarga-periodica.md).

## Verificar a propagação

Com Docker e Compose disponíveis, carregue as despesas e execute:

```bash
make ingestion
make cdc-test
make cdc-status
```

`make cdc-test` inicia o CDC, reconstrói a imagem do ingestor e roda `tests/test_cdc_integration.py`. O teste espera o slot e o tópico, posiciona o consumidor no fim do tópico, altera o `valor` de uma despesa e exige um evento `op = "u"` com o novo valor. No fim, restaura o valor anterior. A restauração também produz um evento de atualização. Sem despesas carregadas, o teste é pulado.

Na execução local de 13/10/2026, o conector ficou `RUNNING` e o teste passou com 21.430 despesas carregadas (`1 passed in 1.10s`). Essa medição pertence àquele ambiente; os comandos acima reproduzem a verificação em outro banco.

## O que o replay mostra

Kafka guarda eventos por tópico, partição e offset. Um consumidor que volta a um offset pode receber a mesma mensagem outra vez. Os testes forçam essa situação com `seek`, sem depender de uma falha aleatória:

1. `tests/test_cdc_integration.py` relê o offset da atualização criada pelo próprio teste. Uma lista que só acrescenta eventos fica com duas entradas; uma projeção por `despesas.id` fica com uma linha no valor novo.
2. `tests/test_delivery_semantics.py`, acrescentado no PR 27, lê os eventos reais do tópico, volta aos offsets iniciais e lê o mesmo conjunto outra vez. Compara `AppendConsumer` e `IdempotentDeduplicator`, implementados em `ingestion/src/cdc/dedup.py`.

Se a primeira leitura tiver **N eventos** e **U registros ativos** após a deduplicação, o replay produz este resultado:

| Consumidor de teste | Após a primeira leitura | Após reler os N eventos |
|---|---:|---:|
| Lista sem controle | N entradas | 2N entradas |
| Estado por chave e LSN | U registros ativos | U registros ativos; N eventos do replay descartados |

`U` pode ser menor que `N`: o tópico pode conter snapshot, atualizações, exclusões e entregas repetidas antes do teste. Por isso, o teste mede os descartes do replay separadamente dos descartes que já ocorreram na primeira leitura.

Para reproduzir a comparação e ver o resultado no terminal:

```bash
make cdc-semantics
make cdc-replay-demo
```

O primeiro comando roda o teste de integração; o segundo imprime os contadores das duas estratégias. Ambos precisam de Kafka com eventos no tópico. `make cdc-test` gera ao menos uma alteração quando há despesas carregadas.

## Regra de deduplicação

O `IdempotentDeduplicator` mantém, **em memória**, o último LSN visto para cada `despesas.id`. Para uma chave já conhecida, descarta eventos com LSN menor ou igual ao armazenado; com LSN maior, atualiza o estado. Em `DELETE`, remove a linha ativa. Um evento sem LSN válido é rejeitado: `ts_ms` é um horário e não pode ser comparado com a posição no WAL.

Essa regra demonstra que o estado por chave não muda ao reler as mesmas mensagens enquanto o processo mantém sua memória. O replay é uma ação do consumidor: ele não demonstra que o Debezium publicou uma duplicata. Também não há consumidor persistente ligado à camada analítica nem gravação atômica do estado junto com o offset. Portanto, os testes **não comprovam exactly once ponta a ponta**; um destino real ainda precisa persistir a deduplicação ou fazer upsert idempotente e tratar a recuperação após falhas.
