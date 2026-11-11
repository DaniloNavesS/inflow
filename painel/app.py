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


def barras_horizontais(df, x, y, titulo, labels, color=None, hover_data=None):
    """Barras na ordem do DataFrame (não agrupadas por cor) e com todos os rótulos visíveis."""
    fig = px.bar(df, x=x, y=y, color=color, orientation="h", title=titulo, labels=labels,
                 hover_data=hover_data, category_orders={y: list(dict.fromkeys(df[y]))},
                 height=max(320, 26 * df[y].nunique() + 140))
    fig.update_yaxes(dtick=1)
    st.plotly_chart(fig, width="stretch")


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
                    color_discrete_map={"Senador": "#111827", "Média dos pares do partido": "#2563eb",
                                        "Média dos pares da UF": "#ea580c"},
                    labels={"periodo": "Competência", "valor": "Gasto (R$)", "serie": ""},
                    title=f"{mensal['nome'].iloc[0]}: gasto mensal e médias dos pares"),
            width="stretch",
        )
    else:
        topo = resumo.dropna(subset=["diferenca_acumulada_partido"]).head(20)
        barras_horizontais(
            topo, "diferenca_acumulada_partido", "nome", color="partidos_no_ano",
            titulo="Maiores diferenças acumuladas em relação aos pares do partido (até 20)",
            labels={"diferenca_acumulada_partido": "Diferença acumulada vs. pares do partido (R$)",
                    "nome": "Senador", "partidos_no_ano": "Partido"},
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
    barras_horizontais(
        df.head(30), "media_mensal", "nome", color="partido_atual",
        titulo="Maiores médias mensais (até 30 senadores)",
        labels={"media_mensal": "Média mensal (R$)", "nome": "Senador", "partido_atual": "Partido"},
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
    resumo = resumo.rename(columns={"senador_id": "senadores"})
    barras_horizontais(
        resumo.sort_values("senadores", ascending=False), "senadores", "tipo_despesa",
        titulo="Quantos senadores têm cada categoria como a maior",
        labels={"senadores": "Senadores", "tipo_despesa": "Categoria"},
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


def secao_pergunta_13(filtros):
    st.header("Pergunta 13 (parcial): fornecedores que mais receberam CEAPS")
    st.caption(
        "Mostra as empresas e pessoas fornecedoras, não os donos: o quadro societário (CNPJ) ainda não foi "
        "transformado em modelos analíticos. Partido e UF atuais; todos os filtros se aplicam."
    )
    df = consultar("maiores_fornecedores", filtros)
    if sem_dados(df):
        return
    topo = df.head(15).assign(rotulo=lambda d: d["razao_social"].str.slice(0, 45))
    barras_horizontais(
        topo, "valor_total", "rotulo", hover_data=["documento", "senadores", "quantidade_despesas"],
        titulo="Maiores fornecedores (até 15)",
        labels={"valor_total": "Valor recebido (R$)", "rotulo": "Fornecedor"},
    )
    tabela(df, moeda=["valor_total"])


# ---------------------------------------------------------------- Comissões e gabinete

def secao_pergunta_7(filtros):
    st.header("Pergunta 7: comissões que cada senador integra")
    df = consultar("comissoes_por_senador", filtros)
    if sem_dados(df):
        return
    referencias = ", ".join(sorted({pd.Timestamp(d).strftime("%d/%m/%Y") for d in df["data_referencia"]}))
    st.caption(
        f"Comissões e subcomissões distintas com vínculo vigente em {referencias} (data de referência da última "
        "publicação dos modelos); frentes, grupos parlamentares e conselhos não entram. Vínculos sem data de "
        "início não entram na contagem e aparecem à parte: zero comissões confirmadas não prova ausência de "
        "vínculo. Partido e UF atuais; o filtro de ano e o de categoria "
        "não se aplicam."
    )
    barras_horizontais(
        df.head(30), "comissoes_com_vigencia_confirmada", "nome", color="partido_atual",
        titulo="Senadores com mais comissões (até 30)",
        labels={"comissoes_com_vigencia_confirmada": "Comissões com vigência confirmada",
                "nome": "Senador", "partido_atual": "Partido"},
    )
    tabela(df)


def secao_pergunta_12(filtros):
    st.header("Pergunta 12: quantitativo de pessoal por senador")
    st.caption(
        "Quantitativos anuais publicados pelo Senado (gabinete e escritório de apoio), não cadastro de pessoas. "
        "Anos não somam pessoas distintas e ano ausente não é zero. Partido e UF atuais; o filtro de categoria "
        "não se aplica."
    )
    df = consultar("estrutura_gabinete", filtros)
    if sem_dados(df):
        return
    ultimo = df[df["ano"] == df["ano"].max()].head(30)
    barras = ultimo.melt(id_vars="nome", value_vars=["qtd_pessoal_gabinete", "qtd_pessoal_escritorio"],
                         var_name="lotacao", value_name="pessoas")
    barras["lotacao"] = barras["lotacao"].map({"qtd_pessoal_gabinete": "Gabinete",
                                               "qtd_pessoal_escritorio": "Escritório de apoio"})
    barras_horizontais(
        barras, "pessoas", "nome", color="lotacao",
        titulo=f"Maiores estruturas em {int(df['ano'].max())} (até 30)",
        labels={"pessoas": "Pessoas", "nome": "Senador", "lotacao": "Lotação"},
    )
    tabela(df)


# ---------------------------------------------------------------- Presença

def secao_presenca(filtros):
    st.header("Perguntas 5 e 6 (parcial): presenças documentadas no Diário do Senado")
    cobertura = consultar("cobertura_dsf")
    sessoes = cobertura["sessao_id"].nunique()
    st.warning(
        f"Não é taxa de comparecimento: só {sessoes} sessão(ões) plenária(s) foram coletadas e não há o total "
        "de sessões deliberativas a que cada senador estava obrigado. Ausência de registro não significa falta."
    )
    st.caption(
        "Conta sessões distintas com presença aceita (identidade exata, situação PRESENTE e documento com parser "
        "SUCESSO). Registros de documentos parciais ficam fora da contagem e aparecem à parte. Partido e UF "
        "atuais; o filtro de categoria não se aplica."
    )
    df = consultar("presencas_documentadas", filtros)
    if not sem_dados(df):
        por_partido = (df.groupby("partido_atual", as_index=False)
                       .agg(senadores=("senador_id", "nunique"),
                            sessoes_com_presenca=("sessoes_com_presenca_documentada", "sum"))
                       .sort_values("sessoes_com_presenca", ascending=False))
        st.plotly_chart(
            px.bar(por_partido, x="partido_atual", y="sessoes_com_presenca", hover_data=["senadores"],
                   labels={"partido_atual": "Partido (atual)",
                           "sessoes_com_presenca": "Presenças documentadas (senador × sessão)"},
                   title="Presenças documentadas por partido"),
            width="stretch",
        )
        tabela(df)
    with st.expander("Sessões e documentos coletados"):
        tabela(cobertura)


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
    anos = st.multiselect("Ano", opcoes["anos"]["ano"].tolist(), placeholder="Todos")
    partidos = st.multiselect("Partido", opcoes["partidos"]["partido"].tolist(), placeholder="Todos")
    ufs = st.multiselect("UF", opcoes["ufs"]["uf"].tolist(), placeholder="Todos")
    nomes_sen = dict(zip(opcoes["senadores"]["senador_id"], opcoes["senadores"]["nome"]))
    senadores = st.multiselect("Senador", list(nomes_sen), format_func=nomes_sen.get, placeholder="Todos")
    nomes_cat = dict(zip(opcoes["categorias"]["categoria_id"], opcoes["categorias"]["tipo_despesa"]))
    categorias = st.multiselect("Categoria", list(nomes_cat), format_func=nomes_cat.get, placeholder="Todos")
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
                       secao_pergunta_11, secao_gasto_mensal, secao_pergunta_13),
    "Comissões e gabinete": (secao_pergunta_7, secao_pergunta_12),
    "Presença": (secao_presenca,),
}

for aba, secoes in zip(st.tabs(list(ABAS)), ABAS.values()):
    with aba:
        for secao in secoes:
            try:
                secao(filtros)
            except Exception as erro:
                st.error("Falha ao consultar o banco. Verifique o PostgreSQL (`make start`) e os modelos (`make models`).")
                st.caption(f"Detalhe técnico: {type(erro).__name__}")
