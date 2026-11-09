"""Resumo dos testes de qualidade do dbt por dimensão.

Lê `run_results.json` e `manifest.json` da última invocação do dbt (build ou test) e
agrupa os testes nas seis dimensões de qualidade: esquema, volume, unicidade,
integridade, histórico e distribuição. Só lê arquivos locais; não acessa o banco.

Uso:
    python3 scripts/quality/relatorio_qualidade.py [--target analytics/dbt/target]
                                                   [--json saida.json]

Sai com código 1 se algum teste falhou ou deu erro (avisos não reprovam), 2 se os
artefatos não existem.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

DIMENSOES = ("esquema", "volume", "unicidade", "integridade", "historico", "distribuicao")
ROTULOS = {
    "esquema": "Esquema",
    "volume": "Volume",
    "unicidade": "Unicidade",
    "integridade": "Integridade",
    "historico": "Histórico",
    "distribuicao": "Distribuição",
    "outros": "Outros",
}
# Testes genéricos são classificados pelo nome; singulares, pela tag da pasta
# tests/qualidade/<dimensão>/ (configurada no dbt_project.yml).
POR_TESTE_GENERICO = {
    "esquema_esperado": "esquema",
    "volume_minimo": "volume",
    "volume_igual": "volume",
    "volume_por_grupo": "volume",
    "unique": "unicidade",
    "unicidade_combinada": "unicidade",
    "not_null": "integridade",
    "relationships": "integridade",
    "accepted_values": "integridade",
    "regra_linha": "integridade",
    "intervalo_valores": "distribuicao",
    "proporcao": "distribuicao",
    "concentracao_maxima": "distribuicao",
}
STATUS = ("pass", "warn", "fail", "error", "skipped")
REPROVA = {"fail", "error"}


def dimensao(no: dict) -> str:
    for tag in no.get("tags", []):
        if tag in DIMENSOES:
            return tag
    nome = (no.get("test_metadata") or {}).get("name")
    return POR_TESTE_GENERICO.get(nome, "outros")


def alvo(no: dict) -> str:
    """Modelo ou fonte que o teste verifica, para leitura humana."""
    anexado = no.get("attached_node")
    if not anexado:
        dependencias = (no.get("depends_on") or {}).get("nodes") or []
        anexado = dependencias[0] if dependencias else ""
    partes = anexado.split(".")
    if partes[0] == "source" and len(partes) >= 4:
        return f"{partes[-2]}.{partes[-1]}"
    return partes[-1] if partes else ""


def rotulo(no: dict) -> str:
    """Nome curto: `teste(coluna)` ou `teste(regra)` em vez do nome gerado pelo dbt."""
    meta = no.get("test_metadata")
    if not meta:
        return no.get("name", "")
    argumentos = meta.get("kwargs") or {}
    detalhe = argumentos.get("column_name")
    for chave in ("expressao", "condicao", "colunas", "grupo", "comparar_com"):
        if detalhe is None and argumentos.get(chave) is not None \
                and not isinstance(argumentos[chave], dict):
            detalhe = argumentos[chave]
    if isinstance(detalhe, list):
        detalhe = ", ".join(map(str, detalhe))
    if detalhe is None:
        return meta["name"]
    detalhe = " ".join(str(detalhe).split())
    if len(detalhe) > 70:
        detalhe = detalhe[:67] + "..."
    return f"{meta['name']}({detalhe})"


def resumir(manifest: dict, run_results: dict) -> dict:
    nos = manifest.get("nodes", {})
    contagem = {d: Counter() for d in (*DIMENSOES, "outros")}
    problemas = []
    for resultado in run_results.get("results", []):
        uid = resultado.get("unique_id", "")
        if not uid.startswith("test."):
            continue
        no = nos.get(uid, {})
        dim = dimensao(no)
        status = resultado.get("status", "error")
        contagem[dim][status] += 1
        if status in ("warn", "fail", "error"):
            problemas.append({
                "dimensao": dim,
                "status": status,
                "teste": rotulo(no) or uid.split(".")[-1],
                "unique_id": uid,
                "alvo": alvo(no),
                "linhas_com_problema": resultado.get("failures"),
                "mensagem": next(iter((resultado.get("message") or "").strip().splitlines()), ""),
            })
    ordem = {"error": 0, "fail": 1, "warn": 2}
    problemas.sort(key=lambda p: (ordem[p["status"]], DIMENSOES.index(p["dimensao"])
                                  if p["dimensao"] in DIMENSOES else len(DIMENSOES), p["teste"]))
    dimensoes = {
        d: {s: contagem[d][s] for s in STATUS} | {"total": sum(contagem[d].values())}
        for d in contagem if d != "outros" or contagem[d]
    }
    reprovado = any(p["status"] in REPROVA for p in problemas)
    return {
        "executado_em": (run_results.get("metadata") or {}).get("generated_at"),
        "comando": (run_results.get("args") or {}).get("which"),
        "aprovado": not reprovado,
        "dimensoes": dimensoes,
        "problemas": problemas,
    }


def formatar(resumo: dict) -> str:
    linhas = [
        f"Qualidade dos dados: {'APROVADA' if resumo['aprovado'] else 'REPROVADA'}"
        f" (dbt {resumo['comando'] or '?'} em {resumo['executado_em'] or '?'})",
        "",
        f"{'Dimensão':<14}{'Total':>7}{'Passou':>8}{'Aviso':>7}{'Falhou':>8}{'Erro':>6}{'Pulado':>8}",
    ]
    for dim, c in resumo["dimensoes"].items():
        linhas.append(f"{ROTULOS[dim]:<14}{c['total']:>7}{c['pass']:>8}{c['warn']:>7}"
                      f"{c['fail']:>8}{c['error']:>6}{c['skipped']:>8}")
    if resumo["problemas"]:
        linhas += ["", "Problemas:"]
        for p in resumo["problemas"]:
            qtd = p["linhas_com_problema"]
            detalhe = f"{qtd} linha(s)" if isinstance(qtd, int) and p["status"] != "error" else p["mensagem"]
            linhas.append(f"  [{p['status'].upper()}] {ROTULOS[p['dimensao']]} · {p['alvo']} · "
                          f"{p['teste']}: {detalhe}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", type=Path, default=Path("analytics/dbt/target"),
                        help="diretório com run_results.json e manifest.json")
    parser.add_argument("--json", type=Path, help="grava o resumo também em JSON")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        manifest = json.loads((args.target / "manifest.json").read_text(encoding="utf-8"))
        run_results = json.loads((args.target / "run_results.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(f"Artefato do dbt ausente: {exc.filename}. Rode `make quality` ou `make models`.",
              file=sys.stderr)
        return 2
    resumo = resumir(manifest, run_results)
    print(formatar(resumo))
    if args.json:
        args.json.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if resumo["aprovado"] else 1


if __name__ == "__main__":
    sys.exit(main())
