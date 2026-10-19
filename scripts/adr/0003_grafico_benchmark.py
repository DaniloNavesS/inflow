"""Gera figuras com os dois layouts da versão 2 do benchmark da ADR 0003.

pip install -r scripts/adr/requirements-grafico.txt
python scripts/adr/0003_grafico_benchmark.py
"""
import argparse
import csv
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[2]
ENGINES = ('postgres', 'parquet', 'delta', 'iceberg')
LABELS = ('PostgreSQL', 'DuckDB + Parquet', 'DuckDB + Delta', 'DuckDB + Iceberg')
COLORS = ('#26456E', '#007F73', '#BE641A', '#7953A3')
LAYOUTS = ('sem_particao', 'ano_mes')
QUERIES = ('agregacao_completa', 'filtro_mensal', 'busca_por_id')
TITLES = ('Agregação por senador e categoria', 'Filtro por ano e mês', 'Busca por ID')


def load(path):
    document = json.loads(path.read_text())
    if document['metadados'].get('versao_experimento') != 2:
        raise ValueError(f'{path}: refaça a medição com os dois layouts (benchmark v2).')
    records = document['resultados']
    volumes = sorted({row['linhas'] for row in records})
    lookup = {}
    for n in volumes:
        for query in QUERIES:
            subset = [r for r in records if r['linhas'] == n and r['consulta'] == query]
            expected = sorted((fmt, layout) for layout in LAYOUTS for fmt in ENGINES[1:])
            if sorted((r['formato'], r['layout']) for r in subset) != expected:
                raise ValueError(f'{path}: seis combinações únicas são obrigatórias em {n}/{query}.')
            pg = subset[0]['amostras_postgres_ms']
            if any(r['amostras_postgres_ms'] != pg for r in subset):
                raise ValueError('A referência PostgreSQL deve ser a mesma nos dois layouts.')
            for layout in LAYOUTS:
                lookup[n, query, layout, 'postgres'] = pg
            for r in subset:
                samples = r['amostras_formato_ms']
                if not samples or min(samples) <= 0:
                    raise ValueError('Amostras positivas são obrigatórias.')
                if abs(statistics.median(samples) - r['consulta_ms']) > 1e-6:
                    raise ValueError('Mediana publicada diverge das amostras.')
                lookup[n, query, r['layout'], r['formato']] = samples
    return document, volumes, lookup


def stats(samples):
    median = statistics.median(samples)
    return median, median - min(samples), max(samples) - median


def style():
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'svg.fonttype': 'none', 'axes.spines.top': False,
                         'axes.spines.right': False})


def figure(document, volumes, lookup, output, real):
    fig, axes = plt.subplots(2, 3, figsize=(16, 10), sharey='col')
    titles = ('SEM PARTICIONAMENTO — todos os três formatos',
              'PARTICIONADOS POR ANO/MÊS — todos os três formatos')
    for row, layout in enumerate(LAYOUTS):
        for col, (query, title) in enumerate(zip(QUERIES, TITLES)):
            ax = axes[row, col]
            ax.set_title(title, fontsize=11, pad=14)
            if real:
                values = [stats(lookup[volumes[0], query, layout, e]) for e in ENGINES]
                medians, below, above = zip(*values)
                ax.bar(range(4), medians, color=COLORS, width=.65,
                       yerr=[below, above], capsize=3, error_kw={'linewidth': 1})
                for i, value in enumerate(medians):
                    ax.annotate(f'{value:.2f}'.replace('.', ','), (i, value + above[i]),
                                xytext=(0, 5), textcoords='offset points', ha='center', fontsize=10)
                ax.set_xticks(range(4), ['PostgreSQL', 'Parquet', 'Delta', 'Iceberg'], rotation=15)
                peak = max(max(lookup[volumes[0], query, part, e]) for part in LAYOUTS for e in ENGINES)
                ax.set_ylim(0, peak * 1.3)
                ax.set_ylabel('Tempo (ms) — menor é melhor')
                ax.grid(axis='y', alpha=.18)
                ax.set_axisbelow(True)
            else:
                for e, label, color in zip(ENGINES, LABELS, COLORS):
                    values = [stats(lookup[n, query, layout, e]) for n in volumes]
                    medians, below, above = zip(*values)
                    ax.errorbar(volumes, medians, yerr=[below, above], label=label, color=color,
                                marker='o', linewidth=1.8, markersize=5, capsize=3)
                ax.set_xscale('log')
                ax.set_yscale('log')
                ax.set_xticks(volumes, [f'{n:,}'.replace(',', '.') for n in volumes])
                ax.set_xlabel('Quantidade de despesas sintéticas')
                ax.set_ylabel('Tempo (ms, escala logarítmica)')
                ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:g}'.replace('.', ',')))
                ax.grid(which='major', alpha=.2)
    origin = f'Base real: {volumes[0]:,} despesas CEAPS'.replace(',', '.') if real else 'Escala sintética: 10 mil, 100 mil e 1 milhão de despesas'
    fig.suptitle(f'Particionar por ano e mês muda o desempenho?\n{origin}', fontsize=17, y=.985)
    fig.text(.055, .885, titles[0], fontsize=12, weight='bold')
    fig.text(.055, .475, titles[1], fontsize=12, weight='bold')
    handles = [plt.Line2D([0], [0], color=c, marker='o', label=l) for c, l in zip(COLORS, LABELS)]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(.5, .055), ncol=4, frameon=False)
    repetitions = document['metadados']['repeticoes']
    fig.text(.055, .025,
             f'Medianas de {repetitions} repetições após aquecimento; barras de erro = mínimo–máximo observado. Tempos incluem fetch, sem exportação.\n'
             'PostgreSQL conserva seus índices e a mesma referência nos dois painéis. Mesma escala vertical por coluna. '
             'Parquet, Delta e Iceberg usam ZSTD.', fontsize=9, color='#4B5563')
    fig.subplots_adjust(left=.065, right=.98, top=.84, bottom=.16, hspace=.62, wspace=.3)
    for extension in ('svg', 'png'):
        kwargs = {'metadata': {'Title': 'ADR 0003 — comparação de particionamento', 'Date': None}} if extension == 'svg' else {'dpi': 160}
        fig.savefig(output.with_suffix('.' + extension), **kwargs)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', type=Path, default=ROOT / 'documentation/static/data/adr-0003/base-real.json')
    parser.add_argument('--synthetic', type=Path, default=ROOT / 'documentation/static/data/adr-0003/escala-sintetica.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'documentation/static/img/adr-0003')
    args = parser.parse_args()
    real_doc, real_ns, real = load(args.real)
    synth_doc, synth_ns, synth = load(args.synthetic)
    if len(real_ns) != 1 or real_doc['metadados']['origem'] != 'oltp' or synth_doc['metadados']['origem'] != 'synthetic':
        parser.error('As origens real e sintética devem estar identificadas corretamente.')
    for field in ('duckdb', 'deltalake', 'pyiceberg', 'pyarrow', 'repeticoes', 'script_sha256', 'layouts'):
        if real_doc['metadados'][field] != synth_doc['metadados'][field]:
            parser.error(f'Experimentos diferem em {field}; gere medições sob a mesma metodologia.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    style()
    figure(real_doc, real_ns, real, args.output_dir / 'base-real-particionamento', True)
    figure(synth_doc, synth_ns, synth, args.output_dir / 'escala-sintetica-particionamento', False)
    with (args.output_dir / 'medicoes.csv').open('w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['origem', 'linhas', 'consulta', 'layout', 'caminho', 'mediana_ms', 'minimo_ms', 'maximo_ms'])
        for origin, ns, lookup in (('real', real_ns, real), ('synthetic', synth_ns, synth)):
            for n in ns:
                for query in QUERIES:
                    for layout in LAYOUTS:
                        for engine in ENGINES:
                            samples = lookup[n, query, layout, engine]
                            writer.writerow([origin, n, query, layout, engine, statistics.median(samples), min(samples), max(samples)])
    print(f'Figuras SVG/PNG e CSV gerados em {args.output_dir}')


if __name__ == '__main__':
    main()
