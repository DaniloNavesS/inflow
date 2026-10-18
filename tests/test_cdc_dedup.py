"""Testes unitários para o módulo de deduplicação de eventos CDC."""
from cdc.dedup import AppendConsumer, IdempotentDeduplicator


def _make_debezium_event(despesa_id: int, valor: float, lsn: int, op: str = "u") -> dict:
    """Helper para construir payload simulado do conector Debezium."""
    return {
        "schema": {"type": "struct"},
        "payload": {
            "op": op,
            "ts_ms": 1729267200000,
            "source": {
                "version": "2.7.3.Final",
                "connector": "postgresql",
                "name": "inflow",
                "ts_ms": 1729267200000,
                "db": "inflow_db",
                "schema": "oltp",
                "table": "despesas",
                "lsn": lsn,
            },
            "before": {"id": despesa_id, "valor": valor - 10} if op != "c" else None,
            "after": {"id": despesa_id, "valor": valor} if op != "d" else None,
        },
    }


def test_append_consumer_accumulates_all_events():
    consumer = AppendConsumer()
    event = _make_debezium_event(despesa_id=1, valor=100.0, lsn=1000)

    consumer.consume(event)
    consumer.consume(event)  # Replay da mesma mensagem

    assert consumer.total_processed == 2


def test_idempotent_deduplicator_discards_exact_duplicates():
    dedup = IdempotentDeduplicator(key_field="id")
    event = _make_debezium_event(despesa_id=1, valor=100.0, lsn=1000)

    primeiro_aceito = dedup.consume(event)
    segundo_aceito = dedup.consume(event)  # Replay

    assert primeiro_aceito is True
    assert segundo_aceito is False
    assert dedup.total_received == 2
    assert dedup.duplicates_ignored == 1
    assert dedup.total_unique == 1
    assert dedup.active_records[1]["valor"] == 100.0


def test_idempotent_deduplicator_accepts_newer_version():
    dedup = IdempotentDeduplicator(key_field="id")
    v1 = _make_debezium_event(despesa_id=1, valor=100.0, lsn=1000)
    v2 = _make_debezium_event(despesa_id=1, valor=150.0, lsn=1050)

    dedup.consume(v1)
    dedup.consume(v2)

    assert dedup.total_unique == 1
    assert dedup.duplicates_ignored == 0
    assert dedup.active_records[1]["valor"] == 150.0


def test_idempotent_deduplicator_rejects_older_out_of_order_event():
    dedup = IdempotentDeduplicator(key_field="id")
    v1 = _make_debezium_event(despesa_id=1, valor=100.0, lsn=1000)
    v2 = _make_debezium_event(despesa_id=1, valor=150.0, lsn=1050)

    dedup.consume(v2)  # Chegou v2 primeiro
    aceito_v1 = dedup.consume(v1)  # Chegou v1 atrasado/fora de ordem

    assert aceito_v1 is False
    assert dedup.duplicates_ignored == 1
    assert dedup.active_records[1]["valor"] == 150.0


def test_idempotent_deduplicator_handles_deletions():
    dedup = IdempotentDeduplicator(key_field="id")
    insert_ev = _make_debezium_event(despesa_id=1, valor=100.0, lsn=1000, op="c")
    delete_ev = _make_debezium_event(despesa_id=1, valor=100.0, lsn=1050, op="d")

    dedup.consume(insert_ev)
    assert dedup.total_unique == 1

    dedup.consume(delete_ev)
    assert dedup.total_unique == 0


def test_simulated_stream_replay_comparison():
    """Compara diretamente o comportamento de replay:

    - Append Consumer duplica registros (2x N).
    - Idempotent Deduplicator converge para o mesmo estado (N registros).
    """
    eventos = [
        _make_debezium_event(despesa_id=101, valor=50.0, lsn=2001),
        _make_debezium_event(despesa_id=102, valor=75.5, lsn=2002),
        _make_debezium_event(despesa_id=103, valor=120.0, lsn=2003),
        _make_debezium_event(despesa_id=104, valor=300.0, lsn=2004),
        _make_debezium_event(despesa_id=105, valor=45.0, lsn=2005),
    ]

    append_consumer = AppendConsumer()
    dedup_consumer = IdempotentDeduplicator(key_field="id")

    # 1ª Passada: consumo normal dos 5 eventos
    for ev in eventos:
        append_consumer.consume(ev)
        dedup_consumer.consume(ev)

    assert append_consumer.total_processed == 5
    assert dedup_consumer.total_unique == 5
    assert dedup_consumer.duplicates_ignored == 0

    # 2ª Passada: REPLAY exato dos mesmos 5 eventos
    for ev in eventos:
        append_consumer.consume(ev)
        dedup_consumer.consume(ev)

    # Comprova o efeito da garantia at-least-once:
    # 1. Sem dedup: duplicação dos dados processados (10 eventos)
    assert append_consumer.total_processed == 10

    # 2. Com dedup: idempotência total (continua com 5 registros e 5 duplicatas descartadas)
    assert dedup_consumer.total_received == 10
    assert dedup_consumer.total_unique == 5
    assert dedup_consumer.duplicates_ignored == 5

