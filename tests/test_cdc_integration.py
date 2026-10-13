import json
import os
import time

import pytest

if os.getenv("CDC_INTEGRATION_TEST") != "1":
    pytest.skip(
        "Requer Kafka/Kafka Connect no ar; rode via `make cdc-test`.", allow_module_level=True
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


def test_update_em_despesas_propaga_para_o_topico_de_cdc(db):
    with db.cursor() as cursor:
        cursor.execute("SELECT id, valor FROM oltp.despesas ORDER BY id LIMIT 1;")
        row = cursor.fetchone()
    if not row:
        pytest.skip("Não há despesas carregadas; rode `make ingestion` antes do teste de CDC.")

    despesa_id, valor_atual = row
    novo_valor = round(float(valor_atual) + 1.23, 2)

    _wait_until(lambda: _slot_active(db), f"Replication slot {CDC_SLOT} não ficou ativo.")

    consumer = KafkaConsumer(
        bootstrap_servers=f"{KAFKA_HOST}:{KAFKA_PORT}",
        consumer_timeout_ms=30_000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    evento_encontrado = None
    try:
        _wait_until(lambda: CDC_TOPIC in consumer.topics(), f"Tópico {CDC_TOPIC} não foi criado.")
        partitions = [
            TopicPartition(CDC_TOPIC, p) for p in consumer.partitions_for_topic(CDC_TOPIC)
        ]
        consumer.assign(partitions)
        consumer.seek_to_end(*partitions)
        for partition in partitions:
            consumer.position(partition)

        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE oltp.despesas SET valor = %s WHERE id = %s;", (novo_valor, despesa_id)
            )
        db.commit()

        for message in consumer:
            payload = message.value.get("payload", message.value)
            after = payload.get("after") or {}
            if payload.get("op") == "u" and after.get("id") == despesa_id:
                evento_encontrado = payload
                break
    finally:
        consumer.close()
        db.rollback()
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE oltp.despesas SET valor = %s WHERE id = %s;", (valor_atual, despesa_id)
            )
        db.commit()

    assert evento_encontrado is not None, (
        f"Nenhum evento de UPDATE encontrado no tópico {CDC_TOPIC} para a despesa {despesa_id}."
    )
    assert evento_encontrado["op"] == "u"
    assert float(evento_encontrado["after"]["valor"]) == novo_valor
