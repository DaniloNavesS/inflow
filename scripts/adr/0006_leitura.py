"""ADR 0006, parte 1: mede as alternativas de leitura das métricas publicadas.

Compara, sobre gestao_comparacao_despesas_mensais:
  L0 CSV agendado (opção nula)   L1 warehouse (PostgreSQL)
  L2 federação (DuckDB)          L3 cópia em Parquet

Cada caminho que muda de motor é medido "direto" (tipos inferidos) e "tipado" (tipos
declarados), porque o mart usa numeric sem precisão e o DuckDB o lê como DOUBLE.

Uso, na raiz do repositório, com os marts publicados:
  docker compose run --rm -v ./scripts/adr:/adr:ro -v ./resultados/adr-0006:/saida \
    analytics python /adr/0006_leitura.py

Os marts não são alterados. O script cria e remove um papel (adr0006_leitor) e um schema
(adr0006_tmp) temporários; as consultas de leitura usam esse papel, e não o dono do banco.
"""
import json
import os
import platform
import secrets
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import psycopg2
from psycopg2.extensions import make_dsn

REPETICOES = int(os.getenv("REPETICOES", "7"))
SENADOR = int(os.getenv("SENADOR", "581"))
ANO = int(os.getenv("ANO", "2024"))
SAIDA = Path(os.getenv("SAIDA", "/saida"))
DB = dict(
    host=os.getenv("DB_HOST", "postgres"),
    port=int(os.getenv("DB_PORT", "5432")),
    dbname=os.getenv("DB_NAME", "inflow_db"),
)
DONO = dict(user=os.getenv("DB_USER", "inflow_user"), password=os.getenv("DB_PASSWORD", "inflow_pass"))

PAPEL, TMP = "adr0006_leitor", "adr0006_tmp"
MART = "analytics_marts.gestao_comparacao_despesas_mensais"
# Cabe com folga: até 16 casas nas médias, 20 nos percentuais e 7 dígitos inteiros.
DECIMAL = "DECIMAL(38,20)"

CONSULTAS = {
    "C1 resumo anual por senador": f"""
        SELECT senador_id, count(*) AS competencias, sum(valor_total) AS valor_total,
               count(*) FILTER (WHERE status_comparacao_partido = 'COMPARAVEL' AND acima_media_partido)
                   AS meses_acima,
               sum(diferenca_media_partido) FILTER (WHERE status_comparacao_partido = 'COMPARAVEL')
                   AS diferenca_acumulada
        FROM {{fonte}} WHERE em_exercicio_no_mes AND ano = {ANO}
        GROUP BY senador_id ORDER BY senador_id""",
    "C2 detalhe de um senador": f"""
        SELECT mes, valor_total, media_pares_partido, diferenca_media_partido, desvio_percentual_partido
        FROM {{fonte}} WHERE senador_id = {SENADOR} AND ano = {ANO} ORDER BY mes""",
    "C3 carga do ETL reverso": f"""
        SELECT mensal_id, senador_id, ano, mes, valor_total, media_pares_partido, diferenca_media_partido
        FROM {{fonte}} WHERE acima_media_partido AND ano = {ANO} ORDER BY mensal_id""",
    # Preenchida em main() com todas as colunas do mart.
    "C4 mart completo": None,
}


def conectar(credencial, options="-c timezone=UTC"):
    return psycopg2.connect(**DB, **credencial, connect_timeout=5, options=options)


def consulta_completa(colunas):
    """Todas as colunas. Instantes vão como texto em UTC: o DuckDB exige pytz para devolvê-los."""
    selecao = ", ".join(
        f"CAST({c} AS VARCHAR) AS {c}" if t == "timestamp with time zone" else c for c, t in colunas)
    return f"SELECT {selecao} FROM {{fonte}} ORDER BY mensal_id"


def mediana_ms(funcao, repeticoes=REPETICOES):
    funcao()  # aquecimento, fora da amostra
    tempos = []
    for _ in range(repeticoes):
        inicio = time.perf_counter()
        funcao()
        tempos.append((time.perf_counter() - inicio) * 1000)
    return dict(mediana=statistics.median(tempos), minimo=min(tempos), maximo=max(tempos))


def normalizar(valor):
    # repr(float) é o valor que o consumidor vê; Decimal(float) expandiria o binário.
    return Decimal(repr(valor)) if isinstance(valor, float) else valor


def comparar(esperado, obtido):
    """Linhas diferentes e maior diferença numérica absoluta."""
    diferentes, maior = abs(len(esperado) - len(obtido)), Decimal(0)
    for a, b in zip(esperado, obtido):
        a, b = [normalizar(v) for v in a], [normalizar(v) for v in b]
        if a != b:
            diferentes += 1
            for x, y in zip(a, b):
                if isinstance(x, (Decimal, int)) and isinstance(y, (Decimal, int)):
                    maior = max(maior, abs(Decimal(x) - Decimal(y)))
    return diferentes, maior


class Leitor:
    """Um caminho de leitura: abre a conexão, resolve a fonte e executa a consulta."""

    def __init__(self, nome, abrir, fonte, executar):
        self.nome, self.abrir, self.fonte, self.executar = nome, abrir, fonte, executar

    def ler(self, modelo, conexao=None):
        propria = conexao is None
        conexao = conexao or self.abrir()
        try:
            return self.executar(conexao, modelo.format(fonte=self.fonte))
        finally:
            if propria:
                conexao.close()


def executar_pg(conexao, sql):
    with conexao.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def executar_duck(conexao, sql):
    return conexao.execute(sql).fetchall()


def abrir_duck():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con


def colunas_do_mart(dono):
    return executar_pg(dono, f"""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = '{MART.split('.')[0]}' AND table_name = '{MART.split('.')[1]}'
        ORDER BY ordinal_position""")


def montar_leitores(leitor, colunas, pasta, tabela=MART):
    """Os caminhos de leitura, todos com a credencial do papel restrito ou sem credencial."""
    dsn = make_dsn(**DB, **leitor).replace("'", "''")

    def abrir_federado():
        con = abrir_duck()
        con.load_extension("postgres")
        con.execute(f"ATTACH '{dsn}' AS pg (TYPE postgres, READ_ONLY)")
        return con

    tipos = {
        "numeric": DECIMAL, "timestamp with time zone": "TIMESTAMPTZ", "text": "VARCHAR",
    }
    declaradas = ", ".join(f"'{c}': '{tipos.get(t, t)}'" for c, t in colunas)
    selecao = ", ".join(f"{c}::numeric(38,20) AS {c}" if t == "numeric" else c for c, t in colunas)
    csv, pq, pq_tipado = (pasta / n for n in ("mart.csv", "mart.parquet", "mart_tipado.parquet"))
    return [
        Leitor("L0 CSV, direto", abrir_duck, f"read_csv('{csv}')", executar_duck),
        Leitor("L0 CSV, tipado", abrir_duck,
               f"read_csv('{csv}', header=true, columns={{{declaradas}}})", executar_duck),
        Leitor("L1 warehouse", lambda: conectar(leitor), tabela, executar_pg),
        Leitor("L2 federação, direta", abrir_federado, f"pg.{tabela}", executar_duck),
        Leitor("L2 federação, tipada", abrir_federado,
               f"postgres_query('pg', 'SELECT {selecao} FROM {tabela}')", executar_duck),
        Leitor("L3 Parquet, direto", abrir_duck, f"read_parquet('{pq}')", executar_duck),
        Leitor("L3 Parquet, tipado", abrir_duck, f"read_parquet('{pq_tipado}')", executar_duck),
    ]


def exportadores(leitor, colunas, pasta, tabela=MART):
    """Publicação dos arquivos: grava ao lado e troca, para o leitor nunca ver arquivo parcial."""
    dsn = make_dsn(**DB, **leitor).replace("'", "''")
    selecao = ", ".join(f"{c}::numeric(38,20) AS {c}" if t == "numeric" else c for c, t in colunas)

    def csv():
        parcial = pasta / "mart.csv.parcial"
        con = conectar(leitor)
        try:
            with con.cursor() as cursor, open(parcial, "w", encoding="utf-8", newline="") as arquivo:
                cursor.copy_expert(f"COPY (SELECT * FROM {tabela}) TO STDOUT WITH (FORMAT csv, HEADER)", arquivo)
        finally:
            con.close()
        os.replace(parcial, pasta / "mart.csv")

    def parquet(nome, consulta):
        con = abrir_duck()
        con.load_extension("postgres")
        con.execute(f"ATTACH '{dsn}' AS pg (TYPE postgres, READ_ONLY)")
        parcial = pasta / f"{nome}.parcial"
        con.execute(f"COPY ({consulta}) TO '{parcial}' (FORMAT parquet)")
        con.close()
        os.replace(parcial, pasta / nome)

    return {
        "L0 CSV": (csv, "mart.csv"),
        "L3 Parquet, direto": (lambda: parquet("mart.parquet", f"SELECT * FROM pg.{tabela}"), "mart.parquet"),
        "L3 Parquet, tipado": (
            lambda: parquet("mart_tipado.parquet",
                            f"SELECT * FROM postgres_query('pg', 'SELECT {selecao} FROM {tabela}')"),
            "mart_tipado.parquet"),
    }


def limpar(dono):
    with dono.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {TMP} CASCADE")
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (PAPEL,))
        if cursor.fetchone():
            cursor.execute(f"DROP OWNED BY {PAPEL}")
            cursor.execute(f"DROP ROLE {PAPEL}")


def criar_papel(dono):
    senha = secrets.token_hex(16)
    esquema = MART.split(".")[0]
    with dono.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {PAPEL} LOGIN PASSWORD '{senha}'")
        cursor.execute(f"GRANT USAGE ON SCHEMA {esquema} TO {PAPEL}")
        cursor.execute(f"GRANT SELECT ON {MART} TO {PAPEL}")
    return dict(user=PAPEL, password=senha)


def tentar(funcao):
    try:
        funcao()
        return "permitido"
    except (psycopg2.Error, duckdb.Error) as erro:
        return "negado: " + str(erro).strip().splitlines()[0][:110]


def medir_privilegio(leitor, dono):
    def em(credencial, *comandos, options=None):
        con = conectar(credencial, options) if options else conectar(credencial)
        try:
            with con.cursor() as cursor:
                for comando in comandos:
                    cursor.execute(comando)
        finally:
            con.rollback()
            con.close()

    with dono.cursor() as cursor:
        cursor.execute(f"CREATE TABLE {TMP}.alvo AS SELECT 1 AS n")
    painel = "-c default_transaction_read_only=on"
    return {
        "papel restrito lê o mart": tentar(lambda: em(leitor, f"SELECT 1 FROM {MART} LIMIT 1")),
        "papel restrito lê outro mart": tentar(lambda: em(leitor, "SELECT 1 FROM analytics_marts.fct_despesas LIMIT 1")),
        "papel restrito lê o OLTP": tentar(lambda: em(leitor, "SELECT 1 FROM oltp.despesas LIMIT 1")),
        "papel restrito escreve no mart": tentar(lambda: em(leitor, f"DELETE FROM {MART}")),
        "conexão do painel (dono, somente leitura) escreve": tentar(
            lambda: em(DONO, f"DELETE FROM {TMP}.alvo", options=painel)),
        "conexão do painel desliga a trava e escreve": tentar(
            lambda: em(DONO, "SET TRANSACTION READ WRITE", f"DELETE FROM {TMP}.alvo", options=painel)),
    }


def medir_mudancas(leitor, dono, colunas, pasta):
    """Numa cópia do mart: correção de valor, coluna renomeada e recriação da tabela pelo dbt."""
    tabela, pasta = f"{TMP}.comparacao", pasta / "mudancas"
    pasta.mkdir(exist_ok=True)
    with dono.cursor() as cursor:
        cursor.execute(f"CREATE TABLE {tabela} AS SELECT * FROM {MART}")
        cursor.execute(f"GRANT USAGE ON SCHEMA {TMP} TO {PAPEL}")
        cursor.execute(f"GRANT SELECT ON {tabela} TO {PAPEL}")
    for exportar, _ in exportadores(leitor, colunas, pasta, tabela).values():
        exportar()
    leitores = [r for r in montar_leitores(leitor, colunas, pasta, tabela) if "tipad" in r.nome or r.nome.startswith("L1")]
    consulta = f"SELECT valor_total FROM {{fonte}} WHERE senador_id = {SENADOR} AND ano = {ANO} AND mes = 1"
    antes = {r.nome: r.ler(consulta)[0][0] for r in leitores}
    resultado = {r.nome: {} for r in leitores}

    with dono.cursor() as cursor:
        cursor.execute(f"UPDATE {tabela} SET valor_total = valor_total + 1 "
                       f"WHERE senador_id = {SENADOR} AND ano = {ANO} AND mes = 1")
    for r in leitores:
        resultado[r.nome]["correção no mart"] = "visível" if r.ler(consulta)[0][0] != antes[r.nome] else "não visível"

    with dono.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {tabela} RENAME COLUMN valor_total TO gasto_total")
    for r in leitores:
        resultado[r.nome]["coluna renomeada"] = "responde" if tentar(lambda: r.ler(consulta)) == "permitido" else "quebra"

    # Mesma troca que a materialização table faz: nova tabela por CTAS e renomeação.
    with dono.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {tabela} RENAME COLUMN gasto_total TO valor_total")
        cursor.execute(f"CREATE TABLE {tabela}__novo AS SELECT * FROM {tabela}")
        cursor.execute(f"DROP TABLE {tabela}")
        cursor.execute(f"ALTER TABLE {tabela}__novo RENAME TO comparacao")
    for r in leitores:
        resultado[r.nome]["tabela recriada"] = "responde" if tentar(lambda: r.ler(consulta)) == "permitido" else "acesso negado"
    return resultado


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    # Disco do contêiner: a pasta montada do host distorceria o tempo dos arquivos.
    pasta = Path(tempfile.mkdtemp())
    dono = conectar(DONO)
    dono.autocommit = True
    limpar(dono)  # restos de uma execução interrompida
    try:
        leitor = criar_papel(dono)
        with dono.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA {TMP}")
        colunas = colunas_do_mart(dono)
        consultas = {**CONSULTAS, "C4 mart completo": consulta_completa(colunas)}

        publicacao = {}
        for nome, (exportar, arquivo) in exportadores(leitor, colunas, pasta).items():
            tempo = mediana_ms(exportar)
            publicacao[nome] = {**tempo, "bytes": (pasta / arquivo).stat().st_size}

        leitores = montar_leitores(leitor, colunas, pasta)
        leitura = {}
        for nome_consulta, modelo in consultas.items():
            esperado = executar_pg(dono, modelo.format(fonte=MART))
            linhas = []
            for r in leitores:
                obtido = r.ler(modelo)
                diferentes, maior = comparar(esperado, obtido)
                conexao = r.abrir()
                try:
                    so_consulta = mediana_ms(lambda: r.ler(modelo, conexao))
                finally:
                    conexao.close()
                com_conexao = mediana_ms(lambda: r.ler(modelo))
                linhas.append(dict(caminho=r.nome, diferentes=diferentes, maior_diferenca=str(maior),
                                   consulta_ms=so_consulta, com_conexao_ms=com_conexao))
            leitura[nome_consulta] = dict(linhas=len(esperado), caminhos=linhas)

        privilegio = medir_privilegio(leitor, dono)
        mudancas = medir_mudancas(leitor, dono, colunas, pasta)
        tamanho = executar_pg(dono, f"SELECT pg_table_size('{MART}'), count(*) FROM {MART}")[0]
        versao = executar_pg(dono, "SHOW server_version")[0][0]
    finally:
        limpar(dono)
        dono.close()

    relatorio = dict(
        executado_em=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), repeticoes=REPETICOES,
        ambiente=f"PostgreSQL {versao}, DuckDB {duckdb.__version__}, Python {platform.python_version()}",
        mart=dict(nome=MART, linhas=tamanho[1], bytes=tamanho[0]),
        publicacao=publicacao, leitura=leitura, privilegio=privilegio, mudancas=mudancas,
    )
    (SAIDA / "leitura.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    texto = formatar(relatorio)
    (SAIDA / "leitura.txt").write_text(texto, encoding="utf-8")
    sys.stdout.write(texto)


def formatar(r):
    ms = lambda t: f"{t['mediana']:.2f} ({t['minimo']:.2f}-{t['maximo']:.2f})"
    numero = lambda n: f"{Decimal(n):.1E}" if Decimal(n) else "0"
    s = [f"ADR 0006: leitura das métricas ({r['executado_em']})", r["ambiente"],
         f"{r['mart']['nome']}: {r['mart']['linhas']} linhas, {r['mart']['bytes']} bytes",
         f"Mediana (mínimo-máximo) de {r['repeticoes']} execuções após aquecimento, em ms", "",
         "== Publicação dos arquivos"]
    s += [f"{n:<24} {ms(p):>28}  {p['bytes']:>9} bytes" for n, p in r["publicacao"].items()]
    for consulta, dados in r["leitura"].items():
        s += ["", f"== {consulta} ({dados['linhas']} linhas)",
              f"{'caminho':<24} {'só a consulta':>28} {'com conexão':>28}  diferentes  maior diferença"]
        s += [f"{c['caminho']:<24} {ms(c['consulta_ms']):>28} {ms(c['com_conexao_ms']):>28}  "
              f"{c['diferentes']:>10}  {numero(c['maior_diferenca'])}" for c in dados["caminhos"]]
    s += ["", "== Privilégio mínimo"] + [f"{n:<52} {v}" for n, v in r["privilegio"].items()]
    s += ["", "== Mudanças na cópia do mart"]
    for caminho, eventos in r["mudancas"].items():
        s.append(f"{caminho:<24} " + "; ".join(f"{e}: {v}" for e, v in eventos.items()))
    return "\n".join(s) + "\n"


if __name__ == "__main__":
    main()
