#!/usr/bin/env python3
"""
Plataforma InFlow: Ingestor Automatizado de Dados Abertos do Senado Federal
Módulo E1 - Disciplina de Banco de Dados 2 (UnB - FCTE)

Responsável por:
1. Consumir APIs RESTful do Senado Federal com resiliência, retries e rate limiting.
2. Tratar, limpar e normalizar os dados em memória.
3. Carregar e realizar upsert no banco relacional PostgreSQL (OLTP).
"""

import os
import sys
import time
import ssl
import logging
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import psycopg2
from psycopg2.extras import execute_batch, execute_values

# -----------------------------------------------------------------------------
# Configuração de Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("inflow_ingestor")

# -----------------------------------------------------------------------------
# Configurações de Ambiente
# -----------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "inflow_db")
DB_USER = os.getenv("DB_USER", "inflow_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "inflow_pass")

INGESTION_YEAR = int(os.getenv("INGESTION_YEAR", "2024"))
LIMIT_SENADORES = int(os.getenv("LIMIT_SENADORES", "0"))  # 0 para processar todos

# Headers HTTP padrão aceitos por WAFs e proxies governamentais
REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# -----------------------------------------------------------------------------
# Sessão HTTP Resiliente com Políticas de Retry e Adaptação TLS
# -----------------------------------------------------------------------------
class SenateTLSAdapter(HTTPAdapter):
    """
    Adapter customizado para garantir compatibilidade TLS 1.2 com os servidores
    e firewalls do Senado Federal, evitando timeouts de negociação TLS 1.3 do OpenSSL 3.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

def get_resilient_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = SenateTLSAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# -----------------------------------------------------------------------------
# Conexão com o Banco de Dados com Backoff Exponencial
# -----------------------------------------------------------------------------
def wait_for_database(max_attempts: int = 30, delay_seconds: int = 2) -> psycopg2.extensions.connection:
    logger.info("Aguardando disponibilidade do banco de dados PostgreSQL...")
    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5
            )
            conn.autocommit = False
            logger.info("Conexão com PostgreSQL estabelecida com sucesso!")
            return conn
        except psycopg2.OperationalError as e:
            logger.warning("PostgreSQL indisponível na tentativa %d/%d: %s", attempt, max_attempts, e)
            time.sleep(delay_seconds)
    
    logger.error("Falha crítica: impossível conectar ao PostgreSQL após múltiplas tentativas.")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Etapa 1: Ingestão de Senadores
# -----------------------------------------------------------------------------
def ingest_senadores(session: requests.Session, conn: psycopg2.extensions.connection) -> list:
    url = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json"
    logger.info("Iniciando ingestão de Senadores atuais a partir de: %s", url)
    
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    parlamentares = data.get("ListaParlamentarEmExercicio", {}).get("Parlamentares", {}).get("Parlamentar", [])
    if isinstance(parlamentares, dict):
        parlamentares = [parlamentares]
        
    logger.info("Total de parlamentares em exercício recebidos: %d", len(parlamentares))
    
    records = []
    senador_ids = []
    for item in parlamentares:
        ident = item.get("IdentificacaoParlamentar", {})
        cod = int(ident.get("CodigoParlamentar"))
        nome = ident.get("NomeParlamentar", "").strip()
        nome_completo = ident.get("NomeCompletoParlamentar", "").strip() or None
        partido = ident.get("SiglaPartidoParlamentar", "S/PART").strip()
        uf = ident.get("UfParlamentar", "DF").strip()
        foto_url = ident.get("UrlFotoParlamentar")
        pagina_url = ident.get("UrlPaginaParlamentar")
        email = ident.get("EmailParlamentar")
        status = "Em Exercício"
        
        records.append((cod, nome, nome_completo, partido, uf, foto_url, pagina_url, email, status))
        senador_ids.append(cod)

    query = """
        INSERT INTO senadores (
            id, nome, nome_completo, partido, uf, foto_url, pagina_url, email, status, timestamp_ingestao, atualizado_em
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (id) DO UPDATE SET
            nome = EXCLUDED.nome,
            nome_completo = EXCLUDED.nome_completo,
            partido = EXCLUDED.partido,
            uf = EXCLUDED.uf,
            foto_url = EXCLUDED.foto_url,
            pagina_url = EXCLUDED.pagina_url,
            email = EXCLUDED.email,
            status = EXCLUDED.status,
            atualizado_em = CURRENT_TIMESTAMP;
    """
    
    with conn.cursor() as cur:
        execute_batch(cur, query, records, page_size=100)
    conn.commit()
    logger.info("Upsert concluído: %d senadores persistidos.", len(records))
    return senador_ids

# -----------------------------------------------------------------------------
# Etapa 2: Ingestão de Comissões e Participações
# -----------------------------------------------------------------------------
def ingest_comissoes_e_participacoes(session: requests.Session, conn: psycopg2.extensions.connection, senador_ids: list):
    logger.info("Iniciando ingestão de Comissões e Participações para %d senadores...", len(senador_ids))
    
    comissoes_unicas = {}
    participacoes = []
    
    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]
    
    for idx, sen_id in enumerate(target_ids, 1):
        url = f"https://legis.senado.leg.br/dadosabertos/senador/{sen_id}/comissoes.json"
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                comissoes_data = data.get("MembroComissaoParlamentar", {}).get("Parlamentar", {}).get("MembroComissoes", {}).get("Comissao", [])
                if isinstance(comissoes_data, dict):
                    comissoes_data = [comissoes_data]
                    
                for c in comissoes_data:
                    ident_c = c.get("IdentificacaoComissao", {})
                    if not ident_c.get("CodigoComissao"):
                        continue
                    com_id = int(ident_c.get("CodigoComissao"))
                    sigla = (ident_c.get("SiglaComissao") or "COM").strip()
                    nome_c = (ident_c.get("NomeComissao") or sigla).strip()
                    casa = (ident_c.get("SiglaCasaComissao") or "SF").strip()
                    
                    comissoes_unicas[com_id] = (com_id, sigla, nome_c, casa)
                    
                    cargo = (c.get("DescricaoParticipacao") or "Membro").strip()
                    data_inicio = c.get("DataInicio") or None
                    data_fim = c.get("DataFim") or None
                    
                    # Sanitize datas
                    if data_inicio and data_fim and data_fim < data_inicio:
                        data_fim = None
                        
                    participacoes.append((sen_id, com_id, cargo, data_inicio, data_fim))
            
            time.sleep(0.12)
        except Exception as e:
            logger.warning("Falha ao obter comissões para senador %d: %s", sen_id, e)
            
        if idx % 20 == 0 or idx == len(target_ids):
            logger.info("Processamento de comissões: %d/%d senadores analisados.", idx, len(target_ids))
            
    # Persistir comissões
    if comissoes_unicas:
        query_comissoes = """
            INSERT INTO comissoes (id, sigla, nome, casa, timestamp_ingestao, atualizado_em)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                sigla = EXCLUDED.sigla,
                nome = EXCLUDED.nome,
                casa = EXCLUDED.casa,
                atualizado_em = CURRENT_TIMESTAMP;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_comissoes, list(comissoes_unicas.values()), page_size=100)
        conn.commit()
        logger.info("Upsert concluído: %d comissões cadastradas.", len(comissoes_unicas))
        
    # Persistir participações
    if participacoes:
        query_part = """
            INSERT INTO participacoes_comissao (
                senador_id, comissao_id, cargo, data_inicio, data_fim, timestamp_ingestao
            ) VALUES (
                %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (senador_id, comissao_id, cargo, data_inicio) DO UPDATE SET
                data_fim = EXCLUDED.data_fim;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_part, participacoes, page_size=200)
        conn.commit()
        logger.info("Upsert concluído: %d participações em comissões registradas.", len(participacoes))

# -----------------------------------------------------------------------------
# Etapa 3: Ingestão de Sessões e Presenças (Atuação Parlamentar)
# -----------------------------------------------------------------------------
def ingest_sessoes_presenca(session: requests.Session, conn: psycopg2.extensions.connection, senador_ids: list):
    logger.info("Iniciando ingestão de Sessões e Presenças (Votações Nominais)...")
    
    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]
    sessoes_unicas = {}
    registros_presenca = []

    for idx, sen_id in enumerate(target_ids, 1):
        url = f"https://legis.senado.leg.br/dadosabertos/votacao?codigoParlamentar={sen_id}"
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    # Ingerir as últimas 30 votações por parlamentar
                    for item in data[:30]:
                        sessao_id = item.get("codigoSessao")
                        data_sessao = item.get("dataSessao")
                        tipo_sessao = item.get("siglaTipoSessao") or item.get("sigla") or "Plenário"
                        
                        if not sessao_id or not data_sessao:
                            continue
                            
                        presenca = "Presente"
                        votos = item.get("votos", [])
                        if votos:
                            voto_sen = next((v for v in votos if v.get("codigoParlamentar") == sen_id), None)
                            if voto_sen:
                                presenca = voto_sen.get("siglaVotoParlamentar") or "Votou"
                                
                        sessoes_unicas[int(sessao_id)] = (int(sessao_id), data_sessao, tipo_sessao)
                        registros_presenca.append((int(sessao_id), sen_id, presenca))


            time.sleep(0.12)
        except Exception as e:
            logger.warning("Falha ao consultar sessões/presenças do senador %d: %s", sen_id, e)
            
        if idx % 20 == 0 or idx == len(target_ids):
            logger.info("Processamento de presenças: %d/%d senadores analisados.", idx, len(target_ids))

    # As sessões precisam existir antes das presenças que as referenciam.
    if sessoes_unicas:
        query_sessoes = """
            INSERT INTO sessoes (id, data_sessao, tipo_sessao, timestamp_ingestao, atualizado_em)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                data_sessao = EXCLUDED.data_sessao,
                tipo_sessao = EXCLUDED.tipo_sessao,
                atualizado_em = CURRENT_TIMESTAMP;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_sessoes, list(sessoes_unicas.values()), page_size=200)
        conn.commit()
        logger.info("Upsert concluído: %d sessões plenárias persistidas.", len(sessoes_unicas))

    if registros_presenca:
        query_presenca = """
            INSERT INTO sessoes_presenca (
                sessao_id, senador_id, presenca, timestamp_ingestao
            ) VALUES (
                %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (sessao_id, senador_id) DO UPDATE SET
                presenca = EXCLUDED.presenca;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_presenca, registros_presenca, page_size=200)
        conn.commit()
        logger.info("Upsert concluído: %d registros de presença persistidos.", len(registros_presenca))

# -----------------------------------------------------------------------------
# Etapa 4: Ingestão de Fornecedores e Despesas (CEAPS)
# -----------------------------------------------------------------------------
def ingest_ceaps_despesas(session: requests.Session, conn: psycopg2.extensions.connection, ano: int):
    url = f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}"
    logger.info("Iniciando ingestão de despesas da CEAPS para o ano de %d a partir de: %s", ano, url)
    
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    despesas_raw = resp.json()
    
    if not isinstance(despesas_raw, list):
        logger.warning("Formato inesperado na resposta de despesas da CEAPS.")
        return
        
    logger.info("Total de lançamentos de despesas CEAPS recuperados para %d: %d", ano, len(despesas_raw))
    
    # Cache local de fornecedores
    fornecedores_cache = {}
    with conn.cursor() as cur:
        cur.execute("SELECT cnpj_cpf, id FROM fornecedores;")
        for row in cur.fetchall():
            fornecedores_cache[row[0]] = row[1]
            
    logger.info("Fornecedores pré-existentes em cache: %d", len(fornecedores_cache))
    
    # Coleta fornecedores únicos não existentes
    novos_fornecedores = {}
    senadores_despesas = set()
    
    for d in despesas_raw:
        raw_cnpj = str(d.get("cpfCnpj") or "").strip()
        razao = str(d.get("fornecedor") or "NÃO INFORMADO").strip()
        if not raw_cnpj:
            raw_cnpj = "SEM_DOCUMENTO"
            
        if raw_cnpj not in fornecedores_cache and raw_cnpj not in novos_fornecedores:
            novos_fornecedores[raw_cnpj] = razao[:255]
            
        cod_senador = d.get("codSenador")
        nome_senador = d.get("nomeSenador")
        if cod_senador:
            senadores_despesas.add((int(cod_senador), str(nome_senador or "Desconhecido").strip()))

    # Garante que senadores referenciados nas despesas existam na tabela senadores
    if senadores_despesas:
        query_garante_senador = """
            INSERT INTO senadores (id, nome, partido, uf, status, timestamp_ingestao, atualizado_em)
            VALUES (%s, %s, 'S/PART', 'DF', 'Exercício Passado', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_garante_senador, [(s[0], s[1]) for s in senadores_despesas])
        conn.commit()

    # Inserção em lote de novos fornecedores com execute_values
    if novos_fornecedores:
        logger.info("Cadastrando %d novos fornecedores...", len(novos_fornecedores))
        query_ins_forn = """
            INSERT INTO fornecedores (cnpj_cpf, razao_social, timestamp_ingestao, atualizado_em)
            VALUES %s
            ON CONFLICT (cnpj_cpf) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                atualizado_em = CURRENT_TIMESTAMP;
        """
        with conn.cursor() as cur:
            execute_values(
                cur,
                query_ins_forn,
                list(novos_fornecedores.items()),
                template="(%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                page_size=1000
            )
        conn.commit()
        
        # Atualiza cache com todos os fornecedores
        with conn.cursor() as cur:
            cur.execute("SELECT cnpj_cpf, id FROM fornecedores;")
            for row in cur.fetchall():
                fornecedores_cache[row[0]] = row[1]
        logger.info("Cache de fornecedores atualizado: %d registros.", len(fornecedores_cache))
                
    # Tratamento e montagem das despesas
    despesas_records = []
    for d in despesas_raw:
        despesa_id = d.get("id")
        cod_sen = d.get("codSenador")
        data_str = d.get("data")
        tipo_despesa = (d.get("tipoDespesa") or "OUTRAS").strip()
        tipo_doc = (d.get("tipoDocumento") or "OUTRO").strip()
        num_doc = str(d.get("documento") or "").strip() or None
        detalhamento = str(d.get("detalhamento") or "").strip() or None
        valor = float(d.get("valorReembolsado") or 0.0)
        ano_d = int(d.get("ano") or ano)
        mes_d = int(d.get("mes") or 1)
        
        if not despesa_id or not cod_sen or not data_str:
            continue
            
        raw_cnpj = str(d.get("cpfCnpj") or "").strip() or "SEM_DOCUMENTO"
        forn_id = fornecedores_cache.get(raw_cnpj)
        if not forn_id:
            continue
            
        try:
            data_despesa = datetime.datetime.strptime(data_str[:10], "%Y-%m-%d").date()
        except ValueError:
            data_despesa = datetime.date(ano_d, mes_d, 1)

        if valor < 0:
            valor = 0.0

        despesas_records.append((
            int(despesa_id),
            int(cod_sen),
            int(forn_id),
            data_despesa,
            ano_d,
            mes_d,
            tipo_despesa[:255],
            tipo_doc[:100],
            num_doc[:100] if num_doc else None,
            detalhamento,
            valor
        ))

    logger.info("Realizando upsert de %d despesas no PostgreSQL...", len(despesas_records))
    query_despesas = """
        INSERT INTO despesas (
            id, senador_id, fornecedor_id, data_despesa, ano, mes,
            tipo_despesa, tipo_documento, num_documento, detalhamento, valor,
            timestamp_ingestao, atualizado_em
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (id) DO UPDATE SET
            valor = EXCLUDED.valor,
            tipo_despesa = EXCLUDED.tipo_despesa,
            tipo_documento = EXCLUDED.tipo_documento,
            num_documento = EXCLUDED.num_documento,
            detalhamento = EXCLUDED.detalhamento,
            atualizado_em = CURRENT_TIMESTAMP;
    """
    
    with conn.cursor() as cur:
        execute_batch(cur, query_despesas, despesas_records, page_size=500)
    conn.commit()
    logger.info("Upsert concluído: %d despesas persistidas com sucesso.", len(despesas_records))

# -----------------------------------------------------------------------------
# Etapa 5: Ingestão de Estrutura de Gabinete e Pessoal (Pergunta 14)
# -----------------------------------------------------------------------------
def ingest_estrutura_gabinete(session: requests.Session, conn: psycopg2.extensions.connection, senador_ids: list, ano: int):
    logger.info("Iniciando ingestão de Estrutura de Gabinete e Pessoal para o ano %d...", ano)
    
    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]
    registros_estrutura = []
    
    for idx, sen_id in enumerate(target_ids, 1):
        url = f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/{sen_id}/recursos-utilizados?ano={ano}"
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                payload = resp.json()
                data_list = payload.get("data", [])
                for d in data_list:
                    ano_dado = int(d.get("ano") or ano)
                    pessoal_list = d.get("pessoal", [])
                    beneficios_list = d.get("beneficios", [])
                    
                    qtd_gabinete = 0
                    qtd_escritorio = 0
                    
                    for p in pessoal_list:
                        loc = str(p.get("local") or "").lower()
                        qtd = int(p.get("quantidade") or 0)
                        if "gabinete" in loc:
                            qtd_gabinete += qtd
                        elif "escritório" in loc or "apoio" in loc:
                            qtd_escritorio += qtd
                            
                    auxilio_moradia = False
                    imovel_funcional = False
                    for b in beneficios_list:
                        ben = str(b.get("beneficio") or "").lower()
                        util = str(b.get("utilizacao") or "").lower()
                        if "auxílio-moradia" in ben and "não" not in util:
                            auxilio_moradia = True
                        if "imóvel funcional" in ben and "não" not in util:
                            imovel_funcional = True
                            
                    registros_estrutura.append((
                        sen_id, ano_dado, qtd_gabinete, qtd_escritorio,
                        auxilio_moradia, imovel_funcional
                    ))
            time.sleep(0.12)
        except Exception as e:
            logger.warning("Falha ao consultar estrutura de gabinete do senador %d: %s", sen_id, e)
            
        if idx % 20 == 0 or idx == len(target_ids):
            logger.info("Processamento de estrutura de gabinete: %d/%d senadores analisados.", idx, len(target_ids))

    if registros_estrutura:
        query_est = """
            INSERT INTO estrutura_gabinete (
                senador_id, ano, qtd_pessoal_gabinete, qtd_pessoal_escritorio,
                auxilio_moradia, imovel_funcional, timestamp_ingestao, atualizado_em
            ) VALUES (
                %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (senador_id, ano) DO UPDATE SET
                qtd_pessoal_gabinete = EXCLUDED.qtd_pessoal_gabinete,
                qtd_pessoal_escritorio = EXCLUDED.qtd_pessoal_escritorio,
                auxilio_moradia = EXCLUDED.auxilio_moradia,
                imovel_funcional = EXCLUDED.imovel_funcional,
                atualizado_em = CURRENT_TIMESTAMP;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_est, registros_estrutura, page_size=100)
        conn.commit()
        logger.info("Upsert concluído: %d registros de estrutura de pessoal persistidos.", len(registros_estrutura))

# -----------------------------------------------------------------------------
# Validação e Sumário Estatístico
# -----------------------------------------------------------------------------
def log_database_summary(conn: psycopg2.extensions.connection):
    tabelas = [
        "senadores",
        "comissoes",
        "participacoes_comissao",
        "sessoes",
        "sessoes_presenca",
        "fornecedores",
        "despesas",
        "estrutura_gabinete"
    ]
    
    logger.info("==================================================")
    logger.info("       RELATÓRIO DE INGESTÃO E AUDITORIA OLTP     ")
    logger.info("==================================================")
    with conn.cursor() as cur:
        for t in tabelas:
            cur.execute(f"SELECT COUNT(*) FROM {t};")
            count = cur.fetchone()[0]
            logger.info("Tabela '%-25s': %8d registros", t, count)
            
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM despesas;")
        total_despesas = cur.fetchone()[0]
        logger.info("Total Financeiro Reembolsado (CEAPS): R$ %14.2f", total_despesas)
    logger.info("==================================================")

# -----------------------------------------------------------------------------
# Fluxo Principal
# -----------------------------------------------------------------------------
def main():
    logger.info("Iniciando pipeline de carga automatizada InFlow (E1)...")
    start_time = time.time()
    
    conn = wait_for_database()
    session = get_resilient_session()
    
    try:
        # 1. Senadores
        senador_ids = ingest_senadores(session, conn)
        
        # 2. Comissões e Participações
        ingest_comissoes_e_participacoes(session, conn, senador_ids)
        
        # 3. Sessões e Presenças (Atuação)
        ingest_sessoes_presenca(session, conn, senador_ids)
        
        # 4. Despesas e Fornecedores (CEAPS)
        ingest_ceaps_despesas(session, conn, INGESTION_YEAR)
        
        # 5. Estrutura de Gabinete e Pessoal (Pergunta 14)
        ingest_estrutura_gabinete(session, conn, senador_ids, INGESTION_YEAR)
        
        # Relatório Final
        log_database_summary(conn)
        
        elapsed = time.time() - start_time
        logger.info("Pipeline de ingestão finalizado com sucesso em %.2f segundos!", elapsed)
    except Exception as e:
        logger.exception("Erro crítico durante a execução do pipeline de ingestão: %s", e)
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
