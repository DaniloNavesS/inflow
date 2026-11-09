"""Painel Streamlit do Mandato Aberto: CEAPS."""
import pandas as pd
import plotly.express as px
import streamlit as st

import consultas

st.set_page_config(page_title="Mandato Aberto: CEAPS", layout="wide")

FORMATO_DATA = "%d/%m/%Y %H:%M"


@st.cache_data(ttl=300)
def c_ultima_atualizacao():
    return consultas.ultima_atualizacao()


@st.cache_data(ttl=300)
def c_opcoes():
    return consultas.opcoes_filtros()


@st.cache_data(ttl=300)
def c_media_senador(filtros):
    return consultas.media_mensal_senador(filtros)


@st.cache_data(ttl=300)
def c_media_grupo(grupo, filtros):
    return consultas.media_mensal_por_grupo(grupo, filtros)


@st.cache_data(ttl=300)
def c_fora_grupo(grupo, filtros):
    return consultas.competencias_fora_do_grupo(grupo, filtros)


@st.cache_data(ttl=300)
def c_maior_categoria(filtros):
    return consultas.maior_categoria(filtros)


@st.cache_data(ttl=300)
def c_gasto_mensal(filtros):
    return consultas.gasto_mensal(filtros)


def formatar(valor):
    return "indisponível" if pd.isna(valor) else pd.Timestamp(valor).strftime(FORMATO_DATA)


def moeda(df, colunas):
    return df.style.format({c: "R$ {:,.2f}" for c in colunas}, na_rep="")


st.title("Mandato Aberto: CEAPS")

try:
    datas = c_ultima_atualizacao().iloc[0]
    opcoes = c_opcoes()
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
st.info(
    "Nas perguntas 4 e 10, partido e UF são os oficiais de cada mês. Nas demais seções, "
    "são os atuais de cada senador, não os vigentes na data de cada despesa."
)

with st.sidebar:
    st.header("Filtros")
    anos = st.multiselect("Ano", opcoes["anos"]["ano"].tolist())
    partidos = st.multiselect("Partido", opcoes["partidos"]["partido"].tolist())
    ufs = st.multiselect("UF", opcoes["ufs"]["uf"].tolist())
    nomes_sen = dict(zip(opcoes["senadores"]["senador_id"], opcoes["senadores"]["nome"]))
    senadores = st.multiselect("Senador", list(nomes_sen), format_func=nomes_sen.get)
    nomes_cat = dict(zip(opcoes["categorias"]["categoria_id"], opcoes["categorias"]["tipo_despesa"]))
    categorias = st.multiselect("Categoria", list(nomes_cat), format_func=nomes_cat.get)
    st.caption("Sem seleção, o filtro considera todos os valores.")

filtros = {
    "anos": [int(a) for a in anos],
    "partidos": partidos,
    "ufs": ufs,
    "senadores": [int(s) for s in senadores],
    "categorias": [str(c) for c in categorias],
}

try:
    st.header("Pergunta 1: média mensal de gasto por senador")
    st.caption("Média entre os meses com despesas. O filtro de categoria não se aplica a esta seção.")
    df1 = c_media_senador(filtros)
    if df1.empty:
        st.warning("Sem dados para os filtros escolhidos.")
    else:
        topo = df1.head(30)
        st.plotly_chart(
            px.bar(topo, x="media_mensal", y="nome", color="partido_atual", orientation="h",
                   labels={"media_mensal": "Média mensal (R$)", "nome": "Senador", "partido_atual": "Partido"},
                   title="Maiores médias mensais (até 30 senadores)")
            .update_yaxes(autorange="reversed"),
            width="stretch",
        )
        st.dataframe(moeda(df1, ["valor_total", "media_mensal"]), width="stretch", hide_index=True)

    for numero, grupo, rotulo in ((4, "partido", "partido"), (10, "uf", "UF")):
        st.header(f"Pergunta {numero}: média mensal por {rotulo}")
        st.caption(
            f"Gasto médio por senador-mês, usando o {rotulo} oficial de cada competência "
            "(histórico de mandatos e filiações), não o atual. Entram só meses com lançamentos, "
            f"senador em exercício e {rotulo} único no mês. O filtro de categoria não se aplica."
        )
        dfg = c_media_grupo(grupo, filtros)
        if dfg.empty:
            st.warning("Sem dados para os filtros escolhidos.")
        else:
            dfg = dfg.assign(ano=dfg["ano"].astype(str))
            st.plotly_chart(
                px.bar(dfg, x="grupo", y="media_mensal", color="ano", barmode="group",
                       labels={"grupo": rotulo.capitalize(), "media_mensal": "Média por senador-mês (R$)",
                               "ano": "Ano"}),
                width="stretch",
            )
            st.dataframe(moeda(dfg, ["valor_total", "media_mensal"]), width="stretch", hide_index=True)
        fora = c_fora_grupo(grupo, filtros)
        if not fora.empty:
            with st.expander(f"Competências fora do cálculo por {rotulo} ({int(fora['competencias'].sum())})"):
                st.caption(
                    "MULTIPLOS: mais de um valor no mês; SEM_EXERCICIO: sem exercício confirmado; "
                    "NAO_COLETADO: ano sem contexto histórico. Os filtros de partido e UF não se aplicam aqui."
                )
                st.dataframe(moeda(fora, ["valor_total"]), width="stretch", hide_index=True)

    st.header("Pergunta 11: categoria de maior gasto por senador")
    st.caption("Em caso de empate, o senador aparece em mais de uma linha.")
    df11 = c_maior_categoria(filtros)
    if df11.empty:
        st.warning("Sem dados para os filtros escolhidos.")
    else:
        resumo = df11.groupby("tipo_despesa", as_index=False)["senador_id"].nunique()
        resumo = resumo.rename(columns={"senador_id": "senadores"}).sort_values("senadores")
        st.plotly_chart(
            px.bar(resumo, x="senadores", y="tipo_despesa", orientation="h",
                   labels={"senadores": "Senadores", "tipo_despesa": "Categoria"}),
            width="stretch",
        )
        st.dataframe(moeda(df11, ["valor_total", "valor_total_ano"]), width="stretch", hide_index=True)

    st.header("Gasto mensal")
    dfm = c_gasto_mensal(filtros)
    if dfm.empty:
        st.warning("Sem dados para os filtros escolhidos.")
    else:
        dfm = dfm.assign(periodo=pd.to_datetime(dict(year=dfm["ano"], month=dfm["mes"], day=1)))
        st.plotly_chart(
            px.line(dfm, x="periodo", y="valor_total", markers=True,
                    labels={"periodo": "Mês", "valor_total": "Gasto (R$)"}),
            width="stretch",
        )
        st.dataframe(moeda(dfm.drop(columns="periodo"), ["valor_total"]), width="stretch", hide_index=True)
except Exception as erro:
    st.error(
        "Falha ao consultar o banco. Verifique o PostgreSQL (`make start`) e os modelos (`make models`)."
    )
    st.caption(f"Detalhe técnico: {type(erro).__name__}")
