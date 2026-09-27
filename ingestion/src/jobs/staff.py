import logging
import time
import psycopg2
import requests
from psycopg2.extras import execute_batch
from config import LIMIT_SENADORES
from bronze.raw import save_raw_payload

logger = logging.getLogger("inflow_ingestor")


def ingest_estrutura_gabinete(
    session: requests.Session,
    conn: psycopg2.extensions.connection,
    senador_ids: list,
    ano: int,
    run_id
):

    logger.info(
        "Iniciando ingestão de Estrutura de Gabinete e Pessoal para o ano %d...", ano
    )

    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]

    registros_estrutura = []

    for idx, sen_id in enumerate(target_ids, 1):
        url = f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/{sen_id}/recursos-utilizados?ano={ano}"

        try:
            resp = session.get(url, timeout=30)

            if resp.status_code == 200:
                payload = resp.json()

                save_raw_payload(
                    conn,
                    entity_type="staff",
                    source_name="senado_administrativo",
                    source_url=url,
                    payload_json=payload,
                    media_type="application/json",
                    run_id=run_id,
                    http_status=resp.status_code,
                    ingestion_year=ano,
                )

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

                    registros_estrutura.append(
                        (
                            sen_id,
                            ano_dado,
                            qtd_gabinete,
                            qtd_escritorio,
                            auxilio_moradia,
                            imovel_funcional,
                        )
                    )

            time.sleep(0.12)

        except Exception as e:
            logger.warning(
                "Falha ao consultar estrutura de gabinete do senador %d: %s", sen_id, e
            )

        if idx % 20 == 0 or idx == len(target_ids):
            logger.info(
                "Processamento de estrutura de gabinete: %d/%d senadores analisados.",
                idx,
                len(target_ids),
            )

    if registros_estrutura:
        query_est = """

            INSERT INTO oltp.estrutura_gabinete (
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

        logger.info(
            "Upsert concluído: %d registros de estrutura de pessoal persistidos.",
            len(registros_estrutura),
        )
