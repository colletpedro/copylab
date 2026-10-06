"""RF-VER-05 — verificação complementar (CA-05.1 a CA-05.4).

Fecha o que a primeira execução deixou em aberto. Valem as regras do prompt 02: somente
leitura, **nada de desempenho** (CA-05.2 devolve razões e contagens, nunca valores de PnL),
**nada de conteúdo da janela de avaliação** (toda consulta é cortada em `CUTOFF_MS - 1`),
orçamento de peso com folga, semente fixa.

- CA-05.1: como a coleta paginou, onde as quebras de continuidade caem em relação às
  fronteiras de página (medido recoletando as carteiras com quebra, com a paginação
  instrumentada) e uma consulta nova, de uma hora em torno de 10 quebras sorteadas.
- CA-05.2: offline, sobre os fills já gravados.
- CA-05.3: `fundingHistory` de BTC por uma semana da janela de seleção.
- CA-05.4: offline, mais a existência dos equivalentes na Binance em vários dias.

Uso: `python scripts/verify/v05_complement.py [--smoke]`
"""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter, defaultdict
from itertools import pairwise
from typing import Any

import httpx

from analysis import (
    build_episodes,
    classify_coin,
    continuity_break_pairs,
    notional_by_coin,
    percentile,
    pnl_divergence_bps,
    ratio_summary,
    size_band,
)
from common import (
    BINANCE_BASE,
    CUTOFF_MS,
    PAGE_MAX,
    SEED,
    UNIVERSE,
    USER_AGENT,
    WINDOW_START_MS,
    Ctx,
    HlClient,
    Progress,
    RateBudget,
    _fill_key,
    collect_fills,
    day_of,
    iso,
    load_meta,
    make_ctx,
    read_json,
    sample_days,
    setup_logging,
    write_json,
)
from v01_schema import criterion
from v02_universe import binance_symbol_candidates

STEP = "RF-VER-05"
MINUTE_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
N_BREAKS_TO_REQUERY = 10
F9_SHARE = 0.5
TOP_ASSETS = 30
FUNDING_HOURS = 168
SIZE_BANDS = ("2", "3-4", "5+")


def load_records(ctx: Ctx) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Todas as carteiras em cache, e os endereços de cada amostra (RF-VER-01 e RF-VER-02)."""
    sample_01 = read_json(ctx.path("results", "v01.json"))["sample"]
    sample_02 = read_json(ctx.path("results", "v02.json"))["sampling"]["chosen"]
    addresses = sorted(set(sample_01) | set(sample_02))
    records = []
    for address in addresses:
        cache = ctx.path("fills", f"{address}.json")
        if cache.exists():
            records.append(read_json(cache))
    return records, sample_01, sample_02


def perp_series(
    rec: dict[str, Any], assets: dict[str, Any]
) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """Fills de perpétuo do primeiro dex por ativo, com a posição de cada um na carteira."""
    perp_names = frozenset(assets)
    by_coin: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for pos, fill in enumerate(rec["fills"]):
        if classify_coin(str(fill.get("coin")), perp_names) == "perp":
            by_coin[fill["coin"]].append((pos, fill))
    return by_coin


def find_breaks(records: list[dict[str, Any]], assets: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        for coin, items in perp_series(rec, assets).items():
            lot = 10 ** -int(assets[coin]["szDecimals"])
            fills = [f for _, f in items]
            for i, j in continuity_break_pairs(fills, lot):
                out.append(
                    {
                        "address": rec["address"],
                        "coin": coin,
                        "pos_a": items[i][0],
                        "pos_b": items[j][0],
                        "t_a": int(items[i][1]["time"]),
                        "t_b": int(items[j][1]["time"]),
                    }
                )
    return sorted(out, key=lambda b: (b["address"], b["coin"], b["t_a"]))


SPAN_BANDS = ((1, 1, "1"), (2, 10, "2 a 10"), (11, 100, "11 a 100"), (101, 1000, "101 a 1000"))


def span_band(distance: int) -> str:
    """Faixa do vão, em posições da lista de fills da carteira, entre os dois fills de um par."""
    for low, high, name in SPAN_BANDS:
        if low <= distance <= high:
            return name
    return "mais de 1000"


def straddle_by_span(
    records: list[dict[str, Any]],
    assets: dict[str, Any],
    boundaries: dict[str, list[int]],
    broken: set[tuple[str, str, int]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Por faixa de vão: pares consecutivos do mesmo ativo (quebrados e íntegros) e quantos
    atravessam uma fronteira de página. Comparar quebra e par íntegro de *mesmo vão* evita o
    viés de que um vão longo atravessa fronteira só por ser longo."""
    out: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: {"broken": Counter(), "intact": Counter()}
    )
    for rec in records:
        marks = boundaries.get(rec["address"])
        if marks is None:
            continue
        for coin, items in perp_series(rec, assets).items():
            for (pos_a, fa), (pos_b, _) in pairwise(items):
                kind = "broken" if (rec["address"], coin, int(fa["time"])) in broken else "intact"
                band = span_band(pos_b - pos_a)
                out[band][kind]["pairs"] += 1
                out[band][kind]["crossing"] += any(pos_a < m <= pos_b for m in marks)
    return {band: {k: dict(v) for k, v in kinds.items()} for band, kinds in out.items()}


def recollect(
    ctx: Ctx, client: HlClient, addresses: list[str], cached: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Recoleta a janela de seleção das carteiras com quebra, guardando as fronteiras de página."""
    out: dict[str, dict[str, Any]] = {}
    progress = Progress(ctx, f"{STEP} recoleta", len(addresses))
    for address in addresses:
        got = collect_fills(client, address, WINDOW_START_MS, CUTOFF_MS - 1, keep=True)
        window = [f for f in got.fills if WINDOW_START_MS <= int(f["time"]) < CUTOFF_MS]
        before = Counter(_fill_key(f) for f in cached[address]["fills"])
        after = Counter(_fill_key(f) for f in window)
        out[address] = {
            "pages": got.pages,
            "count": len(window),
            "boundaries": got.boundaries,
            "identical_to_first_collection": before == after,
            "only_in_first": sum((before - after).values()),
            "only_in_second": sum((after - before).values()),
            "same_order": [_fill_key(f) for f in window]
            == [_fill_key(f) for f in cached[address]["fills"]],
        }
        progress.tick(address[:10], weight=int(client.budget.total_weight))
    return out


def requery(client: HlClient, rec: dict[str, Any], brk: dict[str, Any]) -> dict[str, Any]:
    """Nova consulta do intervalo entre os dois fills quebrados (1 min de folga, até 2 páginas).

    O intervalo é cortado na janela de seleção (nada de antes dela nem do corte T). Compara
    por chave os fills devolvidos com os já gravados.
    """
    start = max(brk["t_a"] - MINUTE_MS, WINDOW_START_MS)
    end = min(brk["t_b"] + MINUTE_MS, CUTOFF_MS - 1)
    # Mesma paginação e mesma deduplicação da coleta (início inclusivo, multiconjunto na
    # fronteira). Uma primeira versão desta função somava as páginas sem deduplicar e contou as
    # repetições do milissegundo da fronteira como "fill que faltava"; ver o relatório.
    got = collect_fills(client, brk["address"], start, end, keep=True, max_pages=2)
    returned = Counter(
        _fill_key(f) for f in got.fills if WINDOW_START_MS <= int(f["time"]) < CUTOFF_MS
    )
    complete = not got.truncated
    last = max((int(f["time"]) for f in got.fills), default=start)
    stored = Counter(
        _fill_key(f) for f in rec["fills"] if start <= int(f["time"]) <= (end if complete else last)
    )
    return {
        "address": brk["address"],
        "coin": brk["coin"],
        "gap_s": (brk["t_b"] - brk["t_a"]) / 1000,
        "interval_s": (end - start) / 1000,
        "pages": got.pages,
        "returned": sum(returned.values()),
        "stored_in_range": sum(stored.values()),
        "missing_from_stored": sum((returned - stored).values()),
        "stored_not_returned": sum((stored - returned).values()) if complete else None,
        "covers_whole_interval": complete,
    }


def ca_051(
    ctx: Ctx, client: HlClient, records: list[dict[str, Any]], meta: dict[str, Any]
) -> dict[str, Any]:
    assets = meta["assets"]
    cached = {r["address"]: r for r in records}
    breaks = find_breaks(records, assets)
    addresses = sorted({b["address"] for b in breaks})
    recollected = recollect(ctx, client, addresses, cached) if addresses else {}
    boundaries = {a: v["boundaries"] for a, v in recollected.items() if v["same_order"]}

    classified = []
    for b in breaks:
        marks = boundaries.get(b["address"])
        if marks is None:
            classified.append({**b, "straddles": None, "adjacent": None})
            continue
        classified.append(
            {
                **b,
                "straddles": any(b["pos_a"] < m <= b["pos_b"] for m in marks),
                "adjacent": b["pos_b"] == b["pos_a"] + 1 and b["pos_b"] in marks,
            }
        )
    known = [c for c in classified if c["straddles"] is not None]
    broken_keys = {(b["address"], b["coin"], b["t_a"]) for b in breaks}
    by_span = straddle_by_span(records, assets, boundaries, broken_keys)

    picks = (
        random.Random(SEED).sample(breaks, min(N_BREAKS_TO_REQUERY, len(breaks))) if breaks else []
    )
    progress = Progress(ctx, f"{STEP} consultas das quebras", max(len(picks), 1))
    queries = []
    for brk in picks:
        queries.append(requery(client, cached[brk["address"]], brk))
        progress.tick(brk["address"][:10], weight=int(client.budget.total_weight))
    returned_missing = [q for q in queries if q["missing_from_stored"] > 0]

    # Complemento (fora da spec): reconsulta as demais quebras do mesmo jeito. Custa pouco e
    # transforma a amostra de 10 num censo das 100.
    picked = {(b["address"], b["coin"], b["t_a"]) for b in picks}
    rest = [b for b in breaks if (b["address"], b["coin"], b["t_a"]) not in picked]
    progress = Progress(ctx, f"{STEP} consultas do complemento", max(len(rest), 1))
    census = []
    for brk in rest:
        census.append(requery(client, cached[brk["address"]], brk))
        progress.tick(brk["address"][:10], weight=int(client.budget.total_weight))
    return {
        "pagination": {
            "start_of_page": "inclusivo (startTime = instante do último fill da página anterior)",
            "dedup": "multiconjunto de chaves dos fills do milissegundo da fronteira",
            "page_max": PAGE_MAX,
            "stored_boundaries_in_first_collection": False,
        },
        "breaks_total": len(breaks),
        "wallets_with_breaks": len(addresses),
        "recollection": {
            a: {k: v for k, v in r.items() if k != "boundaries"}
            | {"n_boundaries": len(r["boundaries"])}
            for a, r in recollected.items()
        },
        "classified_breaks": len(known),
        "straddling_a_page_boundary": sum(bool(c["straddles"]) for c in known),
        "adjacent_across_a_page_boundary": sum(bool(c["adjacent"]) for c in known),
        "straddle_by_span": by_span,
        "queries": queries,
        "queries_returning_a_missing_fill": len(returned_missing),
        "queries_covering_whole_interval": sum(q["covers_whole_interval"] for q in queries),
        "complement_all_other_breaks": {
            "queries": len(census),
            "covering_whole_interval": sum(q["covers_whole_interval"] for q in census),
            "returning_a_missing_fill": sum(q["missing_from_stored"] > 0 for q in census),
            "with_stored_fills_not_returned": sum(bool(q["stored_not_returned"]) for q in census),
            "with_two_pages": sum(q["pages"] >= 2 for q in census),
            "not_clean": [
                q for q in census if q["missing_from_stored"] or not q["covers_whole_interval"]
            ],
            "fills_returned_total": sum(q["returned"] for q in census),
        },
    }


def ca_052(
    records: list[dict[str, Any]],
    assets: dict[str, Any],
    sample_01: list[str],
    sample_02: list[str],
) -> dict[str, Any]:
    perp_names = frozenset(assets)
    pairs: list[tuple[str, int, float]] = []
    for rec in records:
        by_coin: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fill in rec["fills"]:
            if classify_coin(str(fill.get("coin")), perp_names) == "perp":
                by_coin[fill["coin"]].append(fill)
        for coin, fills in by_coin.items():
            lot = 10 ** -int(assets[coin]["szDecimals"])
            pairs += [
                (rec["address"], n, bps)
                for n, bps in pnl_divergence_bps(build_episodes(fills, lot))
            ]
    bands = {b: [bps for _, n, bps in pairs if size_band(n) == b] for b in SIZE_BANDS}
    in_01 = set(sample_01)
    in_02 = set(sample_02)
    return {
        "all": ratio_summary([bps for _, _, bps in pairs]),
        "by_band": {b: ratio_summary(v) for b, v in bands.items()},
        "by_sample": {
            "amostra de RF-VER-01 (20)": ratio_summary([bps for a, _, bps in pairs if a in in_01]),
            "amostra de RF-VER-02 (100)": ratio_summary([bps for a, _, bps in pairs if a in in_02]),
        },
    }


def ca_053(client: HlClient) -> dict[str, Any]:
    block = random.Random(SEED).randrange((CUTOFF_MS - WINDOW_START_MS) // (7 * DAY_MS))
    start = WINDOW_START_MS + block * 7 * DAY_MS
    end = start + FUNDING_HOURS * HOUR_MS - 1
    payload, _ = client.info(
        {"type": "fundingHistory", "coin": "BTC", "startTime": start, "endTime": end},
        reserve=20 + math.ceil(500 / 20),
    )
    rows = payload if isinstance(payload, list) else []
    times = sorted(int(r["time"]) for r in rows)
    hours = Counter((t - start) // HOUR_MS for t in times)
    gaps = [(b - a) / 1000 for a, b in pairwise(times)]
    offsets = [(t - start) % HOUR_MS for t in times]
    missing = [h for h in range(FUNDING_HOURS) if hours[h] == 0]
    return {
        "week": {"start": iso(start), "end": iso(end + 1), "block_index": block},
        "records": len(rows),
        "fields": {k: type(v).__name__ for k, v in rows[0].items()} if rows else {},
        "interval_s": {
            "min": min(gaps) if gaps else None,
            "median": percentile(gaps, 50) if gaps else None,
            "max": max(gaps) if gaps else None,
        },
        "offset_in_hour_ms": {
            "min": min(offsets) if offsets else None,
            "max": max(offsets) if offsets else None,
        },
        "hours_with_a_record": sum(1 for h in range(FUNDING_HOURS) if hours[h] > 0),
        "hours_with_more_than_one": [h for h, n in hours.items() if n > 1],
        "missing_hours": missing,
        "outside_the_168_hours": sum(1 for t in times if not start <= t <= end),
    }


def binance_days(extra: int) -> list[str]:
    first, last = day_of(WINDOW_START_MS), day_of(CUTOFF_MS - 1)
    return sorted({*sample_days(extra), first, last})


def equivalence(http: httpx.Client, coin: str, days: list[str]) -> dict[str, Any]:
    """Para cada símbolo candidato, em quantos dos `days` o arquivo diário existe na Binance."""
    best: dict[str, Any] = {"symbol": None, "days_present": 0}
    for symbol in binance_symbol_candidates(coin):
        present = 0
        for day in days:
            url = f"{BINANCE_BASE}/{symbol}/{symbol}-aggTrades-{day}.zip"
            try:
                present += http.head(url).status_code == 200
            except httpx.TransportError:
                continue
        if present > best["days_present"]:
            best = {"symbol": symbol, "days_present": present}
    return {**best, "days_checked": len(days), "all_days": best["days_present"] == len(days)}


def ca_054(
    ctx: Ctx, records: list[dict[str, Any]], meta: dict[str, Any], sample_02: list[str]
) -> dict[str, Any]:
    assets = meta["assets"]
    perp_names = frozenset(assets)
    mine = [r for r in records if r["address"] in set(sample_02)]
    fills = [f for r in mine for f in r["fills"]]
    totals = notional_by_coin(fills)
    counts = Counter(f["coin"] for f in fills)
    grand = sum(totals.values())
    perp_total = sum(v for c, v in totals.items() if classify_coin(c, perp_names) == "perp")
    top = sorted(
        (c for c in totals if classify_coin(c, perp_names) == "perp"),
        key=lambda c: totals[c],
        reverse=True,
    )[:TOP_ASSETS]
    days = binance_days(ctx.n_days if not ctx.smoke else 1)
    http = httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    rows = []
    for coin in top:
        eq = equivalence(http, coin, days)
        rows.append(
            {
                "coin": coin,
                "fills": counts[coin],
                "notional_share_all": totals[coin] / grand if grand else None,
                "notional_share_perps": totals[coin] / perp_total if perp_total else None,
                "is_delisted": assets[coin]["isDelisted"],
                **eq,
            }
        )
    listed_equivalent = [r["coin"] for r in rows if r["all_days"]]
    partial = [r["coin"] for r in rows if r["days_present"] and not r["all_days"]]

    active = [r for r in mine if r["in_window_count"] > 0]
    universes = {
        "BTC, ETH e SOL": set(UNIVERSE),
        "todos os listados com equivalente": set(listed_equivalent),
    }
    f9: dict[str, Any] = {}
    for name, members in universes.items():
        shares = []
        for rec in active:
            per_wallet = notional_by_coin(rec["fills"])
            denom = sum(per_wallet.values())
            if denom > 0:
                shares.append(sum(per_wallet.get(c, 0.0) for c in members) / denom)
        f9[name] = {
            "assets": len(members),
            "wallets": len(shares),
            "at_least_50pct": sum(s >= F9_SHARE for s in shares),
            "share_p25": percentile(shares, 25) if shares else None,
            "share_median": percentile(shares, 50) if shares else None,
            "share_p75": percentile(shares, 75) if shares else None,
        }
    return {
        "days_checked_on_binance": days,
        "top_assets": rows,
        "listed_with_equivalent_all_days": listed_equivalent,
        "listed_with_equivalent_on_some_days": partial,
        "wallets_with_fills_in_window": len(active),
        "wallets_in_sample": len(mine),
        "f9": f9,
    }


def run(ctx: Ctx, client: HlClient) -> dict[str, Any]:
    log = setup_logging()
    meta = load_meta(ctx, client)
    records, sample_01, sample_02 = load_records(ctx)
    log.info("carteiras em cache", n=len(records))

    a051 = ca_051(ctx, client, records, meta)
    a052 = ca_052(records, meta["assets"], sample_01, sample_02)
    a053 = ca_053(client)
    a054 = ca_054(ctx, records, meta, sample_02)

    explained = a051["queries_returning_a_missing_fill"]
    c051 = criterion(
        "não medido" if not a051["queries"] else ("a emendar" if explained else "ok"),
        {
            "breaks": a051["breaks_total"],
            "straddling_a_page_boundary": a051["straddling_a_page_boundary"],
            "adjacent_across_a_page_boundary": a051["adjacent_across_a_page_boundary"],
            "queries": len(a051["queries"]),
            "queries_returning_a_missing_fill": explained,
            "queries_covering_whole_interval": a051["queries_covering_whole_interval"],
        },
        "quantas quebras coincidem com fronteira de página; em 10 quebras sorteadas, uma nova "
        "consulta de 1 hora devolve fill que faltava? Se sim, o defeito é da coleta",
        "" if not explained else "alguma consulta devolveu fill ausente da coleta",
    )
    fraction = a052["all"].get("fraction_above")
    c052 = criterion(
        "não medido" if fraction is None else ("a emendar" if fraction > 0.05 else "ok"),
        {"all": a052["all"], "by_band": a052["by_band"]},
        "mediana, p95, p99 e máximo da razão |reconstruído - closedPnl| / notional, em bps, por "
        "faixa de fills, e a fração acima de 1 bp; acima de 5% RF-ING-04 CA-04.2 volta para emenda",
    )
    full = a053["hours_with_a_record"] == FUNDING_HOURS and not a053["hours_with_more_than_one"]
    c053 = criterion(
        "ok" if a053["records"] else "não medido",
        {k: v for k, v in a053.items() if k != "missing_hours"}
        | {"missing_hours": len(a053["missing_hours"])},
        "formato da resposta de fundingHistory e se há uma taxa para cada hora cheia",
        "" if full else "há hora sem registro ou com mais de um",
    )
    c054 = criterion(
        "ok" if a054["wallets_with_fills_in_window"] else "não medido",
        {
            "top_assets": len(a054["top_assets"]),
            "equivalent_all_days": len(a054["listed_with_equivalent_all_days"]),
            "f9": a054["f9"],
        },
        "30 perpétuos de maior notional, fills e equivalente na Binance; carteiras com 50% ou mais "
        "do "
        "notional no universo, para dois universos (informativo)",
    )
    result: dict[str, Any] = {
        "step": STEP,
        "ca_051": a051,
        "ca_052": a052,
        "ca_053": a053,
        "ca_054": a054,
        "criteria": {
            "RF-VER-05 CA-05.1": c051,
            "RF-VER-05 CA-05.2": c052,
            "RF-VER-05 CA-05.3": c053,
            "RF-VER-05 CA-05.4": c054,
        },
        "client_stats": dict(client.stats),
        "budget": {
            "limit": client.budget.limit,
            "peak": client.budget.peak,
            "total_weight": client.budget.total_weight,
            "waited_s": client.budget.waited_s,
        },
    }
    write_json(ctx.path("results", "v05.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    run(make_ctx(args.smoke), HlClient(RateBudget()))


if __name__ == "__main__":
    main()
