import datetime
import logging
import psycopg2
import requests
from psycopg2.extras import execute_batch, execute_values
from bronze.raw import save_raw_payload


logger = logging.getLogger("inflow_ingestor")


def ingest_ceaps_despesas(session: requests.Session, conn: psycopg2.extensions.connection, ano: int, run_id):
    url = f"https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}"
    logger.info(
        "Iniciando ingestão de despesas da CEAPS para o ano de %d a partir de: %s",
        ano,
        url,
        
    )
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    despesas_raw = resp.json()

    save_raw_payload(
        conn,
        entity_type="expenses",
        source_name="senado_ceaps",
        source_url=url,
        payload_json=despesas_raw,
        media_type="application/json",
        run_id=run_id,
        http_status=resp.status_code,
        ingestion_year=ano,
    )

    if not isinstance(despesas_raw, list):
        logger.warning("Formato inesperado na resposta de despesas da CEAPS.")
        return

    logger.info(
        "Total de lançamentos de despesas CEAPS recuperados para %d: %d",
        ano,
        len(despesas_raw),
    )

    # Cache local de fornecedores

    fornecedores_cache = {}

    with conn.cursor() as cur:
        cur.execute("SELECT cnpj_cpf, id FROM oltp.fornecedores;")

        for row in cur.fetchall():
            fornecedores_cache[row[0]] = row[1]

    logger.info("Fornecedores pré-existentes em cache: %d", len(fornecedores_cache))

    # Coleta fornecedores únicos da carga

    fornecedores_da_carga = {}

    senadores_despesas = set()

    for d in despesas_raw:
        raw_cnpj = str(d.get("cpfCnpj") or "").strip()

        razao = str(d.get("fornecedor") or "NÃO INFORMADO").strip()

        if not raw_cnpj:
            raw_cnpj = "SEM_DOCUMENTO"

        if raw_cnpj not in fornecedores_da_carga:
            fornecedores_da_carga[raw_cnpj] = razao[:255]

        cod_senador = d.get("codSenador")

        nome_senador = d.get("nomeSenador")

        if cod_senador:
            senadores_despesas.add(
                (int(cod_senador), str(nome_senador or "Desconhecido").strip())
            )

    # Garante que senadores referenciados nas despesas existam na tabela senadores

    if senadores_despesas:
        query_garante_senador = """
            INSERT INTO oltp.senadores (id, nome, partido, uf, status, timestamp_ingestao, atualizado_em)
            VALUES (%s, %s, 'S/PART', 'DF', 'Exercício Passado', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO NOTHING;
        """

        with conn.cursor() as cur:
            execute_batch(
                cur, query_garante_senador, [(s[0], s[1]) for s in senadores_despesas]
            )

        conn.commit()

    # Upsert em lote dos fornecedores da carga com execute_values

    if fornecedores_da_carga:
        logger.info("Sincronizando %d fornecedores da carga...", len(fornecedores_da_carga))

        query_ins_forn = """
            INSERT INTO oltp.fornecedores (cnpj_cpf, razao_social, timestamp_ingestao, atualizado_em)
            VALUES %s
            ON CONFLICT (cnpj_cpf) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE
                fornecedores.razao_social IS DISTINCT FROM EXCLUDED.razao_social;
        """

        with conn.cursor() as cur:
            execute_values(
                cur,
                query_ins_forn,
                list(fornecedores_da_carga.items()),
                template="(%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                page_size=1000,
            )

        conn.commit()

        # Atualiza cache com todos os fornecedores

        with conn.cursor() as cur:
            cur.execute("SELECT cnpj_cpf, id FROM oltp.fornecedores;")

            for row in cur.fetchall():
                fornecedores_cache[row[0]] = row[1]

        logger.info(
            "Cache de fornecedores atualizado: %d registros.", len(fornecedores_cache)
        )

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

        despesas_records.append(
            (
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
                valor,
            )
        )

    logger.info(
        "Realizando upsert de %d despesas no PostgreSQL...", len(despesas_records)
    )

    query_despesas = """
        INSERT INTO oltp.despesas (
            id, senador_id, fornecedor_id, data_despesa, ano, mes,
            tipo_despesa, tipo_documento, num_documento, detalhamento, valor,
            timestamp_ingestao, atualizado_em
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (id) DO UPDATE SET
            senador_id = EXCLUDED.senador_id,
            fornecedor_id = EXCLUDED.fornecedor_id,
            data_despesa = EXCLUDED.data_despesa,
            ano = EXCLUDED.ano,
            mes = EXCLUDED.mes,
            valor = EXCLUDED.valor,
            tipo_despesa = EXCLUDED.tipo_despesa,
            tipo_documento = EXCLUDED.tipo_documento,
            num_documento = EXCLUDED.num_documento,
            detalhamento = EXCLUDED.detalhamento,
            atualizado_em = CURRENT_TIMESTAMP
        WHERE
            despesas.senador_id IS DISTINCT FROM EXCLUDED.senador_id
            OR despesas.fornecedor_id IS DISTINCT FROM EXCLUDED.fornecedor_id
            OR despesas.data_despesa IS DISTINCT FROM EXCLUDED.data_despesa
            OR despesas.ano IS DISTINCT FROM EXCLUDED.ano
            OR despesas.mes IS DISTINCT FROM EXCLUDED.mes
            OR despesas.valor IS DISTINCT FROM EXCLUDED.valor
            OR despesas.tipo_despesa IS DISTINCT FROM EXCLUDED.tipo_despesa
            OR despesas.tipo_documento IS DISTINCT FROM EXCLUDED.tipo_documento
            OR despesas.num_documento IS DISTINCT FROM EXCLUDED.num_documento
            OR despesas.detalhamento IS DISTINCT FROM EXCLUDED.detalhamento;
    """

    with conn.cursor() as cur:
        execute_batch(cur, query_despesas, despesas_records, page_size=500)

    conn.commit()

    logger.info(
        "Upsert concluído: %d despesas persistidas com sucesso.", len(despesas_records)
    )
