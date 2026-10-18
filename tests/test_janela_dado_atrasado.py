"""Regra de janela e de dado atrasado das despesas (analytics.vw_despesas_janela_mensal).

Os testes montam uma fonte sintética em tabela temporária, com um fluxo próprio, dentro da
transação da fixture: não dependem das despesas reais nem deixam nada no banco.

Regra: usa data_despesa como tempo de evento quando ela é válida e não posterior à competência;
caso contrário, usa o primeiro dia da competência. Watermark = 1º dia do mês da maior
competência já vista - 2 meses; janela com fim <= watermark está fechada. O watermark que
classifica um lote é o que os lotes anteriores deixaram.

Cenário principal (senador 1, atraso permitido de 2 meses):

    lote 1  competências jan-abr/2024   despesas 1..4, uma por mês, R$ 100 cada
            watermark: nulo -> 2024-02-01  => janeiro FECHADA; fev, mar e abr ABERTAS
    lote 2  competência mai/2024
            despesa 5, data 20/03 (janela aberta)   -> NO_PRAZO, entra no total de março
            despesa 6, data 15/01 (janela fechada)  -> ATRASADO, vira ajuste tardio de janeiro
            watermark: 2024-02-01 -> 2024-03-01     => fevereiro também FECHADA
    lote 3  correções de valor
            despesa 1 (janeiro, fechada)  100 -> 130  -> ATRASADO, ajuste de +30
            despesa 4 (abril, aberta)     100 -> 150  -> NO_PRAZO, total de abril vai a 150
"""
import datetime
from decimal import Decimal

import pytest

import jobs.late_data as late_data
from jobs.late_data import processar_lote, reiniciar_fluxo

FLUXO = "teste_janela"
FONTE = "despesas_janela_teste"
JAN, FEV, MAR, ABR = (datetime.date(2024, mes, 1) for mes in (1, 2, 3, 4))


@pytest.fixture
def fonte(db):
    with db.cursor() as cursor:
        cursor.execute("SELECT to_regclass('analytics.janela_controle') IS NOT NULL")
        assert cursor.fetchone()[0], "Esquema das janelas ausente; rode `make migrate-janela`."
        cursor.execute(f"""
            CREATE TEMP TABLE {FONTE} (
                id BIGINT PRIMARY KEY,
                senador_id INT NOT NULL,
                data_despesa DATE NOT NULL,
                ano SMALLINT NOT NULL,
                mes SMALLINT NOT NULL,
                valor NUMERIC(14, 2) NOT NULL
            ) ON COMMIT DROP
        """)
    return db


def inserir(db, despesa_id, data, competencia, valor=100, senador_id=1):
    ano, mes = competencia
    with db.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {FONTE} VALUES (%s, %s, %s, %s, %s, %s)",
            (despesa_id, senador_id, data, ano, mes, valor),
        )


def corrigir(db, despesa_id, **colunas):
    atribuicoes = ", ".join(f"{coluna} = %s" for coluna in colunas)
    with db.cursor() as cursor:
        cursor.execute(
            f"UPDATE {FONTE} SET {atribuicoes} WHERE id = %s", (*colunas.values(), despesa_id)
        )


def lote(db):
    return processar_lote(db, fluxo=FLUXO, fonte=FONTE, atraso_meses=2)


def janelas(db):
    """{janela_inicio: (situacao, total_no_prazo, ajuste_tardio, total_revisado)}"""
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT janela_inicio, situacao, total_no_prazo, ajuste_tardio, total_revisado
            FROM analytics.vw_despesas_janela_mensal
            WHERE fluxo = %s AND senador_id = 1
            ORDER BY janela_inicio
            """,
            (FLUXO,),
        )
        return {linha[0]: linha[1:] for linha in cursor.fetchall()}


def lote_1(db):
    inserir(db, 1, "2024-01-10", (2024, 1))
    inserir(db, 2, "2024-02-10", (2024, 2))
    inserir(db, 3, "2024-03-10", (2024, 3))
    inserir(db, 4, "2024-04-10", (2024, 4))
    return lote(db)


def lote_2(db):
    inserir(db, 5, "2024-03-20", (2024, 5))
    inserir(db, 6, "2024-01-15", (2024, 5))
    return lote(db)


def test_primeiro_lote_entra_no_prazo_e_fecha_as_janelas_alem_do_atraso_permitido(fonte):
    resultado = lote_1(fonte)

    assert (resultado["no_prazo"], resultado["atrasados"]) == (4, 0)
    assert resultado["watermark_anterior"] is None
    assert resultado["watermark"] == FEV
    assert janelas(fonte) == {
        JAN: ("FECHADA", 100, 0, 100),
        FEV: ("ABERTA", 100, 0, 100),
        MAR: ("ABERTA", 100, 0, 100),
        ABR: ("ABERTA", 100, 0, 100),
    }


def test_dado_dentro_do_atraso_permitido_entra_na_janela_ainda_aberta(fonte):
    lote_1(fonte)
    lote_2(fonte)

    situacao, total_no_prazo, ajuste_tardio, _ = janelas(fonte)[MAR]
    assert (total_no_prazo, ajuste_tardio) == (200, 0)
    assert situacao == "ABERTA"


def test_dado_atrasado_nao_altera_o_total_fechado_e_vira_ajuste_tardio(fonte):
    lote_1(fonte)
    resultado = lote_2(fonte)

    assert (resultado["no_prazo"], resultado["atrasados"]) == (1, 1)
    assert janelas(fonte)[JAN] == ("FECHADA", 100, 100, 200)
    # O dado atrasado não é descartado: fica rastreável na saída lateral.
    with fonte.cursor() as cursor:
        cursor.execute(
            """
            SELECT despesa_id, janela_inicio, delta_valor, motivo, watermark_no_lote
            FROM analytics.janela_despesas_lancamentos
            WHERE fluxo = %s AND classificacao = 'ATRASADO'
            """,
            (FLUXO,),
        )
        assert cursor.fetchall() == [(6, JAN, Decimal("100.00"), "INSERCAO", FEV)]


def test_watermark_avanca_com_a_competencia_e_fecha_a_proxima_janela(fonte):
    lote_1(fonte)
    resultado = lote_2(fonte)

    assert (resultado["watermark_anterior"], resultado["watermark"]) == (FEV, MAR)
    assert [situacao for situacao, *_ in janelas(fonte).values()] == [
        "FECHADA", "FECHADA", "ABERTA", "ABERTA",
    ]


def test_correcao_em_janela_fechada_e_ajuste_tardio_e_em_janela_aberta_revisa_o_total(fonte):
    lote_1(fonte)
    lote_2(fonte)
    corrigir(fonte, 1, valor=130)
    corrigir(fonte, 4, valor=150)
    resultado = lote(fonte)

    # Cada correção gera um estorno e um novo lançamento.
    assert (resultado["despesas"], resultado["no_prazo"], resultado["atrasados"]) == (2, 2, 2)
    assert janelas(fonte)[JAN] == ("FECHADA", 100, 130, 230)
    assert janelas(fonte)[ABR] == ("ABERTA", 150, 0, 150)


def test_reprocessar_sem_mudanca_na_origem_nao_gera_lancamentos(fonte):
    lote_1(fonte)
    lote_2(fonte)
    antes = janelas(fonte)
    resultado = lote(fonte)

    assert (resultado["despesas"], resultado["no_prazo"], resultado["atrasados"]) == (0, 0, 0)
    assert janelas(fonte) == antes


def test_total_revisado_sempre_bate_com_a_origem(fonte):
    lote_1(fonte)
    lote_2(fonte)
    corrigir(fonte, 1, valor=130)
    corrigir(fonte, 2, data_despesa="2024-04-02", ano=2024, mes=4)
    lote(fonte)

    with fonte.cursor() as cursor:
        cursor.execute(f"""
            SELECT date_trunc('month', data_despesa)::date, sum(valor)
            FROM {FONTE} GROUP BY 1
        """)
        origem = dict(cursor.fetchall())
    revisado = {janela: linha[3] for janela, linha in janelas(fonte).items() if linha[3] != 0}
    assert revisado == origem


def test_watermark_nao_recua_quando_chega_competencia_antiga(fonte):
    lote_1(fonte)
    inserir(fonte, 7, "2023-11-05", (2023, 11))
    resultado = lote(fonte)

    assert resultado["watermark"] == FEV
    assert resultado["atrasados"] == 1


def test_lote_vazio_nao_avanca_watermark_antes_de_despesa_antiga(fonte):
    vazio = lote(fonte)

    assert vazio["despesas"] == 0
    assert vazio["watermark_anterior"] is None
    assert vazio["watermark"] is None

    inserir(fonte, 10, "2024-04-10", (2024, 4))
    resultado = lote(fonte)

    assert (resultado["watermark_anterior"], resultado["no_prazo"], resultado["atrasados"]) == (
        None, 1, 0,
    )
    assert resultado["watermark"] == datetime.date(2024, 2, 1)


def test_data_de_documento_invalida_usa_a_competencia_como_tempo_de_evento(fonte):
    inserir(fonte, 8, "0202-07-04", (2024, 4))
    lote(fonte)

    assert list(janelas(fonte)) == [ABR]
    with fonte.cursor() as cursor:
        cursor.execute(
            "SELECT origem_tempo_evento FROM analytics.janela_despesas_lancamentos"
            " WHERE fluxo = %s",
            (FLUXO,),
        )
        assert cursor.fetchall() == [("COMPETENCIA",)]


def test_data_de_documento_no_futuro_nao_adianta_o_watermark(fonte):
    lote_1(fonte)
    inserir(fonte, 9, "2025-12-31", (2024, 4))  # erro de digitação no ano do documento
    resultado = lote(fonte)

    assert resultado["watermark"] == FEV
    assert resultado["atrasados"] == 0
    with fonte.cursor() as cursor:
        cursor.execute(
            "SELECT janela_inicio, classificacao, origem_tempo_evento"
            " FROM analytics.janela_despesas_lancamentos"
            " WHERE fluxo = %s AND despesa_id = 9 AND delta_quantidade = 1",
            (FLUXO,),
        )
        assert cursor.fetchone() == (ABR, "NO_PRAZO", "COMPETENCIA")


def test_reiniciar_o_fluxo_reprocessa_tudo_como_um_unico_lote_no_prazo(fonte):
    lote_1(fonte)
    lote_2(fonte)
    reiniciar_fluxo(fonte, FLUXO)
    resultado = lote(fonte)

    assert (resultado["lote"], resultado["no_prazo"], resultado["atrasados"]) == (1, 6, 0)
    assert janelas(fonte)[JAN] == ("FECHADA", 200, 0, 200)


def test_reinicio_nao_faz_commit_se_reprocessamento_falha(monkeypatch):
    chamadas = []

    class Connection:
        def commit(self):
            chamadas.append("commit")

    def apagar_estado(_conn):
        chamadas.append("reset")

    def falhar_no_reprocessamento(_conn):
        chamadas.append("processamento")
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(late_data, "reiniciar_fluxo", apagar_estado)
    monkeypatch.setattr(late_data, "processar_lote", falhar_no_reprocessamento)

    with pytest.raises(RuntimeError, match="falha simulada"):
        late_data.process_expense_windows(Connection(), reiniciar=True)

    assert chamadas == ["reset", "processamento"]
