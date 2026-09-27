import logging
import time

import psycopg2
import requests
from psycopg2.extras import execute_batch

from config import LIMIT_SENADORES

logger = logging.getLogger("inflow_ingestion")

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

