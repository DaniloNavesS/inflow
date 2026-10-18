"""Script de demonstração de semântica de entrega e replay para eventos CDC.

Executa o consumo do tópico do Kafka (inflow.oltp.despesas), simula um replay
via retrocesso de offset (seek) e exibe uma tabela comparativa evidenciando:
1. Append ingênuo -> duplicação sob entrega at-least-once.
2. Deduplicação por chave e LSN -> convergência para effectively-once.
"""
import json
import os
import sys
import time
from pathlib import Path

# Garante acesso ao módulo ingestion/src tanto localmente quanto dentro do contêiner
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion" / "src"))
if Path("/app/src").is_dir():
    sys.path.insert(0, "/app/src")

from cdc.dedup import AppendConsumer, IdempotentDeduplicator  # noqa: E402

KAFKA_HOST = os.getenv("KAFKA_HOST", "localhost")
KAFKA_PORT = os.getenv("KAFKA_PORT", "9092")
CDC_TOPIC = os.getenv("CDC_TOPIC", "inflow.oltp.despesas")


def run_demo() -> int:
    try:
        from kafka import KafkaConsumer, TopicPartition
        from kafka.errors import NoBrokersAvailable
    except ImportError:
        print("[ERRO] Biblioteca kafka-python não instalada. Execute: pip install kafka-python==2.0.2")
        return 1

    print("=" * 80)
    print(" DEMONSTRAÇÃO DE SEMÂNTICA DE ENTREGA E REPLAY (CDC / DEBEZIUM / KAFKA)")
    print("=" * 80)
    print(f"[*] Conectando ao Kafka em {KAFKA_HOST}:{KAFKA_PORT}...")

    try:
        consumer = KafkaConsumer(
            bootstrap_servers=f"{KAFKA_HOST}:{KAFKA_PORT}",
            consumer_timeout_ms=5000,
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
    except NoBrokersAvailable:
        print(f"[ERRO] Não foi possível conectar ao Kafka em {KAFKA_HOST}:{KAFKA_PORT}.")
        print("[DICA] Certifique-se de que os contêineres estão ativos: make cdc-up && make cdc-register")
        return 1

    try:
        available_topics = consumer.topics()
        if CDC_TOPIC not in available_topics:
            print(f"[AVISO] O tópico '{CDC_TOPIC}' ainda não existe no Kafka.")
            print("[DICA] O conector Debezium cria o tópico na primeira alteração. Execute: make cdc-test")
            return 1

        partitions = [TopicPartition(CDC_TOPIC, p) for p in consumer.partitions_for_topic(CDC_TOPIC)]
        consumer.assign(partitions)
        consumer.seek_to_beginning(*partitions)
        start_offsets = {p: consumer.position(p) for p in partitions}
        end_offsets = consumer.end_offsets(partitions)

        total_available = sum(end_offsets[p] - start_offsets[p] for p in partitions)
        if total_available == 0:
            print(f"[AVISO] O tópico '{CDC_TOPIC}' existe mas não possui mensagens registradas.")
            print("[DICA] Dispare uma alteração no banco com `make cdc-test` e execute novamente.")
            return 1

        print(f"[*] Tópico identificado: {CDC_TOPIC}")
        print(f"[*] Total de mensagens disponíveis na partição: {total_available}")
        print("\n" + "-" * 80)
        print("FASE 1: Consumo Inicial (1ª Passada)")
        print("-" * 80)

        append_consumer = AppendConsumer()
        dedup_consumer = IdempotentDeduplicator(key_field="id")

        mensagens_lidas = []
        for message in consumer:
            payload = message.value.get("payload", message.value)
            mensagens_lidas.append(payload)
            append_consumer.consume(payload)
            dedup_consumer.consume(payload)

        n_mensagens = len(mensagens_lidas)
        print(f"[✓] {n_mensagens} mensagens consumidas com sucesso.")
        print(f"    - AppendConsumer processou: {append_consumer.total_processed}")
        print(f"    - IdempotentDeduplicator únicos: {dedup_consumer.total_unique} (descartes: {dedup_consumer.duplicates_ignored})")

        print("\n" + "-" * 80)
        print("FASE 2: Simulação de Replay (Reset de Offsets / Falha de Consumidor)")
        print("-" * 80)
        print("[*] Retrocedendo ponteiros de leitura (seek) para os offsets iniciais...")
        for partition, offset in start_offsets.items():
            consumer.seek(partition, offset)

        print("[*] Reconsumindo exatamente os mesmos eventos (2ª Passada)...")
        reprocessados = 0
        for message in consumer:
            payload = message.value.get("payload", message.value)
            reprocessados += 1
            append_consumer.consume(payload)
            dedup_consumer.consume(payload)
            if reprocessados == n_mensagens:
                break

        print(f"[✓] {reprocessados} mensagens reprocessadas.")

        print("\n" + "=" * 80)
        print(" RESULTADO COMPARATIVO DA SEMÂNTICA DE ENTREGA")
        print("=" * 80)
        print(f"{'Estratégia de Consumo':<28} | {'Total Lidos':<12} | {'Registros Finais':<16} | {'Duplicatas Ignoradas':<20}")
        print("-" * 80)
        print(f"{'Append (Ingênuo / Log)':<28} | {append_consumer.total_processed:<12} | {append_consumer.total_processed:<16} | {'0 (Duplicou!)':<20}")
        print(f"{'Deduplicação (Chave + LSN)':<28} | {dedup_consumer.total_received:<12} | {dedup_consumer.total_unique:<16} | {f'{dedup_consumer.duplicates_ignored} (Idempotente)':<20}")
        print("=" * 80)
        print("\nDIAGNÓSTICO ARQUITETURAL:")
        print("  • Garantia da Mensageria (Kafka + Debezium): AT-LEAST-ONCE")
        print("    No replay, mensagens são entregues novamente pelo broker.")
        print("  • Garantia da Aplicação Consumidora:        EFFECTIVELY-ONCE")
        print("    A ordenação por LSN e chave primária impede que reprocessamentos corrompam o estado final.\n")

        return 0

    finally:
        consumer.close()


if __name__ == "__main__":
    sys.exit(run_demo())

