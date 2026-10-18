"""Módulo de deduplicação idempotente para eventos de CDC (Debezium/Kafka).

Fornece estratégias de consumo para demonstrar a semântica de entrega:
- AppendConsumer: Acumula cegamente todos os eventos recebidos (gera duplicatas no replay).
- IdempotentDeduplicator: Deduplica eventos usando chave primária e ordenação lógica
  por LSN (Log Sequence Number do Postgres).
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CDCRecord:
    """Representação normalizada de um evento capturado via Debezium."""
    op: str
    key_id: Any
    data: Optional[Dict[str, Any]]
    lsn: Optional[int]
    ts_ms: Optional[int]
    raw_payload: Dict[str, Any]


class AppendConsumer:
    """Consumidor que apenas anexa eventos conforme chegam."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def consume(self, event_payload: Dict[str, Any]) -> None:
        self.events.append(event_payload)

    @property
    def total_processed(self) -> int:
        return len(self.events)


class IdempotentDeduplicator:
    """Consumidor idempotente com deduplicação por chave e LSN.

    Garante semântica de entrega 'effectively-once' mesmo sob 'at-least-once'
    ou reprocessamento (replay) intencional.
    """

    def __init__(self, key_field: str = "id") -> None:
        self.key_field = key_field
        # Mapeia key_id -> (lsn, record_data, is_deleted)
        self._state: Dict[Any, Tuple[int, Optional[Dict[str, Any]], bool]] = {}
        self.total_received: int = 0
        self.duplicates_ignored: int = 0

    def parse_event(self, payload: Dict[str, Any]) -> CDCRecord:
        body = payload.get("payload", payload)
        op = body.get("op", "u")
        after = body.get("after") or {}
        before = body.get("before") or {}
        source = body.get("source") or {}

        # Identifica a chave primária da entidade
        key_id = after.get(self.key_field)
        if key_id is None:
            key_id = before.get(self.key_field)

        # O timestamp é informativo; apenas o LSN ordena versões.
        lsn = source.get("lsn")
        ts_ms = body.get("ts_ms") or source.get("ts_ms") or 0

        data = after if op != "d" else None
        return CDCRecord(
            op=op,
            key_id=key_id,
            data=data,
            lsn=lsn,
            ts_ms=ts_ms,
            raw_payload=body,
        )

    def consume(self, payload: Dict[str, Any]) -> bool:
        """Processa um evento CDC.

        Retorna:
            True se o evento foi aceito/atualizado.
            False se foi descartado como duplicata obsoleta.
        """
        self.total_received += 1
        record = self.parse_event(payload)

        if record.key_id is None:
            return False

        if not isinstance(record.lsn, int) or isinstance(record.lsn, bool):
            raise ValueError("Evento CDC sem LSN válido; não é seguro ordená-lo por timestamp")
        version = record.lsn
        is_deleted = record.op == "d"

        if record.key_id in self._state:
            curr_version, _, _ = self._state[record.key_id]
            # Se a versão for menor ou igual à já processada, descarta
            if version <= curr_version:
                self.duplicates_ignored += 1
                return False

        self._state[record.key_id] = (version, record.data, is_deleted)
        return True

    @property
    def active_records(self) -> Dict[Any, Dict[str, Any]]:
        """Retorna o estado final consolidado dos registros ativos."""
        return {
            k: data
            for k, (_, data, is_deleted) in self._state.items()
            if not is_deleted and data is not None
        }

    @property
    def total_unique(self) -> int:
        return len(self.active_records)

