"""RF-VER-01 — esquema e retenção da API (CA-01.1 a CA-01.5).

Mede formato, cobertura e consistência. **Não calcula, não imprime e não grava
desempenho de carteira.** A única conta de PnL é a de CA-01.4, e dela só saem
contagens (`analysis.concordance`).

Uso: `python scripts/verify/v01_schema.py [--smoke]`
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analysis import (
    SPEC_FIELDS,
    build_episodes,
    classify_coin,
    concordance,
    concordance_by_size,
    continuity_breaks,
    continuity_pairs,
    field_coverage,
    fill_level_concordance,
    percentile,
    unexpected_fields,
)
from common import (
    CUTOFF_MS,
    SEED,
    WINDOW_START_MS,
    Ctx,
    HlClient,
    Progress,
    RateBudget,
    fetch_wallet,
    fetch_wallet_aggregated,
    iso,
    load_leaderboard,
    load_meta,
    make_ctx,
    setup_logging,
    write_json,
)

STEP = "RF-VER-01"
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")

#: Leitura dos resultados de CA-01.4 (critério deste script, não da spec): uma hipótese
#: "concilia" se explica pelo menos esta fração dos episódios testados.
#: Uma hipótese "descreve" `closedPnl` se vence a segunda colocada por tanto (pontos percentuais).
SEPARATION_MARGIN = 0.5
DECISION_TOLERANCE = "0.001"
MIN_EPISODES_TO_DECIDE = 5
#: Tolerâncias relativas e absolutas (diagnóstico de CA-01.4); a da spec é a primeira (1e-6).
TOLERANCE_LADDER = (1e-6, 1e-4, 1e-3, 1e-2)
_HEAVY_KEYS = (
    "closed_pnl",
    "closed_pnl_ladder",
    "closed_pnl_per_fill",
    "closed_pnl_by_size",
    "break_diagnostics",
)


def criterion(status: str, measured: Any, rule: str, note: str = "") -> dict[str, Any]:
    return {"status": status, "measured": measured, "rule": rule, "note": note}


def wallet_summary(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": rec["address"],
        "in_window": rec["in_window_count"],
        "pre_window": rec["pre_window_count"],
        "post_window": rec["post_window_count"],
        "lower_bound": rec["counts_are_lower_bounds"],
        "total": rec["total_counted"],
        "oldest": iso(rec["oldest_ms"]),
        "history_starts": rec["history_starts"],
        "exceeds_cap": rec["exceeds_documented_cap"],
        "at_cap": rec["at_documented_cap"],
        "pages": rec["pages"],
        "weight": rec["weight"],
    }


def retention_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Resumo de retenção de uma amostra (RF-VER-01 CA-01.2)."""
    n = len(records)
    starts = Counter(r["history_starts"] for r in records)
    return {
        "n_wallets": n,
        "history_starts": dict(starts),
        "reaches_window_start": starts["antes da janela"] / n if n else None,
        "exceeds_documented_cap": sum(r["exceeds_documented_cap"] for r in records),
        "at_documented_cap": sum(r["at_documented_cap"] for r in records),
        "no_fills_in_window": sum(r["in_window_count"] == 0 for r in records),
        "max_total_counted": max((r["total_counted"] for r in records), default=0),
    }


def split_by_kind(
    fills: Sequence[dict[str, Any]], perp_names: frozenset[str]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        out[classify_coin(str(fill.get("coin")), perp_names)].append(fill)
    return out


def continuity_and_episodes(
    records: Sequence[dict[str, Any]], meta: dict[str, Any]
) -> dict[str, Any]:
    """Continuidade de posição (RF-ING-03 CA-03.1) e concordância de `closedPnl`.

    Só perpétuos do primeiro dex presentes no `meta` (precisam de `szDecimals` para o
    lote). Devolve contagens e taxas; nenhum valor de PnL.
    """
    assets = meta["assets"]
    perp_names = frozenset(assets)
    pairs: Counter[str] = Counter()
    conc: Counter[str] = Counter()
    ladder: dict[str, Counter[str]] = {f"{t:g}": Counter() for t in TOLERANCE_LADDER}
    per_fill: Counter[str] = Counter()
    by_size: Counter[str] = Counter()
    break_dir: Counter[str] = Counter()
    break_jump: Counter[str] = Counter()
    break_liq = 0
    break_gaps: list[float] = []
    n_series = n_series_broken = n_wallets = n_wallets_broken = 0
    for rec in records:
        by_coin: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fill in rec["fills"]:
            if classify_coin(str(fill.get("coin")), perp_names) == "perp":
                by_coin[fill["coin"]].append(fill)
        if not by_coin:
            continue
        n_wallets += 1
        wallet_broken = False
        for coin, fills in by_coin.items():
            lot = 10 ** -int(assets[coin]["szDecimals"])
            result = continuity_pairs(fills, lot)
            pairs.update(result)
            n_series += 1
            if result["breaks"]:
                n_series_broken += 1
                wallet_broken = True
            episodes = build_episodes(fills, lot)
            conc.update(concordance(episodes))
            for tol in TOLERANCE_LADDER:
                ladder[f"{tol:g}"].update(concordance(episodes, rel_tol=tol, abs_tol=tol))
            per_fill.update(fill_level_concordance(episodes))
            by_size.update(concordance_by_size(episodes))
            diag = continuity_breaks(fills, lot)
            break_dir.update(diag["prev_dir"])
            break_jump.update(diag["jump"])
            break_liq += diag["with_liquidation_field"]
            break_gaps.extend(diag["gaps_s"])
        n_wallets_broken += wallet_broken
    checked = pairs["pairs"]
    return {
        "pairs_checked": checked,
        "pairs_broken": pairs["breaks"],
        "pairs_broken_same_ms": pairs["breaks_same_ms"],
        "pair_break_rate": pairs["breaks"] / checked if checked else None,
        "series": n_series,
        "series_with_break": n_series_broken,
        "wallets_with_perp_fills": n_wallets,
        "wallets_with_break": n_wallets_broken,
        "closed_pnl": dict(conc),
        "closed_pnl_ladder": {k: dict(v) for k, v in ladder.items()},
        "closed_pnl_per_fill": dict(per_fill),
        "closed_pnl_by_size": dict(by_size),
        "break_diagnostics": {
            "prev_dir": dict(break_dir),
            "jump": dict(break_jump),
            "with_liquidation_field": break_liq,
            "gap_s_p50": percentile(break_gaps, 50) if break_gaps else None,
            "gap_s_max": max(break_gaps) if break_gaps else None,
            "gap_s_under_1": sum(g < 1 for g in break_gaps),
        },
    }


def read_conciliation(ladder: dict[str, dict[str, int]], strict: dict[str, int]) -> tuple[str, str]:
    """Traduz as contagens de `concordance` em `(veredito, explicação)`.

    A pergunta de CA-01.4 é *qual hipótese* (bruto ou líquido) descreve `closedPnl`; ela é
    decidida na tolerância `DECISION_TOLERANCE`, porque a de 1e-6 da spec pode ser mais
    estreita que o arredondamento da própria API. As duas taxas aparecem no texto.
    """
    loose = ladder[DECISION_TOLERANCE]
    tested = loose.get("tested", 0)
    if tested == 0:
        return "não medido", "nenhum episódio fechado de zero a zero na amostra"
    matters = loose.get("fee_matters", 0)
    suffix = "_when_fee_matters" if matters >= MIN_EPISODES_TO_DECIDE else ""
    denom = matters if suffix else tested
    rates = {
        name: loose.get(f"{name}{suffix}", 0) / denom for name in ("gross", "net_all", "net_close")
    }
    ordered = sorted(rates, key=lambda name: rates[name], reverse=True)
    best, runner_up = ordered[0], ordered[1]
    scope = f"{denom} episódios em que a taxa importa" if suffix else f"{denom} episódios"
    text = (
        ", ".join(f"{name} {rate:.1%}" for name, rate in rates.items())
        + f" (tolerância {DECISION_TOLERANCE}; {scope})"
    )
    strict_tested = strict.get("tested", 0)
    if strict_tested:
        strict_rate = strict.get(best, 0) / strict_tested
        text += f"; na tolerância da spec (1e-6), {best} concilia {strict_rate:.1%}"
    if not suffix:
        return "não medido", f"poucos episódios em que a taxa distingue as hipóteses; {text}"
    if rates[best] - rates[runner_up] >= SEPARATION_MARGIN:
        return f"ok:{best}", text
    return "a emendar", f"as hipóteses não se separam; {text}"


def trades_users_check(ws_dir: Path, coin: str = "BTC", minutes: float = 10.0) -> dict[str, Any]:
    """RF-VER-01 CA-01.5: cada negócio do fluxo público traz os endereços das duas pontas?

    Lê o arquivo de `trades` gravado por `record.py` e confere os primeiros `minutes`
    minutos de gravação.
    """
    path = ws_dir / f"{coin}.trades.tsv"
    if not path.exists():
        return {"available": False}
    first_recv: int | None = None
    trades = both = 0
    same_address = 0
    distinct: set[str] = set()
    keys: Counter[str] = Counter()
    last_recv = 0
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if index == 0:
            continue  # snapshot da assinatura: negócios antigos, não é fluxo ao vivo
        recv_text, _, raw = line.partition("\t")
        recv = int(recv_text)
        first_recv = recv if first_recv is None else first_recv
        if recv - first_recv > minutes * 60_000:
            break
        last_recv = recv
        for trade in json.loads(raw)["data"]:
            trades += 1
            keys.update(trade.keys())
            users = trade.get("users")
            ok = (
                isinstance(users, list)
                and len(users) == 2
                and all(isinstance(u, str) and _ADDRESS.match(u) for u in users)
            )
            both += ok
            if ok:
                distinct.update(users)
                same_address += users[0].lower() == users[1].lower()
    covered_s = (last_recv - first_recv) / 1000 if first_recv is not None else 0.0
    return {
        "available": True,
        "coin": coin,
        "covered_seconds": covered_s,
        "trades": trades,
        "with_both_addresses": both,
        "fraction": both / trades if trades else None,
        "distinct_addresses": len(distinct),
        "same_address_both_sides": same_address,
        "trade_keys": dict(keys),
    }


def run(ctx: Ctx, client: HlClient) -> dict[str, Any]:
    log = setup_logging()
    board = load_leaderboard(ctx)
    meta = load_meta(ctx, client)
    perp_names = frozenset(meta["assets"])

    addresses = sorted(row["ethAddress"] for row in board["rows"])
    sample = random.Random(SEED).sample(addresses, ctx.n_v01)
    log.info("amostra RF-VER-01", n=len(sample), seed=SEED)

    records: list[dict[str, Any]] = []
    aggregated: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    progress = Progress(ctx, f"{STEP} fills", len(sample))
    for address in sample:
        try:
            records.append(fetch_wallet(ctx, client, address))
            aggregated.append(fetch_wallet_aggregated(ctx, client, address))
        except Exception as exc:  # RF-ING-07 CA-07.2: segue com as demais e reporta no fim
            failures.append({"address": address, "error": f"{type(exc).__name__}: {exc}"})
            log.error("carteira falhou", address=address, error=str(exc))
        progress.tick(address[:10], weight=int(client.budget.total_weight))

    all_fills = [fill for rec in records for fill in rec["fills"]]
    by_kind = split_by_kind(all_fills, perp_names)

    # CA-01.1
    coverage = field_coverage(all_fills)
    total = coverage["total"]
    per_kind = {kind: field_coverage(fills) for kind, fills in by_kind.items()}
    failing = (
        [name for name in SPEC_FIELDS if coverage["fields"][name]["ok"] != total] if total else []
    )
    if total == 0:
        c011 = criterion("não medido", {"fills": 0}, "100% presente e interpretável", "sem fills")
    else:
        c011 = criterion(
            "ok" if not failing else "reprova",
            {
                "fills": total,
                "fields": {
                    name: {
                        "present": coverage["fields"][name]["present"] / total,
                        "ok": coverage["fields"][name]["ok"] / total,
                    }
                    for name in SPEC_FIELDS
                },
                "per_kind": {
                    kind: {
                        "fills": cov["total"],
                        "min_ok": min(cov["fields"][n]["ok"] for n in SPEC_FIELDS) / cov["total"],
                    }
                    for kind, cov in per_kind.items()
                },
                "failing_fields": failing,
            },
            "cada campo presente e interpretável em 100% dos fills",
        )

    # CA-01.2
    retention = retention_summary(records)
    c012 = criterion(
        "ok" if records else "não medido",
        {"wallets": [wallet_summary(r) for r in records], **retention},
        "informar, por carteira, o fill mais antigo, se o teto de 10.000 foi atingido e a "
        "fração que alcança o início da janela",
    )

    # CA-01.3
    c013 = criterion(
        "ok",
        {
            "rows": board["n_rows"],
            "fields": board["row_key_counts"],
            "min_account_value": board["min_account_value"],
            "rows_with_window_performances": board["rows_with_window_performances"],
            "window_names": board["window_names"],
            "window_fields": board["window_fields"],
            "n_account_value_ge_30000": board["n_account_value_ge_30000"],
            "invalid_addresses": board["n_invalid_addresses"],
            "duplicate_addresses": board["n_duplicate_addresses"],
        },
        "informar linhas, campos presentes e o menor patrimônio listado",
    )

    # CA-01.4 (amostra da spec)
    cont = continuity_and_episodes(records, meta)
    verdict, why = read_conciliation(cont["closed_pnl_ladder"], cont["closed_pnl"])
    if verdict.startswith("ok:"):
        status, summary = "ok", f"closedPnl concilia com a hipótese {verdict[3:]}"
    else:
        status, summary = verdict, "sem veredito"
    c014 = criterion(
        status,
        {
            "conciliation": summary,
            "detail": why,
            "counts": cont["closed_pnl"],
            "ladder": cont["closed_pnl_ladder"],
            "per_fill": cont["closed_pnl_per_fill"],
        },
        "informar se closedPnl é bruto ou líquido de fee, testando as duas hipóteses",
    )

    agg_by_addr = {a["address"]: a["in_window_count"] for a in aggregated}
    agg_rows = [
        {
            "address": r["address"],
            "false": r["in_window_count"],
            "true": agg_by_addr.get(r["address"]),
        }
        for r in records
    ]
    n_false = sum(r["false"] for r in agg_rows)
    n_true = sum(r["true"] for r in agg_rows if r["true"] is not None)

    result: dict[str, Any] = {
        "step": STEP,
        "sample": sample,
        "failures": failures,
        "criteria": {
            "RF-VER-01 CA-01.1": c011,
            "RF-VER-01 CA-01.2": c012,
            "RF-VER-01 CA-01.3": c013,
            "RF-VER-01 CA-01.4": c014,
        },
        "aggregate_by_time": {"per_wallet": agg_rows, "total_false": n_false, "total_true": n_true},
        "continuity": {k: v for k, v in cont.items() if k not in _HEAVY_KEYS},
        "closed_pnl_ladder": cont["closed_pnl_ladder"],
        "closed_pnl_per_fill": cont["closed_pnl_per_fill"],
        "closed_pnl_by_size": cont["closed_pnl_by_size"],
        "break_diagnostics": cont["break_diagnostics"],
        "unexpected_fields": dict(unexpected_fields(all_fills)),
        "fills_sharing_a_tid_within_wallet": sum(
            len(r["fills"]) - len({f.get("tid") for f in r["fills"]}) for r in records
        ),
        "coin_kinds": {kind: len(fills) for kind, fills in by_kind.items()},
        "dir_values": dict(Counter(str(f.get("dir")) for f in all_fills)),
        "window": {"start": iso(WINDOW_START_MS), "cutoff": iso(CUTOFF_MS)},
        "client_stats": dict(client.stats),
        "budget": {
            "limit": client.budget.limit,
            "peak": client.budget.peak,
            "total_weight": client.budget.total_weight,
            "waited_s": client.budget.waited_s,
        },
    }
    write_json(ctx.path("results", "v01.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    ctx = make_ctx(args.smoke)
    client = HlClient(RateBudget())
    run(ctx, client)


if __name__ == "__main__":
    main()
