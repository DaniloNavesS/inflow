---
title: CDC e semântica de entrega
---

# CDC e semântica de entrega — E2

Na E2, Ana, Yza e Manu ficaram com os itens 1, 3 e 7: CDC, semântica de entrega e diário de bordo. O registro é da equipe; o histórico Git não atribui cada etapa a uma pessoa.

| Entrega | O que foi feito | Evidência |
|---|---|---|
| CDC | Debezium lê o WAL do PostgreSQL e publica mudanças de `oltp.despesas` no tópico `inflow.oltp.despesas`. | `tests/test_cdc_integration.py` altera uma despesa e confere o novo valor no tópico. |
| Replay | O teste relê o mesmo offset: uma lista acumula duas entradas; a projeção por `despesas.id` fica com uma. | `tests/test_cdc_integration.py` nesta branch. |
| Deduplicação | O [PR 27](https://github.com/DaniloNavesS/inflow/pull/27), já na `develop`, acrescentou teste de replay com deduplicação por chave e LSN. | `tests/test_delivery_semantics.py` e `make cdc-semantics` na `develop`. |
| Diário | Registro das semanas 7 a 10 a partir do histórico Git. | `documentation/squad/processos/03-diario-de-bordo-semanas-7-a-10.mdx` nesta branch. |

Execute após carregar despesas com `make ingestion`:

```bash
make cdc-test
```

O teste restaura o valor original ao terminar. Na execução local de 13/10/2026, passou com o conector `RUNNING` e 21.430 despesas carregadas (`1 passed in 1.10s`).

**Limite:** o replay é provocado pelo consumidor com `seek`; ele não prova que o Debezium publicou a mensagem duas vezes. As projeções dos testes ficam em memória. Ainda não há garantia de processamento exatamente uma vez em um destino persistente.
