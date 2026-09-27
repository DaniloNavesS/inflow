import logging
import time
import psycopg2
import requests
from psycopg2.extras import execute_batch
from config import LIMIT_SENADORES
from bronze.raw import save_raw_payload

logger = logging.getLogger("inflow_ingestor")


def ingest_sessoes_presenca(
    session: requests.Session, conn: psycopg2.extensions.connection, senador_ids: list, run_id
):

    logger.info("Iniciando ingestão de Sessões e Presenças (Votações Nominais)...")

    target_ids = senador_ids if LIMIT_SENADORES <= 0 else senador_ids[:LIMIT_SENADORES]

    registros_presenca = []

    for idx, sen_id in enumerate(target_ids, 1):
        url = f"https://legis.senado.leg.br/dadosabertos/votacao?codigoParlamentar={sen_id}"

        try:
            resp = session.get(url, timeout=30)

            if resp.status_code == 200:
                data = resp.json()

                save_raw_payload(
                    conn,
                    entity_type="sessions",
                    source_name="senado_legislativo",
                    source_url=url,
                    payload_json=data,
                    media_type="application/json",
                    run_id=run_id,
                    http_status=resp.status_code,
                )

                if isinstance(data, list):
                    # Ingerir as últimas 30 votações por parlamentar

                    for item in data[:30]:
                        sessao_id = item.get("codigoSessao")

                        data_sessao = item.get("dataSessao")

                        tipo_sessao = (
                            item.get("siglaTipoSessao")
                            or item.get("sigla")
                            or "Plenário"
                        )

                        if not sessao_id or not data_sessao:
                            continue

                        presenca = "Presente"

                        votos = item.get("votos", [])

                        if votos:
                            voto_sen = next(
                                (
                                    v
                                    for v in votos
                                    if v.get("codigoParlamentar") == sen_id
                                ),
                                None,
                            )

                            if voto_sen:
                                presenca = (
                                    voto_sen.get("siglaVotoParlamentar") or "Votou"
                                )

                        registros_presenca.append(
                            (int(sessao_id), sen_id, data_sessao, presenca, tipo_sessao)
                        )

            time.sleep(0.12)

        except Exception as e:
            logger.warning(
                "Falha ao consultar sessões/presenças do senador %d: %s", sen_id, e
            )

        if idx % 20 == 0 or idx == len(target_ids):
            logger.info(
                "Processamento de presenças: %d/%d senadores analisados.",
                idx,
                len(target_ids),
            )

    if registros_presenca:
        query_presenca = """

            INSERT INTO oltp.sessoes_presenca (
                sessao_id, senador_id, data_sessao, presenca, tipo_sessao, timestamp_ingestao
            ) VALUES (
                %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (sessao_id, senador_id, data_sessao) DO UPDATE SET
                presenca = EXCLUDED.presenca,
                tipo_sessao = EXCLUDED.tipo_sessao;
        """

        with conn.cursor() as cur:
            execute_batch(cur, query_presenca, registros_presenca, page_size=200)

        conn.commit()

        logger.info(
            "Upsert concluído: %d registros de presença/sessões persistidos.",
            len(registros_presenca),
        )
