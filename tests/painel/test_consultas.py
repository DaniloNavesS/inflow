"""Confere as consultas do painel contra SQL direto nos marts publicados.

Roda no contêiner do painel (`make test-painel`), que tem consultas.py em /app. Os testes são
pulados se o PostgreSQL estiver fora do ar ou se os modelos não tiverem sido publicados.
"""
import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).parents[2] / "painel"))

import consultas  # noqa: E402

TOLERANCIA = 0.005  # meio centavo: as consultas convertem NUMERIC para float


@pytest.fixture(scope="module")
def sql():
    try:
        conn = consultas.conectar()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponível: {exc}")
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('analytics_marts.gestao_comparacao_despesas_mensais')")
        if cur.fetchone()[0] is None:
            conn.close()
            pytest.skip("Modelos não publicados: rode make models")

    def executar(consulta, params=None):
        with conn.cursor() as cur:
            cur.execute(consulta, params)
            return cur.fetchall()

    yield executar
    conn.close()


def escalar(sql, consulta, params=None):
    valor = sql(consulta, params)[0][0]
    return float(valor) if valor is not None else None


def test_conexao_rejeita_escrita(sql):
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        consultas._consultar("CREATE TABLE analytics_marts.painel_nao_deve_existir (i int)")


def test_grupo_invalido_e_rejeitado_antes_do_sql():
    with pytest.raises(ValueError):
        consultas.media_mensal_por_grupo("partido_atual; DROP TABLE x")


def test_media_mensal_senador_reproduz_o_mart(sql):
    df = consultas.media_mensal_senador()
    linhas, soma = sql("SELECT count(*), sum(media_mensal) FROM analytics_marts.gestao_media_mensal")[0]
    assert len(df) == linhas
    assert df["media_mensal"].sum() == pytest.approx(float(soma), abs=TOLERANCIA * linhas)


@pytest.mark.parametrize("grupo,coluna,status", [
    ("partido", "partido_competencia", "status_partido"),
    ("uf", "uf_competencia", "status_uf"),
])
def test_media_por_grupo_confere_com_os_lancamentos(sql, grupo, coluna, status):
    """Recalcula a partir de fct_despesas + contexto, sem passar por fct_despesas_mensais."""
    esperado = {
        (g, ano): float(media) for g, ano, media in sql(f"""
            SELECT c.{coluna}, d.ano, sum(d.valor) / count(DISTINCT (d.senador_id, d.mes))
            FROM analytics_marts.fct_despesas d
            JOIN analytics_marts.dim_contexto_parlamentar_mensal c USING (senador_id, ano, mes)
            WHERE c.dias_exercicio > 0 AND c.{status} = 'UNICO' AND c.{coluna} IS NOT NULL
            GROUP BY 1, 2""")
    }
    df = consultas.media_mensal_por_grupo(grupo)
    obtido = {(r.grupo, r.ano): r.media_mensal for r in df.itertuples()}
    assert obtido.keys() == esperado.keys()
    for chave, media in esperado.items():
        assert obtido[chave] == pytest.approx(media, abs=TOLERANCIA)


@pytest.mark.parametrize("grupo", ["partido", "uf"])
def test_grupos_e_competencias_fora_cobrem_todo_o_gasto(sql, grupo):
    total = escalar(sql, "SELECT sum(valor_total) FROM analytics_marts.fct_despesas_mensais")
    dentro = consultas.media_mensal_por_grupo(grupo)["valor_total"].sum()
    fora = consultas.competencias_fora_do_grupo(grupo)["valor_total"].sum()
    assert dentro + fora == pytest.approx(total, abs=0.01)


def test_resumo_da_pergunta_central_reconcilia_com_o_mart(sql):
    df = consultas.comparacao_resumo()
    total, dif_partido, dif_uf = sql("""
        SELECT sum(valor_total),
               sum(diferenca_media_partido) FILTER (WHERE status_comparacao_partido = 'COMPARAVEL'),
               sum(diferenca_media_uf) FILTER (WHERE status_comparacao_uf = 'COMPARAVEL')
        FROM analytics_marts.gestao_comparacao_despesas_mensais WHERE em_exercicio_no_mes""")[0]
    assert df["valor_total"].sum() == pytest.approx(float(total), abs=0.01)
    assert df["diferenca_acumulada_partido"].sum() == pytest.approx(float(dif_partido), abs=0.01)
    assert df["diferenca_acumulada_uf"].sum() == pytest.approx(float(dif_uf), abs=0.01)


def test_detalhe_da_pergunta_central_nao_mostra_desvio_sem_pares(sql):
    df = consultas.comparacao_mensal()
    sem_comparacao = df[df["status_comparacao_partido"] != "COMPARAVEL"]
    assert sem_comparacao["diferenca_media_partido"].isna().all()
    assert len(df) == escalar(sql, """
        SELECT count(*) FROM analytics_marts.gestao_comparacao_despesas_mensais WHERE em_exercicio_no_mes""")


def test_filtro_de_senador_restringe_a_pergunta_central(sql):
    senador = int(sql("""SELECT senador_id FROM analytics_marts.gestao_comparacao_despesas_mensais
                         WHERE em_exercicio_no_mes ORDER BY senador_id LIMIT 1""")[0][0])
    df = consultas.comparacao_mensal({"senadores": [senador]})
    assert not df.empty and set(df["senador_id"]) == {senador}


def test_maior_categoria_reproduz_o_mart(sql):
    assert len(consultas.maior_categoria()) == escalar(
        sql, "SELECT count(*) FROM analytics_marts.gestao_maior_categoria")


def test_gasto_mensal_soma_todos_os_lancamentos(sql):
    total = escalar(sql, "SELECT sum(valor) FROM analytics_marts.fct_despesas")
    assert consultas.gasto_mensal()["valor_total"].sum() == pytest.approx(total, abs=0.01)


def test_filtro_de_categoria_no_gasto_mensal(sql):
    categoria, total = sql("""SELECT categoria_id, sum(valor) FROM analytics_marts.fct_despesas
                              GROUP BY 1 ORDER BY 2 DESC LIMIT 1""")[0]
    df = consultas.gasto_mensal({"categorias": [categoria]})
    assert df["valor_total"].sum() == pytest.approx(float(total), abs=0.01)


def test_maiores_fornecedores_conferem_com_os_lancamentos(sql):
    esperado = sql("""SELECT fornecedor_id, sum(valor) FROM analytics_marts.fct_despesas
                      GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5""")
    df = consultas.maiores_fornecedores(limite=5)
    assert list(df["fornecedor_id"]) == [f for f, _ in esperado]
    assert list(df["valor_total"]) == pytest.approx([float(v) for _, v in esperado], abs=0.01)


@pytest.mark.parametrize("funcao,mart", [
    (consultas.comissoes_por_senador, "gestao_comissoes_senador"),
    (consultas.estrutura_gabinete, "fct_estrutura_gabinete"),
    (consultas.presencas_documentadas, "gestao_presencas_documentadas"),
])
def test_secoes_institucionais_trazem_todas_as_linhas(sql, funcao, mart):
    assert len(funcao()) == escalar(sql, f"SELECT count(*) FROM analytics_marts.{mart}")


def test_app_renderiza_todas_as_secoes_sem_erro(sql):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(consultas.__file__).with_name("app.py"))).run(timeout=120)
    assert not at.exception
    assert not at.error
    assert [t.label for t in at.tabs] == ["Gastos (CEAPS)", "Comissões e gabinete", "Presença"]
