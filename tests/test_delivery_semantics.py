"""Teste de integração demonstrando a semântica de entrega (at-least-once e replay).

Comprova empiricamente:
1. Sem deduplicação (AppendConsumer): O replay de mensagens no Kafka duplica os registros (2x N).
2. Com deduplicação (IdempotentDeduplicator): O replay mantém a convergência idempotente
   por chave primária e LSN, descartando eventos já processados (effectively-once).
"""
import json
import os
import time

import pytest
from cdc.dedup import AppendConsumer, IdempotentDeduplicator

if os.getenv("CDC_INTEGRATION_TEST") != "1":
    pytest.skip(
        "Requer Kafka/Kafka Connect no ar; execute via `make cdc-semantics` ou defina CDC_INTEGRATION_TEST=1.",
        allow_module_level=True,
    )

kafka = pytest.importorskip("kafka")
KafkaConsumer = kafka.KafkaConsumer
TopicPartition = kafka.TopicPartition

KAFKA_HOST = os.getenv("KAFKA_HOST", "kafka")
KAFKA_PORT = os.getenv("KAFKA_PORT", "9092")
CDC_TOPIC = "inflow.oltp.despesas"
CDC_SLOT = "inflow_despesas_slot"
WAIT_SECONDS = 60


def _wait_until(condition, message):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(1)
    pytest.fail(message)


def _slot_active(db):
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_replication_slots WHERE slot_name = %s AND active;", (CDC_SLOT,)
        )
        found = cursor.fetchone() is not None
    db.rollback()
    return found


def _ensure_events_in_topic(db, consumer, partitions):
    """Garante que existam eventos reais no tópico, gerando UPDATEs se necessário."""
    beginning_offsets = consumer.beginning_offsets(partitions)
    end_offsets = consumer.end_offsets(partitions)
    total_messages = sum(end_offsets[p] - beginning_offsets[p] for p in partitions)

    if total_messages >= 2:
        return []

    with db.cursor() as cursor:
        cursor.execute("SELECT id, valor FROM oltp.despesas ORDER BY id LIMIT 2;")
        rows = cursor.fetchall()
    if len(rows) < 2:
        pytest.skip("Não há despesas suficientes no banco; execute `make ingestion`.")

    revert_actions = []
    for despesa_id, valor_atual in rows:
        novo_valor = round(float(valor_atual) + 0.50, 2)
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE oltp.despesas SET valor = %s WHERE id = %s;", (novo_valor, despesa_id)
            )
        db.commit()
        revert_actions.append((despesa_id, valor_atual))

    return revert_actions


def test_replay_de_mensagens_demonstra_duplicacao_vs_deduplicacao(db):
    """Valida a semântica de entrega lendo o tópico, fazendo seek retroativo (replay)

    e comparando o resultado entre append e deduplicação idempotente.
    """
    _wait_until(lambda: _slot_active(db), f"Replication slot {CDC_SLOT} não ficou ativo.")

    consumer = KafkaConsumer(
        bootstrap_servers=f"{KAFKA_HOST}:{KAFKA_PORT}",
        consumer_timeout_ms=10_000,
        enable_auto_commit=False,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    revert_actions = []
    try:
        _wait_until(lambda: CDC_TOPIC in consumer.topics(), f"Tópico {CDC_TOPIC} não encontrado.")
        partitions = [
            TopicPartition(CDC_TOPIC, p) for p in consumer.partitions_for_topic(CDC_TOPIC)
        ]
        consumer.assign(partitions)

        revert_actions = _ensure_events_in_topic(db, consumer, partitions)
        if revert_actions:
            time.sleep(2)

        # Início da leitura
        consumer.seek_to_beginning(*partitions)
        start_offsets = {p: consumer.position(p) for p in partitions}

        append_consumer = AppendConsumer()
        dedup_consumer = IdempotentDeduplicator(key_field="id")

        # --- 1ª PASSADA: Consumo inicial de N mensagens ---
        primeira_passada_mensagens = []
        for message in consumer:
            payload = message.value.get("payload", message.value)
            primeira_passada_mensagens.append(payload)
            append_consumer.consume(payload)
            dedup_consumer.consume(payload)

        n_mensagens = len(primeira_passada_mensagens)
        assert n_mensagens > 0, "Nenhuma mensagem encontrada no tópico para o teste de replay."

        unicos_passada_1 = dedup_consumer.total_unique
        assert append_consumer.total_processed == n_mensagens
        assert dedup_consumer.duplicates_ignored == 0

        # --- REPLAY: Resetar os offsets para o início (Simula reprocessamento) ---
        for partition, offset in start_offsets.items():
            consumer.seek(partition, offset)

        # --- 2ª PASSADA: Releitura exata das mesmas N mensagens ---
        mensagens_reprocessadas = 0
        for message in consumer:
            payload = message.value.get("payload", message.value)
            mensagens_reprocessadas += 1
            append_consumer.consume(payload)
            dedup_consumer.consume(payload)
            if mensagens_reprocessadas == n_mensagens:
                break

        # --- VALIDAÇÕES DE SEMÂNTICA ---

        # 1. Sem deduplicação (Append): O replay duplica os dados (at-least-once duplica registros)
        assert append_consumer.total_processed == 2 * n_mensagens, (
            "Consumidor append deveria conter o dobro de registros após o replay."
        )

        # 2. Com deduplicação idempotente: O replay preserva exatamente o mesmo total de registros únicos
        assert dedup_consumer.total_received == 2 * n_mensagens
        assert dedup_consumer.total_unique == unicos_passada_1, (
            "Deduplicador idempotente não deveria ter aumentado registros únicos após o replay."
        )
        assert dedup_consumer.duplicates_ignored == n_mensagens, (
            f"Esperava que todas as {n_mensagens} mensagens do replay fossem ignoradas como duplicatas."
        )

    finally:
        consumer.close()
        if revert_actions:
            with db.cursor() as cursor:
                for despesa_id, valor_original in revert_actions:
                    cursor.execute(
                        "UPDATE oltp.despesas SET valor = %s WHERE id = %s;",
                        (valor_original, despesa_id),
                    )
            db.commit()

