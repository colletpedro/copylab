"""Gera `docs/verificacao-de-dados.md` a partir de `data/verify/results/*.json`.

Só formata o que os scripts mediram: tabelas, números e status. As seções narrativas
("O que contradiz a spec", "O que não foi possível medir") listam o que o código detecta
sozinho; o que exige leitura é escrito à mão no documento final.

No modo `--smoke` o relatório vai para `data/verify/_smoke/report.md` e **não** substitui
o de `docs/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    API_WEIGHT_LIMIT_PER_MIN,
    CUTOFF_MS,
    REPO_ROOT,
    SEED,
    WINDOW_START_MS,
    Ctx,
    code_version,
    iso,
    now_ms,
    read_json,
)

CRITERIA = [
    "RF-VER-01 CA-01.1",
    "RF-VER-01 CA-01.2",
    "RF-VER-01 CA-01.3",
    "RF-VER-01 CA-01.4",
    "RF-VER-01 CA-01.5",
    "RF-VER-02 CA-02.1",
    "RF-VER-02 CA-02.2",
    "RF-VER-03 CA-03.1",
    "RF-VER-03 CA-03.2",
    "RF-VER-04 CA-04.1",
    "RF-VER-04 CA-04.2",
    "RF-VER-04 CA-04.3",
]
GB = 1024**3
MB = 1024**2


def pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def num(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:,.{digits}f}"


def size(n: float | None) -> str:
    if n is None:
        return "—"
    if n >= GB:
        return f"{n / GB:.2f} GB"
    if n >= MB:
        return f"{n / MB:.1f} MB"
    return f"{n / 1024:.1f} kB"


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def load(ctx: Ctx, name: str) -> dict[str, Any] | None:
    path = ctx.path("results", f"{name}.json")
    data: dict[str, Any] | None = read_json(path) if path.exists() else None
    return data


def collect_criteria(results: dict[str, dict[str, Any] | None]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for res in results.values():
        if res:
            found.update(res.get("criteria", {}))
    for cid in CRITERIA:
        found.setdefault(
            cid, {"status": "não medido", "measured": {}, "rule": "", "note": "etapa não executada"}
        )
    return found


def short(cid: str, c: dict[str, Any]) -> str:
    m = c["measured"]
    if not m:
        return c.get("note") or "—"
    try:
        if cid.endswith("CA-01.1"):
            worst = min(v["ok"] for v in m["fields"].values())
            return f"{m['fills']:,} fills; pior campo {pct(worst, 2)} presente e interpretável"
        if cid.endswith("CA-01.2"):
            return (
                f"{len(m['wallets'])} carteiras; mais de 10.000 fills devolvidos em "
                f"{m['exceeds_documented_cap']}; exatamente 10.000 em {m['at_documented_cap']}; "
                f"histórico começa antes da janela em {pct(m['reaches_window_start'])}"
            )
        if cid.endswith("CA-01.3"):
            return f"{m['rows']:,} linhas; menor patrimônio US$ {num(m['min_account_value'])}"
        if cid.endswith("CA-01.4"):
            return f"{m['conciliation']}; {m['detail']}"
        if cid.endswith("CA-01.5"):
            return f"{m['with_both_addresses']:,} de {m['trades']:,} negócios com as duas pontas"
        if cid.endswith("CA-02.1"):
            return (
                f"universo = {pct(m['universe_cumulative_all_fills'])} (todos os fills) / "
                f"{pct(m['universe_cumulative_perps_only'])} (só perpétuos)"
            )
        if cid.endswith("CA-02.2"):
            return (
                f"acumulado {pct(m['cumulative_all_fills'])} (todos) / "
                f"{pct(m['cumulative_perps_only'])} (perpétuos)"
            )
        if cid.endswith("CA-03.1"):
            return "fills por ativo: " + ", ".join(
                f"{k} {v['fills']:,}" for k, v in m["per_coin"].items()
            )
        if cid.endswith("CA-03.2"):
            return ", ".join(
                f"{k}: {v['verdict']} (n={v['fills']})" for k, v in m["per_coin"].items()
            )
        if cid.endswith("CA-04.1"):
            t = m["total"]["default"]
            return f"{m['duration_min']:.0f} min; 45 dias = {size(t['bytes_45d'])} bruto / {size(t['gzip_bytes_45d'])} gzip"
        if cid.endswith("CA-04.2"):
            return f"proxy, {m['days_assumed_all_windows']} dias: {size(m['total']['zip_all'])} em zips"
        if cid.endswith("CA-04.3"):
            return f"orçamento {m['budget_gb']:.0f} GB; maior extrapolação individual {num(max(r['gb'] for r in m['individual']))} GB"
    except (KeyError, ValueError, TypeError):
        return c.get("note") or "ver detalhe"
    return c.get("note") or "—"


def size_and_break_tables(
    by_size: dict[str, int], breaks: dict[str, Any], pairs_broken: int
) -> str:
    """Conciliação por tamanho de episódio e diagnóstico das quebras de continuidade."""
    out = ""
    if by_size:
        rows = []
        for band in ("2", "3-4", "5+"):
            n = by_size.get(f"{band}|tested", 0)
            if n:
                rows.append(
                    [
                        f"{band} fills",
                        n,
                        f"{by_size.get(f'{band}|gross@1e-06', 0)} ({pct(by_size.get(f'{band}|gross@1e-06', 0) / n)})",
                        f"{by_size.get(f'{band}|gross@0.001', 0)} ({pct(by_size.get(f'{band}|gross@0.001', 0) / n)})",
                    ]
                )
        out += "Hipótese bruta por número de fills do episódio:\n\n"
        out += (
            table(["Episódio", "Testados", "Concilia em 1e-6", "Concilia em 1e-3"], rows) + "\n\n"
        )
    if breaks and pairs_broken:
        out += (
            f"Diagnóstico das {pairs_broken} quebras de continuidade: `dir` do fill anterior "
            f"{breaks['prev_dir']}; tamanho do salto {breaks['jump']}; com campo `liquidation` em um "
            f"dos dois fills: {breaks['with_liquidation_field']}; intervalo entre os dois fills: "
            f"mediana {num(breaks['gap_s_p50'], 0)} s, máximo {num(breaks['gap_s_max'], 0)} s, "
            f"{breaks['gap_s_under_1']} com menos de 1 s.\n\n"
        )
    return out


def ladder_tables(ladder: dict[str, dict[str, int]], per_fill: dict[str, int]) -> str:
    """Escada de tolerâncias (episódios) e conferência por fill de `closedPnl`. Só contagens."""
    rows = []
    for tol, c in ladder.items():
        tested = c.get("tested", 0)
        rows.append(
            [tol, tested]
            + [
                f"{c.get(h, 0)} ({pct(c.get(h, 0) / tested if tested else None)})"
                for h in ("gross", "net_all", "net_close")
            ]
        )
    out = "Episódios que conciliam, por tolerância (relativa e absoluta iguais):\n\n"
    out += (
        table(["Tolerância", "Episódios testados", "gross", "net_all", "net_close"], rows) + "\n\n"
    )
    if per_fill:
        tols = sorted({k.split("@")[1] for k in per_fill if "@" in k}, key=float)
        rows = []
        for tol in tols:
            o, c = per_fill.get("open_fills", 0), per_fill.get("close_fills", 0)
            rows.append(
                [
                    tol,
                    f"{per_fill.get(f'open_zero@{tol}', 0)} / {o}",
                    f"{per_fill.get(f'open_minus_fee@{tol}', 0)} / {o}",
                    f"{per_fill.get(f'close_gross@{tol}', 0)} / {c}",
                    f"{per_fill.get(f'close_minus_fee@{tol}', 0)} / {c}",
                ]
            )
        out += "Conferência fill a fill (aberturas devem ter `closedPnl` 0 se for bruto, ou menos a taxa se for líquido; "
        out += "fechamentos devem ter o realizado, com ou sem a própria taxa):\n\n"
        out += (
            table(
                [
                    "Tolerância",
                    "abertura = 0",
                    "abertura = -taxa",
                    "fechamento = realizado",
                    "fechamento = realizado - taxa",
                ],
                rows,
            )
            + "\n"
        )
    return out


def build(ctx: Ctx) -> Path:
    results = {n: load(ctx, n) for n in ("v01", "v02", "v03", "v04")}
    crit = collect_criteria(results)
    v01, v02, v03, v04 = (results[n] for n in ("v01", "v02", "v03", "v04"))
    state_path = ctx.path("run_state.json")
    runs = read_json(state_path)["runs"] if state_path.exists() else []
    board_path = ctx.path("leaderboard.json")
    board = read_json(board_path) if board_path.exists() else None

    out: list[str] = []
    w = out.append
    w("# Verificação de dados (§4.1)\n")
    w(
        "> Gerado por `scripts/verify/report.py` a partir de `data/verify/results/`. "
        "Mede e reporta; não decide nada e não altera nenhuma spec.\n"
    )
    w("## Execução\n")
    started = runs[0]["started"] if runs else "—"
    finished = next((r["finished"] for r in reversed(runs) if "finished" in r), "—")
    meta_rows = [
        ["Início da primeira execução", started],
        ["Fim da última execução", finished],
        ["Relatório gerado em", iso(now_ms())],
        ["Semente de toda amostragem", f"`{SEED}`"],
        ["Versão do código", f"`{code_version()}`"],
        ["Modo", "**smoke (reduzido)**" if ctx.smoke else "completo"],
        [
            "Janela de seleção (conteúdo dos fills)",
            f"{iso(WINDOW_START_MS)} a {iso(CUTOFF_MS)} (exclusivo)",
        ],
    ]
    if board:
        meta_rows += [
            [
                "Snapshot do leaderboard",
                f"{iso(board['retrieved_at_ms'])}; {board['n_rows']:,} linhas; "
                f"{size(board['size_bytes'])}; sha256 `{board['sha256'][:16]}…`",
            ],
        ]
    w(table(["Item", "Valor"], meta_rows) + "\n")
    usage_path = ctx.path("results", "api_usage.json")
    usage = read_json(usage_path) if usage_path.exists() else None
    if usage:
        w(
            "**Uso da API de informação** (orçamento de peso da verificação: "
            f"{usage['v01']['limit']}/min; teto documentado: {API_WEIGHT_LIMIT_PER_MIN}/min)\n"
        )
        rows = [
            [
                name,
                u["requests"],
                u["weight"],
                u["http_429"],
                u["retries"],
                u["peak"],
                f"{u['waited_min']:.1f} min",
            ]
            for name, u in (("v01", usage["v01"]), ("v02", usage["v02"]))
        ]
        w(
            table(
                [
                    "Etapa",
                    "Requisições",
                    "Peso gasto",
                    "HTTP 429",
                    "Retentativas",
                    "Pico em 60 s",
                    "Espera por orçamento",
                ],
                rows,
            )
            + "\n"
        )
        w(
            "O pico é o maior peso acumulado numa janela deslizante de 60 s, contado com a reserva "
            "pessimista (120 por página de fills) antes de a resposta chegar. "
            + usage["note"]
            + "\n"
        )

    w("## Resumo dos 12 critérios\n")
    w(
        table(
            ["Critério", "Status", "Medido"],
            [[f"`{c}`", f"**{crit[c]['status']}**", short(c, crit[c])] for c in CRITERIA],
        )
        + "\n"
    )

    # ─── RF-VER-01 ────────────────────────────────────────────────────────────
    w("## RF-VER-01 — esquema e retenção da API\n")
    w(
        table(
            ["Critério", "Regra da spec", "Medido", "Status"],
            [
                [
                    f"`{c.split()[1]}`",
                    crit[c]["rule"],
                    short(c, crit[c]),
                    f"**{crit[c]['status']}**",
                ]
                for c in CRITERIA[:5]
            ],
        )
        + "\n"
    )
    if v01:
        w(
            f"Amostra: {len(v01['sample'])} carteiras sorteadas do leaderboard inteiro (endereços ordenados antes do "
            f"sorteio, semente `{SEED}`); falhas de coleta: {len(v01['failures'])}.\n"
        )
        m = crit["RF-VER-01 CA-01.1"]["measured"]
        if m and "fields" in m:
            w("### CA-01.1 — campos por fill\n")
            w(
                table(
                    ["Campo", "Presente", "Presente e interpretável"],
                    [
                        [f"`{k}`", pct(v["present"], 2), pct(v["ok"], 2)]
                        for k, v in m["fields"].items()
                    ],
                )
                + "\n"
            )
            w(
                f"Fills analisados: {m['fills']:,}. Campos que reprovam: {m['failing_fields'] or 'nenhum'}.\n"
            )
            w("Pior campo por tipo de ativo:\n")
            w(
                table(
                    ["Tipo", "Fills", "Pior campo (interpretável)"],
                    [[k, f"{v['fills']:,}", pct(v["min_ok"], 2)] for k, v in m["per_kind"].items()],
                )
                + "\n"
            )
        w(
            f"Campos presentes nos fills além dos 12 da spec: {v01['unexpected_fields'] or 'nenhum'}.\n"
        )
        w(f"Valores de `dir` observados: {v01['dir_values']}.\n")

        m = crit["RF-VER-01 CA-01.2"]["measured"]
        if m and "wallets" in m:
            w("### CA-01.2 — retenção por carteira\n")
            rows = []
            for x in m["wallets"]:
                mark = ">" if x["lower_bound"] else ""
                rows.append(
                    [
                        f"`{x['address']}`",
                        x["in_window"],
                        x["pre_window"],
                        x["post_window"],
                        f"{mark}{x['total']:,}",
                        x["oldest"] or "—",
                        x["history_starts"],
                        "sim" if x["exceeds_cap"] else ("exatamente" if x["at_cap"] else "não"),
                    ]
                )
            w(
                table(
                    [
                        "Carteira",
                        "Fills na janela",
                        "Antes da janela (contagem)",
                        "Depois do corte (só contagem)",
                        "Total devolvido",
                        "Mais antigo",
                        "O histórico começa",
                        "Passou de 10.000",
                    ],
                    rows,
                )
                + "\n"
            )
            w(
                f"Histórico por categoria: {m['history_starts']}. Maior total contado: "
                f"{m['max_total_counted']:,}. Contagens com `>` pararam cedo, ao provar que a carteira "
                "passa de 10.000 fills (a paginação não prosseguiu). Nenhum fill de antes da janela "
                "ou do corte teve o conteúdo guardado: só contagem e o instante do mais antigo.\n"
            )
            w(
                f"Fills que compartilham `tid` com outro fill da mesma carteira: "
                f"{v01['fills_sharing_a_tid_within_wallet']}.\n"
            )

        m = crit["RF-VER-01 CA-01.3"]["measured"]
        if m and "rows" in m:
            w("### CA-01.3 — leaderboard\n")
            w(
                table(
                    ["Medida", "Valor"],
                    [
                        ["Linhas", f"{m['rows']:,}"],
                        ["Campos por linha (contagem de linhas que o trazem)", m["fields"]],
                        ["Menor patrimônio listado (US$)", num(m["min_account_value"])],
                        [
                            "Linhas com patrimônio ≥ US$ 30.000 (F2)",
                            f"{m['n_account_value_ge_30000']:,}",
                        ],
                        [
                            "`windowPerformances` presente em",
                            f"{m['rows_with_window_performances']:,} linhas",
                        ],
                        ["Janelas em `windowPerformances` (só nomes)", m["window_names"]],
                        [
                            "Campos por janela (só nomes; valores não foram guardados)",
                            m["window_fields"],
                        ],
                        [
                            "Endereços inválidos / duplicados",
                            f"{m['invalid_addresses']} / {m['duplicate_addresses']}",
                        ],
                    ],
                )
                + "\n"
            )

        m = crit["RF-VER-01 CA-01.4"]["measured"]
        if m and "counts" in m:
            c = m["counts"]
            w("### CA-01.4 — `closedPnl` bruto ou líquido\n")
            w(
                "Só contagens de episódios; nenhum valor de PnL é impresso ou gravado. Tolerância relativa 1e-6 "
                "(com piso absoluto de 1e-6 USD, escolha deste script). Hipóteses sobre a soma de `closedPnl` do "
                "episódio: `gross` = igual ao PnL reconstruído de preços e tamanhos por custo médio; `net_all` = "
                "reconstruído menos todas as taxas do episódio; `net_close` = menos só as taxas dos fills que reduzem posição "
                "(a terceira é um acréscimo deste script à comparação binária da spec).\n"
            )
            w(table(["Contagem", "Valor"], [[k, v] for k, v in sorted(c.items())]) + "\n")
            w(f"Leitura: **{m['conciliation']}** — {m['detail']}.\n")
            w(ladder_tables(m["ladder"], m["per_fill"]))
            w(
                size_and_break_tables(
                    v01["closed_pnl_by_size"],
                    v01["break_diagnostics"],
                    v01["continuity"]["pairs_broken"],
                )
            )
        agg = v01["aggregate_by_time"]
        w("### `aggregateByTime` falso e verdadeiro (janela de seleção)\n")
        w(
            table(
                ["Carteira", "Falso", "Verdadeiro"],
                [[f"`{r['address']}`", r["false"], r["true"]] for r in agg["per_wallet"]]
                + [["**Total**", f"**{agg['total_false']}**", f"**{agg['total_true']}**"]],
            )
            + "\n"
        )
        ct = v01["continuity"]
        w("### Quebra de continuidade de posição (RF-ING-03 CA-03.1), amostra de RF-VER-01\n")
        w(
            table(
                ["Medida", "Valor"],
                [
                    ["Carteiras com fills de perpétuo do `meta`", ct["wallets_with_perp_fills"]],
                    ["Séries (carteira, ativo)", ct["series"]],
                    ["Pares consecutivos conferidos", f"{ct['pairs_checked']:,}"],
                    [
                        "Pares com quebra",
                        f"{ct['pairs_broken']:,} ({pct(ct['pair_break_rate'], 3)})",
                    ],
                    ["… dos quais entre fills do mesmo milissegundo", ct["pairs_broken_same_ms"]],
                    ["Séries com ao menos uma quebra", ct["series_with_break"]],
                    ["Carteiras com ao menos uma quebra", ct["wallets_with_break"]],
                ],
            )
            + "\n"
        )
    if v02:
        ec = v02["extended_sample_continuity"]
        w("### Complemento: mesma medição na amostra maior de RF-VER-02 (não é da spec)\n")
        w(
            table(
                ["Medida", "Valor"],
                [
                    ["Carteiras com fills de perpétuo do `meta`", ec["wallets_with_perp_fills"]],
                    ["Séries (carteira, ativo)", ec["series"]],
                    ["Pares consecutivos conferidos", f"{ec['pairs_checked']:,}"],
                    [
                        "Pares com quebra",
                        f"{ec['pairs_broken']:,} ({pct(ec['pair_break_rate'], 3)})",
                    ],
                    ["… dos quais entre fills do mesmo milissegundo", ec["pairs_broken_same_ms"]],
                    ["Séries com ao menos uma quebra", ec["series_with_break"]],
                    ["Carteiras com ao menos uma quebra", ec["wallets_with_break"]],
                ],
            )
            + "\n"
        )
        ex = v02["extended_sample_closed_pnl"]
        w(f"`closedPnl` na amostra maior: **{ex['verdict']}** — {ex['detail']}.\n")
        w(table(["Contagem", "Valor"], [[k, v] for k, v in sorted(ex["counts"].items())]) + "\n")
        w(
            ladder_tables(
                v02["extended_sample_closed_pnl_ladder"], v02["extended_sample_closed_pnl_per_fill"]
            )
        )
        w(
            size_and_break_tables(
                v02["extended_sample_closed_pnl_by_size"],
                v02["extended_sample_break_diagnostics"],
                v02["extended_sample_continuity"]["pairs_broken"],
            )
        )
    if v04 and v04.get("trades_users", {}).get("available"):
        u = v04["trades_users"]
        w("### CA-01.5 — fluxo público de negócios\n")
        w(
            table(
                ["Medida", "Valor"],
                [
                    [
                        "Ativo e janela de gravação conferida",
                        f"{u['coin']}, {u['covered_seconds'] / 60:.1f} min",
                    ],
                    ["Negócios", f"{u['trades']:,}"],
                    [
                        "Com os endereços das duas pontas",
                        f"{u['with_both_addresses']:,} ({pct(u['fraction'], 3)})",
                    ],
                    ["Endereços distintos", f"{u['distinct_addresses']:,}"],
                    ["Comprador e vendedor com o mesmo endereço", u["same_address_both_sides"]],
                    ["Campos de cada negócio", u["trade_keys"]],
                ],
            )
            + "\n"
        )

    # ─── RF-VER-02 ────────────────────────────────────────────────────────────
    w("## RF-VER-02 — cobertura do universo\n")
    w(
        table(
            ["Critério", "Regra da spec", "Medido", "Status"],
            [
                [
                    f"`{c.split()[1]}`",
                    crit[c]["rule"],
                    short(c, crit[c]),
                    f"**{crit[c]['status']}**",
                ]
                for c in CRITERIA[5:7]
            ],
        )
        + "\n"
    )
    if v02:
        s = v02["sampling"]
        w(
            f'Amostra: {len(s["chosen"])} carteiras que passam em F1 (`userRole == "user"`) e F2 (patrimônio ≥ '
            f"US$ 30.000), de um pool F2 de {s['pool_size_f2']:,}. Foram consultadas {s['userrole_checked']:,} para "
            f"achar {len(s['chosen'])}: papéis encontrados {s['roles_among_checked']}. Só fills da janela de seleção. "
            f"Falhas de coleta: {len(v02['failures'])}.\n"
        )
        m = crit["RF-VER-02 CA-02.1"]["measured"]
        if m and "top_assets" in m:
            w("### CA-02.1 — notional negociado por ativo\n")
            w(
                'Volume `px x sz` somado nos fills da janela. "Todos": denominador com spot e HIP-3 '
                'inclusos. "Perpétuos": só perpétuos do primeiro dex.\n'
            )
            w(
                table(
                    ["Ativo", "Tipo", "Fração (todos)", "Fração (perpétuos)", "No universo"],
                    [
                        [
                            f"`{a['coin']}`",
                            a["kind"],
                            pct(a["share_all"], 2),
                            pct(a["share_perps"], 2),
                            "sim" if a["in_universe"] else "",
                        ]
                        for a in m["top_assets"]
                    ],
                )
                + "\n"
            )
            w(
                f"**Acumulado no universo (BTC, ETH, SOL): {pct(m['universe_cumulative_all_fills'], 2)} (todos os fills) "
                f"e {pct(m['universe_cumulative_perps_only'], 2)} (só perpétuos).**\n"
            )
            w(
                "Notional por tipo de ativo: "
                + ", ".join(f"{k} {pct(v, 1)}" for k, v in m["notional_by_kind"].items())
                + ".\n"
            )
            p = m["per_wallet_universe_share"]
            w(
                f"Fração do notional de cada carteira que cai no universo (o que F9 mede): n = {p['n']}, "
                f"p25 {pct(p['p25'])}, mediana {pct(p['median'])}, p75 {pct(p['p75'])}; "
                f"{p['ge_50pct']} carteiras com ≥ 50%.\n"
            )
        m = crit["RF-VER-02 CA-02.2"]["measured"]
        if m and "d7" in m:
            d7 = m["d7"]
            w("### CA-02.2 — regra D7\n")
            if not d7["applied"]:
                w(
                    "Cobertura ≥ 50% nas duas bases de cálculo: a regra D7 não é acionada e nada é listado.\n"
                )
            else:
                w(
                    f"Existência do perpétuo na Binance conferida no arquivo público do dia {d7['binance_check_day']} "
                    f"para os {d7['candidates_checked']} maiores perpétuos fora do universo. Nada foi acrescentado: só a lista "
                    "que a regra D7 produziria.\n"
                )
                for label, key in (("todos os fills", "all_fills"), ("só perpétuos", "perps_only")):
                    items = d7[key]
                    if not items:
                        w(f"- Base **{label}**: cobertura já ≥ 50%, nada a acrescentar.")
                        continue
                    w(
                        f"- Base **{label}**, em ordem: "
                        + ", ".join(
                            f"{i + 1}. `{x['coin']}` ({pct(x['share'], 2)}; acumulado {pct(x['cumulative_after'], 1)})"
                            for i, x in enumerate(items)
                        )
                    )
                w("")
                w(
                    f"Sem equivalente verificado na Binance (pulados pela regra): {d7['no_equivalent'] or 'nenhum'}.\n"
                )
        h = v02["history"]
        w("### Retenção nesta amostra (informativo)\n")
        w(
            f"Fills na janela: {h['in_window_fills_total']:,}. O histórico começa antes da janela em "
            f"{pct(h['reaches_window_start'])} das carteiras ({h['history_starts']}); mais de 10.000 "
            f"fills devolvidos em {h['exceeds_documented_cap']} de {h['n_wallets']}; exatamente 10.000 em "
            f"{h['at_documented_cap']}; maior total contado {h['max_total_counted']:,}; sem fill na "
            f"janela: {h['no_fills_in_window']}.\n"
        )

    # ─── RF-VER-03 ────────────────────────────────────────────────────────────
    w("## RF-VER-03 — validade do preço proxy\n")
    w(
        table(
            ["Critério", "Regra da spec", "Medido", "Status"],
            [
                [
                    f"`{c.split()[1]}`",
                    crit[c]["rule"],
                    short(c, crit[c]),
                    f"**{crit[c]['status']}**",
                ]
                for c in CRITERIA[7:9]
            ],
        )
        + "\n"
    )
    if v03:
        w(
            f"Dias sorteados da janela (semente `{SEED}`): {', '.join(v03['days'])}. Fills de líderes: os da amostra de "
            "RF-VER-02, nesses dias. Proxy do segundo = último negócio do segundo (`last`); `mid` é sensibilidade.\n"
        )
        w(
            table(
                ["Arquivo", "Zip", "CSV", "Negócios", "Segundos com negócio", "Checksum"],
                [
                    [
                        f"`{f['symbol']}` {f['day']}",
                        size(f["zip_bytes"]),
                        size(f["csv_bytes"]),
                        f"{f['trades']:,}",
                        f"{f['seconds_with_trade']:,}",
                        "confere" if f["checksum_ok"] else "**DIVERGE**",
                    ]
                    for f in v03["proxy_files"]
                ],
            )
            + "\n"
        )
        for coin, v in v03.get("per_coin", {}).items():
            w(f"### {coin}\n")
            rows = []
            for d in v["days"]:
                last = d.get("last")
                mid = d.get("mid")
                rows.append(
                    [
                        d["day"],
                        d["fills"],
                        d["no_proxy_second"],
                        num(last["median"]) if last else "—",
                        num(last["p95_abs"]) if last else "—",
                        num(last["p95_abs_dev_from_day_median"]) if last else "—",
                        num(mid["p95_abs_dev_from_day_median"]) if mid else "—",
                    ]
                )
            w(
                table(
                    [
                        "Dia",
                        "Fills",
                        "Sem proxy no segundo",
                        "Mediana (bps)",
                        "p95 abs(dif) (bps)",
                        "p95 abs(dif - mediana do dia) (bps)",
                        "idem, base `mid`",
                    ],
                    rows,
                )
                + "\n"
            )
            w(
                f"Total {coin}: {v['fills']:,} fills ({v['matched']:,} com proxy no segundo). "
                f"p95 do desvio em relação à mediana do dia, agregando os dias: "
                f"{num(v['pooled_p95_abs_dev_last'])} bps (`last`), {num(v['pooled_p95_abs_dev_mid'])} bps (`mid`). "
                f"Dias acima de 10 bps: {v['days_over_threshold_last'] or 'nenhum'}.\n"
            )

    if v03 and v03.get("window_fills_in_sample"):
        t = v03["window_fills_in_sample"]
        w(
            "Para dimensionar o déficit de CA-03.1: nos 62 dias da janela inteira, a mesma amostra de "
            "carteiras tem "
            + ", ".join(f"{c} {n:,}" for c, n in t.items())
            + " fills (contra os 10.000 por ativo que o critério pede).\n"
        )

    # ─── RF-VER-04 ────────────────────────────────────────────────────────────
    w("## RF-VER-04 — orçamento de dados\n")
    w(
        table(
            ["Critério", "Regra da spec", "Medido", "Status"],
            [
                [
                    f"`{c.split()[1]}`",
                    crit[c]["rule"],
                    short(c, crit[c]),
                    f"**{crit[c]['status']}**",
                ]
                for c in CRITERIA[9:]
            ],
        )
        + "\n"
    )
    if v04 and v04.get("recording"):
        rec = v04["recording"]
        w(
            f"Gravação: início {rec['started']}, duração {rec['duration_s'] / 60:.1f} min, eventos {rec['events']}. "
            "Formato: mensagem JSON bruta + instante de recebimento, um arquivo por (ativo, canal).\n"
        )
        rows = []
        for coin, per in rec["files"].items():
            for channel, f in per.items():
                lat = f["latency_ms"] or {}
                srv = f["server_interval_s"] or {}
                rows.append(
                    [
                        coin,
                        channel,
                        f"{f['messages']:,}",
                        f"{f['items']:,}",
                        size(f["bytes"]),
                        size(f["gzip_bytes"]),
                        f"{f['messages'] / rec['duration_s']:.2f}" if rec["duration_s"] else "—",
                        num(srv.get("p50"), 3),
                        num(srv.get("p95"), 3),
                        f"{lat.get('p50', float('nan')):.0f} / {lat.get('p95', float('nan')):.0f} / {lat.get('p99', float('nan')):.0f}",
                    ]
                )
        w(
            table(
                [
                    "Ativo",
                    "Canal",
                    "Mensagens",
                    "Itens",
                    "Bytes",
                    "gzip",
                    "Msg/s",
                    "Intervalo entre atualizações da corretora p50 (s)",
                    "p95 (s)",
                    "recebimento - corretora p50 / p95 / p99 (ms)",
                ],
                rows,
            )
            + "\n"
        )
        snaps = [
            f"{c}/{ch}: {f['snapshot_items']} itens, até {f['snapshot_max_age_s']:.0f} s de idade"
            for c, per in rec["files"].items()
            for ch, f in per.items()
            if ch == "trades" and f["snapshot_messages"]
        ]
        w(
            "A primeira mensagem de cada assinatura é um snapshot e fica fora das colunas de "
            "intervalo e de atraso (os bytes contam tudo). Snapshot de `trades`: "
            + ("; ".join(snaps) or "nenhum")
            + ".\n"
        )
        w(
            "A diferença recebimento - corretora mistura latência de rede com diferença entre os relógios das duas "
            "máquinas; fração negativa por canal: "
            + ", ".join(
                f"{c}/{ch} {pct(f['latency_ms']['negative_fraction'], 1)}"
                for c, per in rec["files"].items()
                for ch, f in per.items()
                if f["latency_ms"]
            )
            + ".\n"
        )
        ext = v04["collector_extrapolation"]
        w("### CA-04.1 — extrapolação para 45 dias\n")
        rows = []
        for coin, variants in ext["per_coin"].items():
            for variant, x in variants.items():
                rows.append(
                    [
                        coin,
                        variant,
                        size(x["measured_bytes"]),
                        size(x["bytes_45d"]),
                        size(x["gzip_bytes_45d"]),
                    ]
                )
        for variant, x in ext["total"].items():
            rows.append(
                [
                    "**Total**",
                    variant,
                    size(x["measured_bytes"]),
                    size(x["bytes_45d"]),
                    size(x["gzip_bytes_45d"]),
                ]
            )
        w(
            table(
                [
                    "Ativo",
                    "Variante",
                    f"Medido em {ext['hours_measured']:.2f} h",
                    "45 dias (bruto)",
                    "45 dias (gzip)",
                ],
                rows,
            )
            + "\n"
        )
        w(
            "Extrapolação linear a partir de uma única janela de gravação: não captura variação ao longo do dia nem "
            "de regime de mercado.\n"
        )
    if v04 and v04.get("proxy_extrapolation") and v04["proxy_extrapolation"]["per_coin"]:
        p = v04["proxy_extrapolation"]
        w("### CA-04.2 — preço proxy\n")
        w(
            table(
                [
                    "Ativo",
                    "Dias medidos",
                    "Zip médio/dia",
                    "CSV médio/dia",
                    "Série por segundo média/dia",
                    f"Zips, {v04['criteria']['RF-VER-04 CA-04.2']['measured']['days_assumed_route_a']} dias (Rota A)",
                    f"Zips, {v04['criteria']['RF-VER-04 CA-04.2']['measured']['days_assumed_all_windows']} dias (todas as janelas)",
                ],
                [
                    [
                        c,
                        x["days_measured"],
                        size(x["zip_mean_bytes"]),
                        size(x["csv_mean_bytes"]),
                        size(x["series_mean_bytes"]),
                        size(x["zip_route_a"]),
                        size(x["zip_all"]),
                    ]
                    for c, x in p["per_coin"].items()
                ]
                + [
                    [
                        "**Total**",
                        "",
                        "",
                        "",
                        "",
                        size(p["total"]["zip_route_a"]),
                        size(p["total"]["zip_all"]),
                    ]
                ],
            )
            + "\n"
        )
    m = crit["RF-VER-04 CA-04.3"]["measured"]
    if m and "individual" in m:
        w("### CA-04.3 — contra o orçamento de RNF-10\n")
        w(
            table(
                ["Extrapolação", "GB", "Excede 30 GB"],
                [
                    [r["item"], f"{r['gb']:.2f}", "**sim**" if r["exceeds_30gb"] else "não"]
                    for r in m["individual"] + m["sums"]
                ],
            )
            + "\n"
        )
        w(
            f"Orçamento de disco da fase inteira: {m['budget_gb']:.0f} GB. A regra da spec é por extrapolação "
            "individual; as somas são informativas.\n"
        )

    # ─── Seções narrativas ────────────────────────────────────────────────────
    w("## O que contradiz a spec\n")
    w("<!-- NARRATIVA: preenchida à mão depois da leitura dos resultados -->\n")
    w("## O que não foi possível medir\n")
    w("<!-- NARRATIVA: preenchida à mão depois da leitura dos resultados -->\n")

    target = ctx.root / "report.md" if ctx.smoke else REPO_ROOT / "docs" / "verificacao-de-dados.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out), encoding="utf-8")
    return target
