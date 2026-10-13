---
title: Replay e semântica de entrega do CDC
---

# Replay do CDC de despesas

O tópico `inflow.oltp.despesas` é um log de eventos. O conector e um consumidor
podem repetir uma mensagem após falha e retomada de offset. Não há garantia de
*exactly once* entre o WAL, o Kafka e um destino externo.

## Prova reproduzível

Com uma carga de despesas já existente, execute:

```bash
make cdc-test
```

O teste `tests/test_cdc_integration.py` espera o slot e o tópico, posiciona o
consumidor no fim, altera o `valor` de uma despesa e confirma o evento `op=u`
com o novo valor. Em seguida, faz `seek` para o **mesmo tópico, partição e
offset**, lê novamente a mensagem e compara os payloads desserializados. O teste
restaura o valor inicial no `finally`; essa restauração também gera um evento.

O próprio teste aplica as duas leituras a dois destinos simulados:

| Destino | Chave | Resultado do mesmo evento duas vezes |
|---|---|---|
| Lista append-only | nenhuma | 2 registros: duplica |
| Projeção de estado | `despesas.id` | 1 registro: converge para o último valor |

Essa releitura é um **replay deliberado do consumidor**, não uma demonstração de
que o Debezium duplicou a publicação. A garantia observada é que o consumidor
pode ver o mesmo offset novamente. Um destino append-only de produção precisa
deduplicar por `(tópico, partição, offset)` ou por identificador estável do
evento. Uma tabela de estado deve fazer upsert por `despesas.id` e tratar
`DELETE` removendo a chave. A projeção no teste só cobre `UPDATE`; ainda não é
um consumidor persistente nem prova tratamento de falhas entre gravação e
commit de offset.

Na validação local de 13/10/2026, `make cdc-test` terminou com `1 passed in
1.10s`, usando um banco com 21.430 despesas e o conector em estado `RUNNING`.

O snapshot inicial também publica um evento por linha antes dos eventos de
alteração. Consumidores que constroem estado precisam aplicar snapshot e
alterações na ordem de cada partição.
