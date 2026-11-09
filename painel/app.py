"""Painel Streamlit do Mandato Aberto: CEAPS e atuação parlamentar."""
import pandas as pd
import plotly.express as px
import streamlit as st

import consultas

st.set_page_config(page_title="Mandato Aberto", layout="wide")

FORMATO_DATA = "%d/%m/%Y %H:%M"


@st.cache_data(ttl=300)
def consultar(nome, *args):
    """Cache único para as funções de consultas.py (argumentos são hasheados pelo Streamlit)."""
    return getattr(consultas, nome)(*args)


def formatar(valor):
    return "indisponível" if pd.isna(valor) else pd.Timestamp(valor).strftime(FORMATO_DATA)


def tabela(df, moeda=(), percentual=()):
    formatos = {c: "R$ {:,.2f}" for c in moeda}
    formatos.update({c: "{:.1f}%" for c in percentual})
    st.dataframe(df.style.format(formatos, na_rep="—"), width="stretch", hide_index=True)


def sem_dados(df):
    if df.empty:
        st.warning("Sem dados para os filtros escolhidos.")
        return True
    return False


# ---------------------------------------------------------------- Gastos CEAPS

def secao_pergunta_central(filtros):
    st.header("Pergunta central: gasto mensal comparado aos pares de partido e UF")
    st.caption(
        "Para cada mês com lançamentos, o gasto do senador é comparado à média dos **outros** senadores "
        "do mesmo partido (ou UF) oficial naquele mês que também tiveram lançamentos. Diferença acima da "
        "média é um indicador aritmético, não indica irregularidade. Partido e UF são os da competência; "
        "o filtro de categoria não se aplica."
    )
    resumo = consultar("comparacao_resumo", filtros)
    if sem_dados(resumo):
        return
    mensal = consultar("comparacao_mensal", filtros)

    if len(filtros["senadores"]) == 1:
        serie = mensal.assign(periodo=pd.to_datetime(mensal["competencia"]))
        serie = serie.melt(
            id_vars="periodo", value_vars=["valor_total", "media_pares_partido", "media_pares_uf"],
            var_name="serie", value_name="valor",
        )
        nomes = {"valor_total": "Senador", "media_pares_partido": "Média dos pares do partido",
                 "media_pares_uf": "Média dos pares da UF"}
        serie["serie"] = serie["serie"].map(nomes)
        st.plotly_chart(
            px.line(serie, x="periodo", y="valor", color="serie", markers=True,
                    labels={"periodo": "Competência", "valor": "Gasto (R$)", "serie": ""},
                    title=f"{mensal['nome'].iloc[0]}: gasto mensal e médias dos pares"),
            width="stretch",
        )
    else:
        topo = resumo.dropna(subset=["diferenca_acumulada_partido"]).head(20)
        st.plotly_chart(
            px.bar(topo, x="diferenca_acumulada_partido", y="nome", orientation="h", color="partidos_no_ano",
                   labels={"diferenca_acumulada_partido": "Diferença acumulada vs. pares do partido (R$)",
                           "nome": "Senador", "partidos_no_ano": "Partido"},
                   title="Maiores diferenças acumuladas em relação aos pares do partido (até 20)")
            .update_yaxes(autorange="reversed"),
            width="stretch",
        )
        st.caption("Selecione um único senador no filtro para ver a série mensal contra as médias dos pares.")

    st.subheader("Resumo por senador e ano")
    st.caption(
        "A diferença acumulada soma, em reais, só os meses com comparação válida (`COMPARAVEL`). "
        "Percentuais não são somados."
    )
    tabela(resumo, moeda=["valor_total", "diferenca_acumulada_partido", "diferenca_acumulada_uf"])

    with st.expander(f"Detalhe mensal ({len(mensal)} competências)"):
        st.caption(
            "`SEM_PARES`: nenhum outro senador do grupo com lançamentos no mês; `MULTIPLOS`: mais de um "
            "partido no mês. Nesses casos média, diferença e percentual ficam vazios (não são desvio zero)."
        )
        tabela(
            mensal,
            moeda=["valor_total", "media_pares_partido", "diferenca_media_partido",
                   "media_pares_uf", "diferenca_media_uf"],
            percentual=["desvio_percentual_partido", "desvio_percentual_uf"],
        )


def secao_pergunta_1(filtros):
    st.header("Pergunta 1: média mensal de gasto por senador")
    st.caption("Média entre os meses com despesas. Partido e UF atuais. O filtro de categoria não se aplica.")
    df = consultar("media_mensal_senador", filtros)
    if sem_dados(df):
        return
    st.plotly_chart(
        px.bar(df.head(30), x="media_mensal", y="nome", color="partido_atual", orientation="h",
               labels={"media_mensal": "Média mensal (R$)", "nome": "Senador", "partido_atual": "Partido"},
               title="Maiores médias mensais (até 30 senadores)")
        .update_yaxes(autorange="reversed"),
        width="stretch",
    )
    tabela(df, moeda=["valor_total", "media_mensal"])


def secao_grupos(filtros):
    for numero, grupo, rotulo in ((4, "partido", "partido"), (10, "uf", "UF")):
        st.header(f"Pergunta {numero}: média mensal por {rotulo}")
        st.caption(
            f"Gasto médio por senador-mês, usando o {rotulo} oficial de cada competência "
            "(histórico de mandatos e filiações), não o atual. Entram só meses com lançamentos, "
            f"senador em exercício e {rotulo} único no mês. O filtro de categoria não se aplica."
        )
        df = consultar("media_mensal_por_grupo", grupo, filtros)
        if not sem_dados(df):
            df = df.assign(ano=df["ano"].astype(str))
            st.plotly_chart(
                px.bar(df, x="grupo", y="media_mensal", color="ano", barmode="group",
                       labels={"grupo": rotulo.capitalize(), "media_mensal": "Média por senador-mês (R$)",
                               "ano": "Ano"}),
                width="stretch",
            )
            tabela(df, moeda=["valor_total", "media_mensal"])
        fora = consultar("competencias_fora_do_grupo", grupo, filtros)
        if not fora.empty:
            with st.expander(f"Competências fora do cálculo por {rotulo} ({int(fora['competencias'].sum())})"):
                st.caption(
                    "MULTIPLOS: mais de um valor no mês; SEM_EXERCICIO: sem exercício confirmado; "
                    "NAO_COLETADO: ano sem contexto histórico. Os filtros de partido e UF não se aplicam aqui."
                )
                tabela(fora, moeda=["valor_total"])


def secao_pergunta_11(filtros):
    st.header("Pergunta 11: categoria de maior gasto por senador")
    st.caption("Em caso de empate, o senador aparece em mais de uma linha. Partido e UF atuais.")
    df = consultar("maior_categoria", filtros)
    if sem_dados(df):
        return
    resumo = df.groupby("tipo_despesa", as_index=False)["senador_id"].nunique()
    resumo = resumo.rename(columns={"senador_id": "senadores"}).sort_values("senadores")
    st.plotly_chart(
        px.bar(resumo, x="senadores", y="tipo_despesa", orientation="h",
               labels={"senadores": "Senadores", "tipo_despesa": "Categoria"}),
        width="stretch",
    )
    tabela(df, moeda=["valor_total", "valor_total_ano"], percentual=["percentual_total_ano"])


def secao_gasto_mensal(filtros):
    st.header("Gasto mensal")
    st.caption("Soma dos lançamentos por competência. Partido e UF atuais.")
    df = consultar("gasto_mensal", filtros)
    if sem_dados(df):
        return
    df = df.assign(periodo=pd.to_datetime(dict(year=df["ano"], month=df["mes"], day=1)))
    st.plotly_chart(
        px.line(df, x="periodo", y="valor_total", markers=True,
                labels={"periodo": "Mês", "valor_total": "Gasto (R$)"}),
        width="stretch",
    )
    tabela(df.drop(columns="periodo"), moeda=["valor_total"])


# ---------------------------------------------------------------- Página

st.title("Mandato Aberto")

try:
    datas = consultar("ultima_atualizacao").iloc[0]
    opcoes = consultar("opcoes_filtros")
except Exception as erro:
    st.error(
        "Não foi possível ler os dados. Verifique se o PostgreSQL está no ar (`make start`) "
        "e se os modelos foram publicados (`make models`; o schema `analytics_marts` precisa existir)."
    )
    st.caption(f"Detalhe técnico: {type(erro).__name__}")
    st.stop()

col1, col2 = st.columns(2)
col1.caption(f"Dados coletados em {formatar(datas['coleta'])}")
col2.caption(f"Modelos atualizados em {formatar(datas['modelos'])}")

with st.sidebar:
    st.header("Filtros")
    anos = st.multiselect("Ano", opcoes["anos"]["ano"].tolist())
    partidos = st.multiselect("Partido", opcoes["partidos"]["partido"].tolist())
    ufs = st.multiselect("UF", opcoes["ufs"]["uf"].tolist())
    nomes_sen = dict(zip(opcoes["senadores"]["senador_id"], opcoes["senadores"]["nome"]))
    senadores = st.multiselect("Senador", list(nomes_sen), format_func=nomes_sen.get)
    nomes_cat = dict(zip(opcoes["categorias"]["categoria_id"], opcoes["categorias"]["tipo_despesa"]))
    categorias = st.multiselect("Categoria", list(nomes_cat), format_func=nomes_cat.get)
    st.caption(
        "Sem seleção, o filtro considera todos os valores. Cada seção informa se usa partido/UF "
        "da competência (histórico oficial) ou atuais (cadastro do senador)."
    )

filtros = {
    "anos": [int(a) for a in anos],
    "partidos": partidos,
    "ufs": ufs,
    "senadores": [int(s) for s in senadores],
    "categorias": [str(c) for c in categorias],
}

ABAS = {
    "Gastos (CEAPS)": (secao_pergunta_central, secao_pergunta_1, secao_grupos,
                       secao_pergunta_11, secao_gasto_mensal),
}

for aba, secoes in zip(st.tabs(list(ABAS)), ABAS.values()):
    with aba:
        for secao in secoes:
            try:
                secao(filtros)
            except Exception as erro:
                st.error("Falha ao consultar o banco. Verifique o PostgreSQL (`make start`) e os modelos (`make models`).")
                st.caption(f"Detalhe técnico: {type(erro).__name__}")
