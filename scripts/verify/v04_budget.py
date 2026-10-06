"""RF-VER-04 — orçamento de dados (CA-04.1 a CA-04.3), e RF-VER-01 CA-01.5.

Lê a gravação feita por `record.py` (uma hora, `l2Book` + `bbo` + `trades` de BTC, ETH
e SOL) e os arquivos do preço proxy baixados por `v03_proxy.py`. Extrapola bytes para
45 dias de coletor e para as janelas do proxy, e compara com o orçamento de disco de
RNF-10 (30 GB). Mede e reporta: não decide o formato de gravação do coletor.

A gravação guarda a mensagem JSON bruta mais o instante de recebimento. Os bytes são,
portanto, os da *representação mais verbosa*; o tamanho comprimido (gzip) é reportado ao
lado como referência do que um formato mais enxuto poderia poupar.

Uso: `python scripts/verify/v04_budget.py [--smoke]`
"""

from __future__ import annotations

import argparse
import json
import zlib
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from analysis import percentile
from common import (
    DISK_BUDGET_BYTES,
    UNIVERSE,
    Ctx,
    iso,
    make_ctx,
    read_json,
    setup_logging,
    write_json,
)
from v01_schema import criterion, trades_users_check

STEP = "RF-VER-04"
COLLECTOR_DAYS = 45  # RF-VER-04 CA-04.1
#: Dias de preço proxy: Rota A (seleção 62 + avaliação 30) + Rota B (seleção 62, §7.2). Os
#: intervalos podem se sobrepor no calendário; a soma é um limite superior.
PROXY_DAYS_ROUTE_A = 62 + 30
PROXY_DAYS_ALL = 62 + 30 + 62
GAP_THRESHOLD_S = 10.0  # RF-COL-02 CA-02.2
GB = 1024**3


def gzip_size(path: Path) -> int:
    compressor = zlib.compressobj(6, zlib.DEFLATED, 31)
    total = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            total += len(compressor.compress(block))
    return total + len(compressor.flush())


def server_times(channel: str, raw: str) -> list[int]:
    data = json.loads(raw)["data"]
    if channel == "trades":
        return [int(t["time"]) for t in data]
    return [int(data["time"])]


def connect_times(ws_dir: Path) -> dict[str, list[int]]:
    """Instantes de (re)conexão por nome de conexão, do `events.tsv`."""
    out: dict[str, list[int]] = defaultdict(list)
    events = ws_dir / "events.tsv"
    if events.exists():
        for line in events.read_text(encoding="utf-8").splitlines():
            ts, kind, detail = [*line.split("\t"), "", ""][:3]
            if kind == "connect":
                out[detail].append(int(ts))
    return out


def analyse_file(path: Path, channel: str, connects: list[int]) -> dict[str, Any]:
    """Bytes, mensagens, atrasos e intervalos de um arquivo (ativo, canal).

    A primeira mensagem depois de cada (re)conexão é o *snapshot* da assinatura (no
    `trades`, um lote de negócios antigos) e fica de fora das medidas de atraso e de
    intervalo, que descrevem o fluxo ao vivo. Os bytes contam tudo o que foi gravado.
    """
    recv: list[int] = []
    raws: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        recv_text, _, raw = line.partition("\t")
        recv.append(int(recv_text))
        raws.append(raw)
    snapshot_idx: set[int] = set()
    for ct in connects:
        idx = next((i for i, r in enumerate(recv) if r >= ct), None)
        if idx is not None:
            snapshot_idx.add(idx)

    latency: list[float] = []
    server: list[int] = []
    items = 0
    snapshot_items = 0
    snapshot_max_age_s = 0.0
    live_recv: list[int] = []
    for i, (r, raw) in enumerate(zip(recv, raws, strict=True)):
        times = server_times(channel, raw)
        if i in snapshot_idx:
            snapshot_items += len(times)
            snapshot_max_age_s = max(snapshot_max_age_s, max((r - t) / 1000 for t in times))
            continue
        live_recv.append(r)
        for t in times:
            items += 1
            latency.append(r - t)
            server.append(t)
    gaps_recv = [(b - a) / 1000 for a, b in pairwise(live_recv)]
    server_sorted = sorted(set(server))
    inter_server = [(b - a) / 1000 for a, b in pairwise(server_sorted)]
    return {
        "bytes": path.stat().st_size,
        "gzip_bytes": gzip_size(path),
        "messages": len(recv),
        "items": items,
        "snapshot_messages": len(snapshot_idx),
        "snapshot_items": snapshot_items,
        "snapshot_max_age_s": snapshot_max_age_s,
        "first_recv": recv[0] if recv else None,
        "last_recv": recv[-1] if recv else None,
        "latency_ms": {
            "p50": percentile(latency, 50),
            "p95": percentile(latency, 95),
            "p99": percentile(latency, 99),
            "negative_fraction": sum(v < 0 for v in latency) / len(latency),
        }
        if latency
        else None,
        "recv_gap_s": {
            "p50": percentile(gaps_recv, 50),
            "p95": percentile(gaps_recv, 95),
            "max": max(gaps_recv),
            "over_threshold": sum(g > GAP_THRESHOLD_S for g in gaps_recv),
        }
        if gaps_recv
        else None,
        "server_interval_s": {
            "p50": percentile(inter_server, 50),
            "p95": percentile(inter_server, 95),
        }
        if inter_server
        else None,
    }


def analyse_recording(ws_dir: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = defaultdict(dict)
    connects = connect_times(ws_dir)
    for coin in UNIVERSE:
        for channel in ("l2Book", "l2BookFast", "bbo", "trades"):
            path = ws_dir / f"{coin}.{channel}.tsv"
            if path.exists() and path.stat().st_size:
                conn = "l2Book-fast" if channel == "l2BookFast" else "principal"
                files[coin][channel] = analyse_file(
                    path, "l2Book" if channel == "l2BookFast" else channel, connects.get(conn, [])
                )
    firsts = [c["first_recv"] for per in files.values() for c in per.values() if c["first_recv"]]
    lasts = [c["last_recv"] for per in files.values() for c in per.values() if c["last_recv"]]
    duration_s = (max(lasts) - min(firsts)) / 1000 if firsts and lasts else 0.0
    events = ws_dir / "events.tsv"
    kinds = (
        [line.split("\t")[1] for line in events.read_text().splitlines()] if events.exists() else []
    )
    return {
        "files": files,
        "duration_s": duration_s,
        "started": iso(min(firsts)) if firsts else None,
        "events": {k: kinds.count(k) for k in sorted(set(kinds))},
    }


def extrapolate(rec: dict[str, Any]) -> dict[str, Any]:
    hours = rec["duration_s"] / 3600
    out: dict[str, Any] = {"hours_measured": hours, "per_coin": {}, "total": {}}
    variants = {
        "default": ("l2Book", "bbo", "trades"),
        "fast": ("l2BookFast", "bbo", "trades"),
        "no_book_depth": ("bbo", "trades"),
    }
    totals: dict[str, dict[str, float]] = {
        v: {"raw": 0.0, "gzip": 0.0, "measured_raw": 0.0} for v in variants
    }
    for coin, per in rec["files"].items():
        out["per_coin"][coin] = {}
        for variant, channels in variants.items():
            raw = sum(per[c]["bytes"] for c in channels if c in per)
            gz = sum(per[c]["gzip_bytes"] for c in channels if c in per)
            scale = 24 * COLLECTOR_DAYS / hours if hours else 0.0
            out["per_coin"][coin][variant] = {
                "measured_bytes": raw,
                "bytes_45d": raw * scale,
                "gzip_bytes_45d": gz * scale,
            }
            totals[variant]["raw"] += raw * scale
            totals[variant]["gzip"] += gz * scale
            totals[variant]["measured_raw"] += raw
    out["total"] = {
        v: {"measured_bytes": t["measured_raw"], "bytes_45d": t["raw"], "gzip_bytes_45d": t["gzip"]}
        for v, t in totals.items()
    }
    return out


def proxy_extrapolation(files: list[dict[str, Any]]) -> dict[str, Any]:
    per_coin: dict[str, Any] = {}
    for coin in UNIVERSE:
        mine = [f for f in files if f["coin"] == coin]
        if not mine:
            continue
        n = len(mine)
        zip_mean = sum(f["zip_bytes"] for f in mine) / n
        csv_mean = sum(f["csv_bytes"] for f in mine) / n
        series_mean = sum(f["series_bytes"] for f in mine) / n
        per_coin[coin] = {
            "days_measured": n,
            "zip_mean_bytes": zip_mean,
            "csv_mean_bytes": csv_mean,
            "series_mean_bytes": series_mean,
            "zip_route_a": zip_mean * PROXY_DAYS_ROUTE_A,
            "zip_all": zip_mean * PROXY_DAYS_ALL,
            "series_all": series_mean * PROXY_DAYS_ALL,
            "csv_all": csv_mean * PROXY_DAYS_ALL,
        }
    return {
        "per_coin": per_coin,
        "total": {
            k: sum(v[k] for v in per_coin.values())
            for k in ("zip_route_a", "zip_all", "series_all", "csv_all")
        },
    }


def run(ctx: Ctx) -> dict[str, Any]:
    log = setup_logging()
    ws_dir = ctx.path("ws", "main", "x").parent
    criteria: dict[str, Any] = {}
    result: dict[str, Any] = {"step": STEP, "criteria": criteria}

    # RF-VER-01 CA-01.5
    users = trades_users_check(ws_dir)
    result["trades_users"] = users
    if not users["available"] or not users["trades"]:
        criteria["RF-VER-01 CA-01.5"] = criterion(
            "não medido", users, "cada negócio traz os endereços das duas pontas", "sem gravação"
        )
    else:
        short = users["covered_seconds"] < 600
        full = users["fraction"] == 1.0
        criteria["RF-VER-01 CA-01.5"] = criterion(
            "ok" if full else "a emendar",
            {k: v for k, v in users.items() if k != "available"},
            "cada negócio traz os endereços das duas pontas; se não trouxer, RF-COL-03 sai do "
            "escopo por emenda",
            ("gravação de " + f"{users['covered_seconds']:.0f} s (< 10 min)") if short else "",
        )

    # RF-VER-04 CA-04.1
    done = (ws_dir / "DONE").exists()
    if ws_dir.exists() and any(ws_dir.glob("*.tsv")):
        rec = analyse_recording(ws_dir)
        ext = extrapolate(rec)
        result["recording"] = {**rec, "done_marker": done}
        result["collector_extrapolation"] = ext
        minutes = rec["duration_s"] / 60
        note = "" if minutes >= 55 or ctx.smoke else f"gravação de {minutes:.0f} min (< 1 hora)"
        criteria["RF-VER-04 CA-04.1"] = criterion(
            "ok" if len(rec["files"]) == len(UNIVERSE) else "não medido",
            {
                "duration_min": minutes,
                "total": ext["total"],
                "per_coin": ext["per_coin"],
                "events": rec["events"],
            },
            "bytes gravados por ativo em uma hora e a extrapolação para 45 dias",
            note,
        )
    else:
        ext = None
        criteria["RF-VER-04 CA-04.1"] = criterion(
            "não medido",
            {},
            "bytes gravados por ativo em uma hora e extrapolação para 45 dias",
            "sem gravação",
        )

    # RF-VER-04 CA-04.2
    v03 = ctx.path("results", "v03.json")
    proxy = proxy_extrapolation(read_json(v03)["proxy_files"]) if v03.exists() else None
    result["proxy_extrapolation"] = proxy
    if proxy and proxy["per_coin"]:
        criteria["RF-VER-04 CA-04.2"] = criterion(
            "ok",
            {
                "days_assumed_route_a": PROXY_DAYS_ROUTE_A,
                "days_assumed_all_windows": PROXY_DAYS_ALL,
                **proxy,
            },
            "tamanho de um dia de proxy por ativo e extrapolação para todas as janelas",
            "janelas somadas sem deduplicar sobreposição de calendário: limite superior",
        )
    else:
        criteria["RF-VER-04 CA-04.2"] = criterion(
            "não medido", {}, "tamanho de um dia de proxy e extrapolação", "sem download"
        )

    # RF-VER-04 CA-04.3
    rows: list[dict[str, Any]] = []
    sums: list[dict[str, Any]] = []
    labels = {
        "default": "l2Book default (20 níveis, ~5 s) + bbo + trades",
        "fast": "l2Book rápido (5 níveis, ~0,5 s) + bbo + trades",
        "no_book_depth": "bbo + trades, sem l2Book",
    }
    if ext:
        for variant, label in labels.items():
            if variant in ext["total"]:
                t = ext["total"][variant]
                rows.append({"item": f"coletor, 45 dias, {label} (bruto)", "bytes": t["bytes_45d"]})
                rows.append(
                    {"item": f"coletor, 45 dias, {label} (gzip)", "bytes": t["gzip_bytes_45d"]}
                )
    if proxy and proxy["per_coin"]:
        rows.append(
            {
                "item": f"proxy, {PROXY_DAYS_ALL} dias, zips mantidos",
                "bytes": proxy["total"]["zip_all"],
            }
        )
        rows.append(
            {
                "item": f"proxy, {PROXY_DAYS_ALL} dias, só a série por segundo",
                "bytes": proxy["total"]["series_all"],
            }
        )
    if ext and proxy and proxy["per_coin"]:
        worst = max(ext["total"].values(), key=lambda t: t["bytes_45d"])
        best = min(ext["total"].values(), key=lambda t: t["gzip_bytes_45d"])
        sums.append(
            {
                "item": "soma pior caso: maior variante do coletor (bruto) + zips do proxy",
                "bytes": worst["bytes_45d"] + proxy["total"]["zip_all"],
            }
        )
        sums.append(
            {
                "item": "soma melhor caso: menor variante do coletor (gzip) + série por segundo",
                "bytes": best["gzip_bytes_45d"] + proxy["total"]["series_all"],
            }
        )
    for row in rows + sums:
        row["gb"] = row["bytes"] / GB
        row["exceeds_30gb"] = row["bytes"] > DISK_BUDGET_BYTES
    if not rows:
        criteria["RF-VER-04 CA-04.3"] = criterion(
            "não medido",
            {},
            "alguma extrapolação > orçamento de RNF-10 (30 GB): orçamento a emendar",
            "sem extrapolações",
        )
    else:
        over = [r["item"] for r in rows if r["exceeds_30gb"]]
        over_sum = [r["item"] for r in sums if r["exceeds_30gb"]]
        criteria["RF-VER-04 CA-04.3"] = criterion(
            "a emendar" if over else "ok",
            {"budget_gb": DISK_BUDGET_BYTES / GB, "individual": rows, "sums": sums},
            "alguma extrapolação excede o orçamento de RNF-10 (30 GB): 'orçamento a emendar'",
            ("excedem: " + "; ".join(over))
            if over
            else (
                "nenhuma extrapolação individual excede; somas acima de 30 GB: "
                + "; ".join(over_sum)
                if over_sum
                else ""
            ),
        )
    log.info("RF-VER-04 concluído", criterios=list(criteria))
    write_json(ctx.path("results", "v04.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    run(make_ctx(args.smoke))


if __name__ == "__main__":
    main()
