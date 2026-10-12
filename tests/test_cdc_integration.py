import json
import os

import pytest
from kafka import KafkaConsumer

pytestmark = pytest.mark.skipif(
    os.getenv("CDC_INTEGRATION_TEST") != "1",
    reason="Requer Kafka/Kafka Connect no ar; rode via `make cdc-test`.",
)

KAFKA_HOST = os.getenv("KAFKA_HOST", "kafka")
KAFKA_PORT = os.getenv("KAFKA_PORT", "9092")
CDC_TOPIC = "inflow.oltp.despesas"


def test_update_em_despesas_propaga_para_o_topico_de_cdc(db):
    with db.cursor() as cursor:
        cursor.execute("SELECT id, valor FROM oltp.despesas ORDER BY id LIMIT 1;")
        row = cursor.fetchone()
    if not row:
        pytest.skip("Não há despesas carregadas; rode `make ingestion` antes do teste de CDC.")

    despesa_id, valor_atual = row
    novo_valor = round(float(valor_atual) + 1.23, 2)

    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE oltp.despesas SET valor = %s WHERE id = %s;", (novo_valor, despesa_id)
        )
    db.commit()

    consumer = KafkaConsumer(
        CDC_TOPIC,
        bootstrap_servers=f"{KAFKA_HOST}:{KAFKA_PORT}",
        auto_offset_reset="earliest",
        group_id=f"cdc-test-{despesa_id}",
        consumer_timeout_ms=30_000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    evento_encontrado = None
    try:
        for message in consumer:
            payload = message.value.get("payload", message.value)
            after = payload.get("after") or {}
            if payload.get("op") == "u" and after.get("id") == despesa_id:
                evento_encontrado = payload
                break
    finally:
        consumer.close()

    assert evento_encontrado is not None, (
        f"Nenhum evento de UPDATE encontrado no tópico {CDC_TOPIC} para a despesa {despesa_id}."
    )
    assert evento_encontrado["op"] == "u"
    assert float(evento_encontrado["after"]["valor"]) == novo_valor
