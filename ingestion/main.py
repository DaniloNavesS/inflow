#!/usr/bin/env python3
"""
Plataforma InFlow: Ingestor Automatizado de Dados Abertos do Senado Federal
Módulo E1 - Disciplina de Banco de Dados 2 (UnB - FCTE)

Responsável por:
1. Consumir APIs RESTful do Senado Federal com resiliência, retries e rate limiting.
2. Tratar, limpar e normalizar os dados em memória.
3. Carregar e realizar upsert no banco relacional PostgreSQL (OLTP).
"""

import sys
import time
import logging
import datetime
import requests
import psycopg2
from psycopg2.extras import execute_batch, execute_values
from attendance import ingest_dsf_attendance
from clients.senate import get_resilient_session
from config import INGESTION_YEAR, LEGISLATURE, LIMIT_SENADORES
from database.postgres import wait_for_database
from domain import supplier_identity

# -----------------------------------------------------------------------------
# Configuração de Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("inflow_ingestion")

# -----------------------------------------------------------------------------
# Etapa 1: Ingestão de Senadores
# -----------------------------------------------------------------------------
def ingest_senadores(session: requests.Session, conn: psycopg2.extensions.connection) -> list:
    current_url = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json"
    legislature_url = f"https://legis.senado.leg.br/dadosabertos/senador/lista/legislatura/{LEGISLATURE}.json"
    logger.info("Iniciando ingestão de senadores atuais e da %dª legislatura.", LEGISLATURE)

    current_response = session.get(current_url, timeout=60)
    current_response.raise_for_status()
    current = current_response.json().get("ListaParlamentarEmExercicio", {}).get("Parlamentares", {}).get("Parlamentar", [])
    if isinstance(current, dict):
        current = [current]
    current_ids = {
        int(item["IdentificacaoParlamentar"]["CodigoParlamentar"])
        for item in current
    }

    legislature_response = session.get(legislature_url, timeout=60)
    legislature_response.raise_for_status()
    historical = legislature_response.json().get("ListaParlamentarLegislatura", {}).get("Parlamentares", {}).get("Parlamentar", [])
    if isinstance(historical, dict):
        historical = [historical]

    by_id = {}
    for item in historical + current:
        ident = item.get("IdentificacaoParlamentar", {})
        if ident.get("CodigoParlamentar") and (
            ident.get("CodigoPublicoNaLegAtual") or ident.get("UfParlamentar")
        ):
            by_id[int(ident["CodigoParlamentar"])] = item
    parlamentares = list(by_id.values())
        
    logger.info("Total de parlamentares atuais/históricos selecionados: %d", len(parlamentares))
    
    records = []
    senador_ids = []
    for item in parlamentares:
        ident = item.get("IdentificacaoParlamentar", {})
        cod = int(ident.get("CodigoParlamentar"))
        nome = ident.get("NomeParlamentar", "").strip()
        nome_completo = ident.get("NomeCompletoParlamentar", "").strip() or None
        partido = (ident.get("SiglaPartidoParlamentar") or "").strip() or None
        uf = (ident.get("UfParlamentar") or "").strip() or None
        foto_url = ident.get("UrlFotoParlamentar")
        pagina_url = ident.get("UrlPaginaParlamentar")
        email = ident.get("EmailParlamentar")
        status = "Em Exercício" if cod in current_ids else "Histórico"
        
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


def ingest_historico_parlamentar(session, conn, senador_ids: list):
    logger.info("Iniciando ingestão de mandatos, exercícios e filiações.")
    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]
    mandatos, exercicios, filiacoes = [], [], []
    for index, senator_id in enumerate(target_ids, 1):
        try:
            response = session.get(
                f"https://legis.senado.leg.br/dadosabertos/senador/{senator_id}/mandatos.json",
                timeout=30,
            )
            if response.status_code == 200:
                parliamentary = response.json().get("MandatoParlamentar", {}).get("Parlamentar", {})
                items = parliamentary.get("Mandatos", {}).get("Mandato", [])
                if isinstance(items, dict):
                    items = [items]
                for item in items:
                    first = item.get("PrimeiraLegislaturaDoMandato", {})
                    second = item.get("SegundaLegislaturaDoMandato", {})
                    start = first.get("DataInicio")
                    end = second.get("DataFim") or first.get("DataFim")
                    if not item.get("CodigoMandato") or not start or not end:
                        continue
                    mandate_id = int(item["CodigoMandato"])
                    mandatos.append((
                        mandate_id, senator_id, item.get("UfParlamentar"),
                        item.get("DescricaoParticipacao") or "Não informado", start, end,
                    ))
                    exercise_items = item.get("Exercicios", {}).get("Exercicio", [])
                    if isinstance(exercise_items, dict):
                        exercise_items = [exercise_items]
                    for exercise in exercise_items:
                        if exercise.get("CodigoExercicio") and exercise.get("DataInicio"):
                            exercicios.append((
                                int(exercise["CodigoExercicio"]), mandate_id, senator_id,
                                exercise["DataInicio"], exercise.get("DataFim"),
                                exercise.get("SiglaCausaAfastamento"),
                                exercise.get("DescricaoCausaAfastamento"),
                            ))

            response = session.get(
                f"https://legis.senado.leg.br/dadosabertos/senador/{senator_id}/filiacoes.json",
                timeout=30,
            )
            if response.status_code == 200:
                parliamentary = response.json().get("FiliacaoParlamentar", {}).get("Parlamentar", {})
                items = parliamentary.get("Filiacoes", {}).get("Filiacao", [])
                if isinstance(items, dict):
                    items = [items]
                for item in items:
                    party = item.get("Partido", {})
                    if item.get("DataFiliacao") and party.get("SiglaPartido"):
                        filiacoes.append((
                            senator_id,
                            int(party["CodigoPartido"]) if party.get("CodigoPartido") else None,
                            party["SiglaPartido"], party.get("NomePartido"),
                            item["DataFiliacao"], item.get("DataDesfiliacao"),
                        ))
            time.sleep(0.12)
        except Exception as exc:
            logger.warning("Falha no histórico do senador %d: %s", senator_id, exc)
        if index % 20 == 0 or index == len(target_ids):
            logger.info("Histórico parlamentar: %d/%d.", index, len(target_ids))

    with conn.cursor() as cur:
        execute_batch(cur, """
            INSERT INTO mandatos
                (codigo_mandato, senador_id, uf, participacao, data_inicio, data_fim)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (codigo_mandato, senador_id) DO UPDATE SET
                uf=EXCLUDED.uf,
                participacao=EXCLUDED.participacao, data_inicio=EXCLUDED.data_inicio,
                data_fim=EXCLUDED.data_fim, atualizado_em=CURRENT_TIMESTAMP
        """, mandatos, page_size=200)
        execute_batch(cur, """
            INSERT INTO exercicios_mandato
                (codigo_exercicio, codigo_mandato, senador_id, data_inicio, data_fim,
                 sigla_causa_afastamento, descricao_causa_afastamento)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (codigo_exercicio) DO UPDATE SET
                data_inicio=EXCLUDED.data_inicio, data_fim=EXCLUDED.data_fim,
                sigla_causa_afastamento=EXCLUDED.sigla_causa_afastamento,
                descricao_causa_afastamento=EXCLUDED.descricao_causa_afastamento,
                atualizado_em=CURRENT_TIMESTAMP
        """, exercicios, page_size=200)
        execute_batch(cur, """
            INSERT INTO filiacoes_partidarias
                (senador_id, codigo_partido, sigla_partido, nome_partido,
                 data_filiacao, data_desfiliacao)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (senador_id, sigla_partido, data_filiacao) DO UPDATE SET
                codigo_partido=EXCLUDED.codigo_partido, nome_partido=EXCLUDED.nome_partido,
                data_desfiliacao=EXCLUDED.data_desfiliacao,
                atualizado_em=CURRENT_TIMESTAMP
        """, filiacoes, page_size=200)
    conn.commit()
    logger.info("Histórico: %d mandatos, %d exercícios, %d filiações.", len(mandatos), len(exercicios), len(filiacoes))

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
    """Compatibilidade do fluxo principal: presença vem exclusivamente do DSF."""
    logger.info("Iniciando ingestão documental de presença no DSF.")
    metrics = ingest_dsf_attendance(session, conn)
    for metric in metrics:
        logger.info(
            "DSF %d, sessão %d: %d/%d linhas; %d não resolvidas; %s.",
            metric["diary_code"], metric["session_number"], metric["extracted"],
            metric["expected_count"], metric["unresolved"], metric["status"],
        )
    return metrics


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
        cur.execute("SELECT chave_deduplicacao, id FROM fornecedores;")
        for row in cur.fetchall():
            fornecedores_cache[row[0]] = row[1]
            
    logger.info("Fornecedores pré-existentes em cache: %d", len(fornecedores_cache))
    
    # Coleta fornecedores únicos não existentes
    novos_fornecedores = {}
    senadores_despesas = set()
    
    for d in despesas_raw:
        razao = str(d.get("fornecedor") or "NÃO INFORMADO").strip()
        identity = supplier_identity(d.get("cpfCnpj"), razao, int(d.get("id") or 0))
        key = identity["key"]
        if key not in fornecedores_cache and key not in novos_fornecedores:
            novos_fornecedores[key] = (
                str(d.get("cpfCnpj") or "").strip() or None,
                razao[:255], identity["kind"], identity["normalized_document"],
                identity["normalized_name"], key,
            )
            
        cod_senador = d.get("codSenador")
        nome_senador = d.get("nomeSenador")
        if cod_senador:
            senadores_despesas.add((int(cod_senador), str(nome_senador or "Desconhecido").strip()))

    # Garante que senadores referenciados nas despesas existam na tabela senadores
    if senadores_despesas:
        query_garante_senador = """
            INSERT INTO senadores (id, nome, partido, uf, status, timestamp_ingestao, atualizado_em)
            VALUES (%s, %s, NULL, NULL, 'Histórico', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING;
        """
        with conn.cursor() as cur:
            execute_batch(cur, query_garante_senador, [(s[0], s[1]) for s in senadores_despesas])
        conn.commit()

    # Inserção em lote de novos fornecedores com execute_values
    if novos_fornecedores:
        logger.info("Cadastrando %d novos fornecedores...", len(novos_fornecedores))
        query_ins_forn = """
            INSERT INTO fornecedores
                (cnpj_cpf, razao_social, tipo_identificador, identificador_normalizado,
                 nome_normalizado, chave_deduplicacao, timestamp_ingestao, atualizado_em)
            VALUES %s
            ON CONFLICT (chave_deduplicacao) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                nome_normalizado = EXCLUDED.nome_normalizado,
                atualizado_em = CURRENT_TIMESTAMP;
        """
        with conn.cursor() as cur:
            execute_values(
                cur,
                query_ins_forn,
                list(novos_fornecedores.values()),
                template="(%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                page_size=1000
            )
        conn.commit()
        
        # Atualiza cache com todos os fornecedores
        with conn.cursor() as cur:
            cur.execute("SELECT chave_deduplicacao, id FROM fornecedores;")
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
            
        identity = supplier_identity(d.get("cpfCnpj"), d.get("fornecedor"), int(despesa_id or 0))
        forn_id = fornecedores_cache.get(identity["key"])
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
        "mandatos",
        "exercicios_mandato",
        "filiacoes_partidarias",
        "comissoes",
        "participacoes_comissao",
        "sessao_plenaria",
        "documento_dsf",
        "registro_presenca",
        "licenca_justificativa",
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

        # 3. Mandatos, exercícios e filiações partidárias históricas
        ingest_historico_parlamentar(session, conn, senador_ids)
        
        # 4. Sessões e presenças documentais
        ingest_sessoes_presenca(session, conn, senador_ids)
        
        # 5. Despesas e Fornecedores (CEAPS)
        ingest_ceaps_despesas(session, conn, INGESTION_YEAR)
        
        # 6. Estrutura de Gabinete e Pessoal
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
