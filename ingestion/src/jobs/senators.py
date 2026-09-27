import logging
import psycopg2
import requests
from psycopg2.extras import execute_batch

logger = logging.getLogger("inflow_ingestor")

def ingest_senadores(
    session: requests.Session, conn: psycopg2.extensions.connection
) -> list:

    url = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json"

    logger.info("Iniciando ingestão de Senadores atuais a partir de: %s", url)

    resp = session.get(url, timeout=60)

    resp.raise_for_status()

    data = resp.json()

    parlamentares = (
        data.get("ListaParlamentarEmExercicio", {})
        .get("Parlamentares", {})
        .get("Parlamentar", [])
    )

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

        records.append(
            (cod, nome, nome_completo, partido, uf, foto_url, pagina_url, email, status)
        )

        senador_ids.append(cod)

    query = """
        INSERT INTO oltp.senadores (
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
