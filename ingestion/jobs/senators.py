import logging
import time

import psycopg2
import requests
from psycopg2.extras import execute_batch

from bronze.raw import save_raw_payload
from config import LEGISLATURE, LIMIT_SENADORES

logger = logging.getLogger("inflow_ingestion")

def ingest_senadores(session: requests.Session, conn: psycopg2.extensions.connection, run_id) -> list:
    current_url = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json"
    legislature_url = f"https://legis.senado.leg.br/dadosabertos/senador/lista/legislatura/{LEGISLATURE}.json"
    logger.info("Iniciando ingestão de senadores atuais e da %dª legislatura.", LEGISLATURE)

    current_response = session.get(current_url, timeout=60)
    current_response.raise_for_status()
    current_payload = current_response.json()
    save_raw_payload(
        conn, entity_type="senators_current", source_name="senado_legislativo",
        source_url=current_url, run_id=run_id, payload_json=current_payload,
        media_type="application/json", http_status=current_response.status_code,
    )
    current = current_payload.get("ListaParlamentarEmExercicio", {}).get("Parlamentares", {}).get("Parlamentar", [])
    if isinstance(current, dict):
        current = [current]
    current_ids = {
        int(item["IdentificacaoParlamentar"]["CodigoParlamentar"])
        for item in current
    }

    legislature_response = session.get(legislature_url, timeout=60)
    legislature_response.raise_for_status()
    legislature_payload = legislature_response.json()
    save_raw_payload(
        conn, entity_type="senators_legislature", source_name="senado_legislativo",
        source_url=legislature_url, run_id=run_id, payload_json=legislature_payload,
        media_type="application/json", http_status=legislature_response.status_code,
    )
    historical = legislature_payload.get("ListaParlamentarLegislatura", {}).get("Parlamentares", {}).get("Parlamentar", [])
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


def ingest_historico_parlamentar(session, conn, senador_ids: list, run_id):
    logger.info("Iniciando ingestão de mandatos, exercícios e filiações.")
    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]
    mandatos, exercicios, filiacoes = [], [], []
    for index, senator_id in enumerate(target_ids, 1):
        try:
            mandates_url = f"https://legis.senado.leg.br/dadosabertos/senador/{senator_id}/mandatos.json"
            response = session.get(mandates_url, timeout=30)
            if response.status_code == 200:
                mandates_payload = response.json()
                save_raw_payload(
                    conn, entity_type="mandates", source_name="senado_legislativo",
                    source_url=mandates_url, run_id=run_id, payload_json=mandates_payload,
                    media_type="application/json", http_status=response.status_code,
                )
                parliamentary = mandates_payload.get("MandatoParlamentar", {}).get("Parlamentar", {})
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

            affiliations_url = f"https://legis.senado.leg.br/dadosabertos/senador/{senator_id}/filiacoes.json"
            response = session.get(affiliations_url, timeout=30)
            if response.status_code == 200:
                affiliations_payload = response.json()
                save_raw_payload(
                    conn, entity_type="party_affiliations", source_name="senado_legislativo",
                    source_url=affiliations_url, run_id=run_id, payload_json=affiliations_payload,
                    media_type="application/json", http_status=response.status_code,
                )
                parliamentary = affiliations_payload.get("FiliacaoParlamentar", {}).get("Parlamentar", {})
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
