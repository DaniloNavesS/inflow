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
    st.plotly_chart(
        px.bar(topo, x="valor_total", y="rotulo", orientation="h",
               hover_data=["documento", "senadores", "quantidade_despesas"],
               labels={"valor_total": "Valor recebido (R$)", "rotulo": "Fornecedor"},
               title="Maiores fornecedores (até 15)")
        .update_yaxes(autorange="reversed"),
        width="stretch",
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
        f"Comissões distintas com vínculo vigente em {referencias} (data de referência da última publicação "
        "dos modelos). Vínculos sem data de início não entram na contagem e aparecem à parte: zero comissões "
        "confirmadas não prova ausência de vínculo. Partido e UF atuais; o filtro de ano e o de categoria "
        "não se aplicam."
    )
    st.plotly_chart(
        px.bar(df.head(30), x="comissoes_com_vigencia_confirmada", y="nome", color="partido_atual",
               orientation="h",
               labels={"comissoes_com_vigencia_confirmada": "Comissões com vigência confirmada",
                       "nome": "Senador", "partido_atual": "Partido"},
               title="Senadores com mais comissões (até 30)")
        .update_yaxes(autorange="reversed"),
        width="stretch",
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
    st.plotly_chart(
        px.bar(barras, x="pessoas", y="nome", color="lotacao", orientation="h",
               labels={"pessoas": "Pessoas", "nome": "Senador", "lotacao": "Lotação"},
               title=f"Maiores estruturas em {int(df['ano'].max())} (até 30)")
        .update_yaxes(autorange="reversed"),
        width="stretch",
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
