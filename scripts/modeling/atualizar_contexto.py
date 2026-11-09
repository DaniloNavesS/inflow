"""Recorte mensal auditável de mandatos e partidos, sem usar o cadastro atual."""
import argparse
import calendar
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ['senador_id', 'ano', 'mes', 'dias_exercicio', 'partido_competencia',
          'uf_competencia', 'status_partido', 'status_uf', 'source_url',
          'fonte_sha256', 'coletado_em']


def items(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def date(value):
    return dt.date.fromisoformat(value) if value else None


def monthly_context(payload, senator_id, year):
    """Classifica todos os dias em exercício; não resolve conflitos por aproximação."""
    parliament = payload['MandatoParlamentar']['Parlamentar']
    if int(parliament['Codigo']) != senator_id:
        raise ValueError('Identidade divergente da requisição')
    mandates = items((parliament.get('Mandatos') or {}).get('Mandato'))
    exercises, affiliations = [], set()
    for mandate in mandates:
        terms = [mandate.get(key) or {} for key in (
            'PrimeiraLegislaturaDoMandato', 'SegundaLegislaturaDoMandato')]
        starts = [date(t.get('DataInicio')) for t in terms if t.get('DataInicio')]
        ends = [date(t.get('DataFim')) for t in terms if t.get('DataFim')]
        if not starts or not ends:
            raise ValueError('Mandato sem limites publicados')
        start, end = min(starts), max(ends)
        for exercise in items((mandate.get('Exercicios') or {}).get('Exercicio')):
            begin = date(exercise.get('DataInicio'))
            if begin is None:
                raise ValueError('Exercício sem início publicado')
            finish = date(exercise.get('DataFim')) or end
            if finish < begin:
                raise ValueError('Intervalo de exercício invertido')
            exercises.append((max(start, begin), min(end, finish), mandate.get('UfParlamentar')))
        for party in items((mandate.get('Partidos') or {}).get('Partido')):
            begin = date(party.get('DataFiliacao'))
            finish = date(party.get('DataDesfiliacao')) or dt.date.max
            if begin:
                if finish < begin:
                    raise ValueError('Intervalo de filiação invertido')
                affiliations.add((begin, finish, party.get('Sigla')))
    rows = []
    for month in range(1, 13):
        active_days, parties, states = 0, set(), set()
        party_gap = state_gap = False
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            point = dt.date(year, month, day)
            active = [uf for begin, end, uf in exercises if begin <= point <= end]
            if not active:
                continue
            active_days += 1
            day_states = {uf for uf in active if uf}
            day_parties = {sigla for begin, end, sigla in affiliations
                           if begin <= point <= end and sigla}
            state_gap |= not day_states
            party_gap |= not day_parties
            states.update(day_states)
            parties.update(day_parties)
        def classify(values, gap):
            if not active_days:
                return '', 'SEM_EXERCICIO'
            if len(values) > 1:
                return '', 'MULTIPLOS'
            if gap or not values:
                return '', 'SEM_COBERTURA'
            return next(iter(values)), 'UNICO'
        party, party_status = classify(parties, party_gap)
        uf, uf_status = classify(states, state_gap)
        rows.append(dict(senador_id=senator_id, ano=year, mes=month,
                         dias_exercicio=active_days, partido_competencia=party,
                         uf_competencia=uf, status_partido=party_status, status_uf=uf_status))
    return rows


def load_history(senator_id, year, use_cache):
    url = f'https://legis.senado.leg.br/dadosabertos/senador/{senator_id}/mandatos.json'
    cache = ROOT / 'resultados' / 'contexto-parlamentar' / str(year) / f'{senator_id}.json'
    if use_cache:
        raw = cache.read_bytes()
        observed = dt.datetime.fromtimestamp(cache.stat().st_mtime, dt.timezone.utc).isoformat()
    else:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={'Accept': 'application/json',
                                                           'User-Agent': 'MandatoAberto/academic'})
                with urllib.request.urlopen(req, timeout=45) as response:
                    raw = response.read()
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        observed = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = monthly_context(json.loads(raw), senator_id, year)
    if not use_cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    for row in rows:
        row.update(source_url=url, fonte_sha256=hashlib.sha256(raw).hexdigest(), coletado_em=observed)
    return rows


def write_seed(target, rows):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False, newline='') as stream:
            tmp = stream.name
            os.fchmod(stream.fileno(), 0o644)
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, target)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ano', type=int, default=2024)
    parser.add_argument('--usar-cache', action='store_true', help='Reprocessa as respostas locais sem HTTP')
    args = parser.parse_args()
    if not 2000 <= args.ano <= 2100:
        parser.error('Ano deve estar entre 2000 e 2100')
    result = subprocess.run([
        'docker', 'compose', 'exec', '-T', 'postgres', 'sh', '-c',
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 -c '
        f"'SELECT DISTINCT senador_id FROM oltp.despesas WHERE ano={args.ano} ORDER BY senador_id'",
    ], cwd=ROOT, check=True, capture_output=True, text=True)
    ids = [int(line) for line in result.stdout.splitlines() if line.strip()]
    if not ids:
        raise SystemExit('Nenhuma despesa no ano solicitado; contexto existente preservado')
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda senator: load_history(senator, args.ano, args.usar_cache), ids))
    target = ROOT / 'analytics/dbt/seeds/contexto_parlamentar.csv'
    previous = []
    if target.exists():
        with target.open() as stream:
            previous = [row for row in csv.DictReader(stream) if int(row['ano']) != args.ano]
    rows = previous + [row for batch in batches for row in batch]
    rows.sort(key=lambda r: (int(r['senador_id']), int(r['ano']), int(r['mes'])))
    write_seed(target, rows)
    print(f'Contexto {args.ano}: {len(ids)} senadores, {len(ids) * 12} competências; {target}')


if __name__ == '__main__':
    main()
