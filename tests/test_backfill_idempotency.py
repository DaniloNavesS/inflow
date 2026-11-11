"""Reexecutar o mesmo período (backfill) não duplica nem altera despesas já carregadas."""
import pytest

from jobs.expenses import ingest_ceaps_despesas
from monitoring.metrics import finish_pipeline, start_pipeline

ANO = 2100  # limite do CHECK da tabela; sem dados reais: o teste só toca nas linhas que cria
SENADOR_ID, FORNECEDOR_DOC = 990000001, "99999999000199"
DESPESA_IDS = (990000101, 990000102)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, timeout=None):
        return FakeResponse(self.payload)


def _payload():
    return [
        {
            "id": despesa_id, "codSenador": SENADOR_ID, "nomeSenador": "Senador de Teste",
            "cpfCnpj": FORNECEDOR_DOC, "fornecedor": "Fornecedor de Teste",
            "data": f"{ANO}-03-10", "ano": ANO, "mes": 3, "tipoDespesa": "Teste",
            "tipoDocumento": "Nota", "documento": str(despesa_id), "detalhamento": "x",
            "valorReembolsado": valor,
        }
        for despesa_id, valor in zip(DESPESA_IDS, (100.25, 50.75))
    ]


def _snapshot(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*), sum(valor), max(atualizado_em) FROM oltp.despesas WHERE id = ANY(%s)",
            (list(DESPESA_IDS),),
        )
        row = cur.fetchone()
    db.rollback()
    return row


def _cleanup(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM oltp.despesas WHERE id = ANY(%s)", (list(DESPESA_IDS),))
        cur.execute("DELETE FROM oltp.fornecedores WHERE cnpj_cpf = %s", (FORNECEDOR_DOC,))
        cur.execute("DELETE FROM oltp.senadores WHERE id = %s", (SENADOR_ID,))
        cur.execute("DELETE FROM bronze.raw_payloads WHERE ingestion_year = %s", (ANO,))
    db.commit()


def test_reprocessing_same_year_is_idempotent(populated_db):
    db = populated_db
    _cleanup(db)
    session = FakeSession(_payload())
    run_id = start_pipeline(conn=db, pipeline_name="backfill_idempotency_test", ingestion_year=ANO)
    try:
        ingest_ceaps_despesas(session, db, ANO, run_id)
        first = _snapshot(db)
        ingest_ceaps_despesas(session, db, ANO, run_id)
        second = _snapshot(db)

        assert first[0] == 2 and float(first[1]) == pytest.approx(151.0)
        # Mesmas linhas, mesma soma e nenhuma atualização desnecessária.
        assert second == first
    finally:
        db.rollback()
        finish_pipeline(conn=db, run_id=run_id, duration_seconds=0)
        _cleanup(db)
