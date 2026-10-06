"""RF-VER-02 — cobertura do universo (CA-02.1 e CA-02.2).

Amostra semeada de carteiras que passam em F1 (`userRole == "user"`) e F2 (patrimônio
do snapshot >= US$ 30.000), só com fills da janela de seleção. Mede **volume negociado**
por ativo (`px * sz`), nunca desempenho: nenhuma carteira é ranqueada, nenhum PnL é
calculado. A mesma amostra serve a RF-VER-03 (fills de líderes) e, como medida
complementar, a CA-01.4 e à continuidade (amostra maior).

Duas bases de cálculo, porque a spec não diz qual é o denominador de "notional negociado":
**todos os fills** (spot e HIP-3 inclusos, como F9 mede "notional da carteira") e **só
perpétuos** do primeiro dex. As duas são reportadas; nenhuma é escolhida pelo script.

Uso: `python scripts/verify/v02_universe.py [--smoke]`
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from typing import Any

import httpx

from analysis import classify_coin, d7_additions, is_perp, notional_by_coin, percentile
from common import (
    BINANCE_BASE,
    SEED,
    UNIVERSE,
    USER_AGENT,
    WINDOW_START_MS,
    Ctx,
    HlClient,
    Progress,
    RateBudget,
    fetch_wallet,
    iso,
    load_leaderboard,
    load_meta,
    make_ctx,
    read_json,
    sample_days,
    setup_logging,
    write_json,
)
from v01_schema import (
    _HEAVY_KEYS,
    continuity_and_episodes,
    criterion,
    read_conciliation,
    retention_summary,
    wallet_summary,
)

STEP = "RF-VER-02"
F2_MIN_ACCOUNT_VALUE = 30_000.0  # §7.3, F2
COVERAGE_TARGET = 0.5  # RF-VER-02 CA-02.2
D7_MAX_ASSETS = 8


def binance_symbol_candidates(coin: str) -> list[str]:
    """Símbolos USD-M plausíveis para um ativo da Hyperliquid.

    `kPEPE` na Hyperliquid é `1000PEPEUSDT` na Binance. A existência é conferida contra o
    arquivo público de um dia da janela; não se supõe nada.
    """
    candidates = [f"{coin}USDT"]
    if coin.startswith("k") and len(coin) > 1:
        candidates.append(f"1000{coin[1:]}USDT")
    return candidates


def binance_has_equivalent(http: httpx.Client, coin: str, day: str) -> tuple[bool, str | None]:
    for symbol in binance_symbol_candidates(coin):
        url = f"{BINANCE_BASE}/{symbol}/{symbol}-aggTrades-{day}.zip"
        try:
            resp = http.head(url)
        except httpx.TransportError:
            continue
        if resp.status_code == 200:
            return True, symbol
    return False, None


def pick_wallets(ctx: Ctx, client: HlClient, board: dict[str, Any]) -> dict[str, Any]:
    """Carteiras que passam em F1 e F2, em ordem sorteada com a semente fixa.

    O pool é ordenado por endereço *antes* de sortear, para que a ordem do leaderboard
    (que pode embutir ranking) não influencie a amostra.
    """
    pool = sorted(
        r["ethAddress"] for r in board["rows"] if r["accountValue"] >= F2_MIN_ACCOUNT_VALUE
    )
    random.Random(SEED).shuffle(pool)
    chosen: list[str] = []
    roles: Counter[str] = Counter()
    checked = 0
    progress = Progress(ctx, f"{STEP} userRole", ctx.n_v02)
    for address in pool:
        if len(chosen) >= ctx.n_v02:
            break
        cache = ctx.path("roles", f"{address}.json")
        if cache.exists():
            payload = read_json(cache)
        else:
            payload = client.user_role(address)
            write_json(cache, payload)
        checked += 1
        role = str(payload.get("role")) if isinstance(payload, dict) else "formato inesperado"
        roles[role] += 1
        if role == "user":
            chosen.append(address)
            progress.tick(f"{len(chosen)}/{ctx.n_v02} (checadas {checked})")
    return {
        "pool_size": len(pool),
        "checked": checked,
        "roles": dict(roles),
        "chosen": chosen,
    }


def shares(totals: dict[str, float], denominator: float) -> dict[str, float]:
    return {coin: value / denominator for coin, value in totals.items()} if denominator else {}


def run(ctx: Ctx, client: HlClient) -> dict[str, Any]:
    log = setup_logging()
    board = load_leaderboard(ctx)
    meta = load_meta(ctx, client)
    perp_names = frozenset(meta["assets"])

    picked = pick_wallets(ctx, client, board)
    chosen: list[str] = picked["chosen"]
    log.info("carteiras F1+F2 escolhidas", n=len(chosen), checadas=picked["checked"])

    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    progress = Progress(ctx, f"{STEP} fills", len(chosen))
    for address in chosen:
        try:
            records.append(fetch_wallet(ctx, client, address))
        except Exception as exc:  # RF-ING-07 CA-07.2
            failures.append({"address": address, "error": f"{type(exc).__name__}: {exc}"})
            log.error("carteira falhou", address=address, error=str(exc))
        progress.tick(address[:10], weight=int(client.budget.total_weight))

    # Notional por ativo (volume negociado, janela de seleção).
    all_fills = [f for rec in records for f in rec["fills"]]
    totals = notional_by_coin(all_fills)
    kind_of = {coin: classify_coin(coin, perp_names) for coin in totals}
    total_all = sum(totals.values())
    perp_totals = {c: v for c, v in totals.items() if is_perp(kind_of[c])}
    total_perp = sum(perp_totals.values())
    share_all = shares(totals, total_all)
    share_perp = shares(perp_totals, total_perp)
    ranked_all = sorted(share_all.items(), key=lambda kv: kv[1], reverse=True)
    ranked_perp = sorted(share_perp.items(), key=lambda kv: kv[1], reverse=True)

    def cumulative(share: dict[str, float]) -> float:
        return sum(share.get(coin, 0.0) for coin in UNIVERSE)

    cum_all, cum_perp = cumulative(share_all), cumulative(share_perp)
    kind_notional: Counter[str] = Counter()
    for coin, value in totals.items():
        kind_notional[kind_of[coin]] += value

    # Fração do universo por carteira (o que F9 vai medir): só informativo.
    per_wallet_share: list[float] = []
    for rec in records:
        wallet_totals = notional_by_coin(rec["fills"])
        denominator = sum(wallet_totals.values())
        if denominator > 0:
            per_wallet_share.append(sum(wallet_totals.get(c, 0.0) for c in UNIVERSE) / denominator)

    top = [
        {
            "coin": coin,
            "kind": kind_of[coin],
            "share_all": share_all[coin],
            "share_perps": share_perp.get(coin),
            "in_universe": coin in UNIVERSE,
        }
        for coin, _ in ranked_all[:15]
    ]
    for coin in UNIVERSE:  # BTC, ETH, SOL sempre aparecem, mesmo fora do top 15
        if all(row["coin"] != coin for row in top):
            top.append(
                {
                    "coin": coin,
                    "kind": kind_of.get(coin, "ausente"),
                    "share_all": share_all.get(coin, 0.0),
                    "share_perps": share_perp.get(coin),
                    "in_universe": True,
                }
            )

    # CA-02.2: a regra D7 só é aplicada se a cobertura ficar abaixo de 50%.
    d7: dict[str, Any] = {"applied": False}
    below = {"all_fills": cum_all < COVERAGE_TARGET, "perps_only": cum_perp < COVERAGE_TARGET}
    if any(below.values()) and records:
        day = sample_days(1)[0]
        http = httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        candidates = [
            c
            for c, _ in ranked_all
            if c not in UNIVERSE and kind_of[c] == "perp" and not meta["assets"][c]["isDelisted"]
        ][:40]
        equivalent: dict[str, bool] = {}
        symbols: dict[str, str | None] = {}
        for coin in candidates:
            equivalent[coin], symbols[coin] = binance_has_equivalent(http, coin, day)
        d7 = {
            "applied": True,
            "binance_check_day": day,
            "candidates_checked": len(candidates),
            "equivalent_symbols": {c: symbols[c] for c in candidates if equivalent[c]},
            "no_equivalent": [c for c in candidates if not equivalent[c]],
            "all_fills": d7_additions(ranked_all, UNIVERSE, equivalent, max_assets=D7_MAX_ASSETS)
            if below["all_fills"]
            else [],
            "perps_only": d7_additions(ranked_perp, UNIVERSE, equivalent, max_assets=D7_MAX_ASSETS)
            if below["perps_only"]
            else [],
        }

    c021 = criterion(
        "ok" if records and total_all > 0 else "não medido",
        {
            "wallets": len(records),
            "fills": len(all_fills),
            "notional_by_kind": {k: v / total_all for k, v in kind_notional.items()}
            if total_all
            else {},
            "top_assets": top,
            "universe_cumulative_all_fills": cum_all,
            "universe_cumulative_perps_only": cum_perp,
            "per_wallet_universe_share": {
                "n": len(per_wallet_share),
                "p25": percentile(per_wallet_share, 25) if per_wallet_share else None,
                "median": percentile(per_wallet_share, 50) if per_wallet_share else None,
                "p75": percentile(per_wallet_share, 75) if per_wallet_share else None,
                "ge_50pct": sum(s >= 0.5 for s in per_wallet_share),
            },
        },
        "informar a fração do notional em cada ativo e a fração acumulada no universo",
    )
    if not records or total_all == 0:
        status, note = "não medido", "sem fills na amostra"
    elif not any(below.values()):
        status, note = "ok", "cobertura >= 50% nas duas bases de cálculo"
    else:
        which = [k for k, v in below.items() if v]
        status = "a emendar"
        note = (
            "universo a emendar; abaixo de 50% em: "
            + ", ".join(which)
            + (
                " (a outra base fica em >= 50%: o denominador muda o status)"
                if len(which) == 1
                else ""
            )
        )
    c022 = criterion(
        status,
        {"cumulative_all_fills": cum_all, "cumulative_perps_only": cum_perp, "d7": d7},
        "se a fração acumulada < 50%: listar os ativos a acrescentar pela regra D7; status "
        "'universo a emendar'",
        note,
    )

    cont = continuity_and_episodes(records, meta)
    verdict, why = read_conciliation(cont["closed_pnl_ladder"], cont["closed_pnl"])

    result: dict[str, Any] = {
        "step": STEP,
        "sampling": {
            "seed": SEED,
            "f2_min_account_value": F2_MIN_ACCOUNT_VALUE,
            "pool_size_f2": picked["pool_size"],
            "userrole_checked": picked["checked"],
            "roles_among_checked": picked["roles"],
            "chosen": chosen,
        },
        "failures": failures,
        "criteria": {"RF-VER-02 CA-02.1": c021, "RF-VER-02 CA-02.2": c022},
        "history": {
            **retention_summary(records),
            "in_window_fills_total": len(all_fills),
            "wallet_summaries": [wallet_summary(r) for r in records],
        },
        "extended_sample_continuity": {k: v for k, v in cont.items() if k not in _HEAVY_KEYS},
        "extended_sample_closed_pnl_by_size": cont["closed_pnl_by_size"],
        "extended_sample_break_diagnostics": cont["break_diagnostics"],
        "extended_sample_closed_pnl_ladder": cont["closed_pnl_ladder"],
        "extended_sample_closed_pnl_per_fill": cont["closed_pnl_per_fill"],
        "extended_sample_closed_pnl": {
            "verdict": verdict,
            "detail": why,
            "counts": cont["closed_pnl"],
        },
        "client_stats": dict(client.stats),
        "budget": {
            "limit": client.budget.limit,
            "peak": client.budget.peak,
            "total_weight": client.budget.total_weight,
            "waited_s": client.budget.waited_s,
        },
        "window_start": iso(WINDOW_START_MS),
    }
    write_json(ctx.path("results", "v02.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    run(make_ctx(args.smoke), HlClient(RateBudget()))


if __name__ == "__main__":
    main()
