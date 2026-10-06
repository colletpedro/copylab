"""RF-VER-03 — validade do preço proxy (CA-03.1 e CA-03.2).

Compara fills de líderes (a amostra de RF-VER-02, só da janela de seleção) com o preço do
perpétuo equivalente na Binance **no mesmo segundo**. Para limitar o download, sorteia
cinco dias da janela (semente fixa) e baixa só esses dias por ativo.

Diferença em bps: `(px do fill - proxy) / proxy * 10_000`, com o proxy do segundo
reduzido a `last` (último negócio do segundo) como base e `mid = (min + max) / 2` como
sensibilidade. Segundo sem negócio na Binance fica ausente (não é preenchido) e é contado.

A spec não diz se o critério de CA-03.2 vale por ativo ou por ativo-dia: o script reporta
as duas leituras e não escolhe.

Uso: `python scripts/verify/v03_proxy.py [--smoke]`
"""

from __future__ import annotations

import argparse
import hashlib
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from analysis import percentile
from common import (
    BINANCE_BASE,
    BINANCE_SYMBOL,
    SEED,
    UNIVERSE,
    USER_AGENT,
    WINDOW_START_MS,
    Ctx,
    Progress,
    day_of,
    make_ctx,
    read_json,
    sample_days,
    setup_logging,
    write_json,
)
from v01_schema import criterion

STEP = "RF-VER-03"
MIN_FILLS_PER_ASSET = 10_000  # CA-03.1
INVALID_ABOVE_BPS = 10.0  # CA-03.2
CSV_COLUMNS = [
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
]


def download(http: httpx.Client, url: str, dest: Path, retries: int = 3) -> int:
    """Baixa em streaming para `dest` e devolve o tamanho em bytes. Falha explícita."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error = ""
    for attempt in range(retries):
        try:
            with http.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code} em {url}")
                with dest.open("wb") as handle:
                    for chunk in resp.iter_bytes(1 << 20):
                        handle.write(chunk)
            return dest.stat().st_size
        except (httpx.TransportError, RuntimeError) as exc:
            last_error = str(exc)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"download falhou: {last_error}")


def checksum_ok(zip_path: Path, checksum_path: Path) -> bool:
    """RF-ING-06 CA-06.2: o arquivo confere com o `.CHECKSUM` publicado ao lado?"""
    expected = checksum_path.read_text(encoding="utf-8").split()[0].lower()
    digest = hashlib.sha256()
    with zip_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def per_second(zip_path: Path, out_path: Path) -> dict[str, int]:
    """Série por segundo (min, max, último, n) de um dia de negócios agregados."""
    tmp_dir = zip_path.parent / "_tmp"
    tmp_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        name = archive.namelist()[0]
        csv_bytes = archive.getinfo(name).file_size
        with archive.open(name) as handle:
            has_header = handle.readline().startswith(b"agg_trade_id")
        archive.extract(name, tmp_dir)
    csv_path = tmp_dir / name
    try:
        lazy = pl.scan_csv(
            csv_path,
            has_header=has_header,
            new_columns=None if has_header else CSV_COLUMNS,
        ).select(
            pl.col("agg_trade_id").cast(pl.Int64),
            pl.col("price").cast(pl.Float64),
            (pl.col("transact_time").cast(pl.Int64) // 1000).alias("sec"),
        )
        trades = int(lazy.select(pl.len()).collect().item())
        series = (
            lazy.sort("agg_trade_id")
            .group_by("sec", maintain_order=True)
            .agg(
                pl.col("price").min().alias("min"),
                pl.col("price").max().alias("max"),
                pl.col("price").last().alias("last"),
                pl.len().alias("n"),
            )
            .sort("sec")
            .collect()
        )
        series.write_parquet(out_path)
    finally:
        csv_path.unlink(missing_ok=True)
    return {
        "csv_bytes": csv_bytes,
        "trades": trades,
        "seconds_with_trade": series.height,
        "series_bytes": out_path.stat().st_size,
    }


def fetch_proxy_files(ctx: Ctx, days: list[str]) -> list[dict[str, Any]]:
    log = setup_logging()
    http = httpx.Client(timeout=120.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    files: list[dict[str, Any]] = []
    progress = Progress(ctx, f"{STEP} download", len(days) * len(UNIVERSE))
    for coin in UNIVERSE:
        symbol = BINANCE_SYMBOL[coin]
        for day in days:
            stem = f"{symbol}-aggTrades-{day}"
            zip_path = ctx.path("binance", symbol, f"{stem}.zip")
            sum_path = ctx.path("binance", symbol, f"{stem}.zip.CHECKSUM")
            series_path = ctx.path("binance", symbol, f"{stem}.sec.parquet")
            meta_path = ctx.path("binance", symbol, f"{stem}.json")
            if meta_path.exists():
                files.append(read_json(meta_path))
                progress.tick(f"{stem} (cache)")
                continue
            url = f"{BINANCE_BASE}/{symbol}/{stem}.zip"
            t0 = time.monotonic()
            size = download(http, url, zip_path)
            download(http, url + ".CHECKSUM", sum_path)
            elapsed = time.monotonic() - t0
            ok = checksum_ok(zip_path, sum_path)
            if not ok:
                log.error("checksum divergente", arquivo=stem)
            info = per_second(zip_path, series_path)
            record = {
                "coin": coin,
                "symbol": symbol,
                "day": day,
                "url": url,
                "zip_bytes": size,
                "download_s": round(elapsed, 1),
                "checksum_ok": ok,
                **info,
            }
            write_json(meta_path, record)
            files.append(record)
            progress.tick(f"{stem} {size / 1e6:.1f} MB")
    return files


def deviation_stats(
    fills: pl.DataFrame, series: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Fills com a diferença em bps contra o proxy do mesmo segundo."""
    joined = fills.join(series, on="sec", how="left")
    matched = joined.filter(pl.col("last").is_not_null()).with_columns(
        ((pl.col("px") - pl.col("last")) / pl.col("last") * 10_000).alias("bps_last"),
        (
            (pl.col("px") - (pl.col("min") + pl.col("max")) / 2)
            / ((pl.col("min") + pl.col("max")) / 2)
            * 10_000
        ).alias("bps_mid"),
    )
    return matched, {"fills": fills.height, "matched": matched.height}


def summarise(values: list[float], day_median: float | None = None) -> dict[str, float]:
    """Mediana e p95 do módulo; com `day_median`, também o p95 do desvio dela."""
    out = {
        "median": percentile(values, 50),
        "p95_abs": percentile([abs(v) for v in values], 95),
    }
    if day_median is not None:
        out["p95_abs_dev_from_day_median"] = percentile([abs(v - day_median) for v in values], 95)
    return out


def run(ctx: Ctx) -> dict[str, Any]:
    log = setup_logging()
    days = sample_days(ctx.n_days)
    log.info("dias sorteados (RF-VER-03)", days=days, seed=SEED)
    files = fetch_proxy_files(ctx, days)

    v02_path = ctx.path("results", "v02.json")
    if not v02_path.exists():
        result: dict[str, Any] = {
            "step": STEP,
            "days": days,
            "proxy_files": files,
            "criteria": {
                "RF-VER-03 CA-03.1": criterion(
                    "não medido", {}, "mediana e p95 em bps, por ativo e por dia", "falta v02"
                ),
                "RF-VER-03 CA-03.2": criterion(
                    "não medido", {}, "p95 do desvio absoluto > 10 bps: proxy inválido", "falta v02"
                ),
            },
        }
        write_json(ctx.path("results", "v03.json"), result)
        return result

    wallets: list[str] = read_json(v02_path)["sampling"]["chosen"]
    rows: list[dict[str, Any]] = []
    window_totals: dict[str, int] = dict.fromkeys(UNIVERSE, 0)
    for address in wallets:
        cache = ctx.path("fills", f"{address}.json")
        if not cache.exists():
            continue
        for fill in read_json(cache)["fills"]:
            if fill["coin"] in UNIVERSE:
                window_totals[fill["coin"]] += 1
            if fill["coin"] in UNIVERSE and day_of(int(fill["time"])) in days:
                rows.append(
                    {
                        "coin": fill["coin"],
                        "day": day_of(int(fill["time"])),
                        "sec": int(fill["time"]) // 1000,
                        "px": float(fill["px"]),
                    }
                )
    fills_df = pl.DataFrame(
        rows, schema={"coin": pl.String, "day": pl.String, "sec": pl.Int64, "px": pl.Float64}
    )

    per_coin: dict[str, Any] = {}
    for coin in UNIVERSE:
        symbol = BINANCE_SYMBOL[coin]
        day_rows: list[dict[str, Any]] = []
        pooled_last: list[float] = []
        pooled_dev: list[float] = []
        pooled_mid_dev: list[float] = []
        n_fills = n_matched = 0
        for day in days:
            series = pl.read_parquet(
                ctx.path("binance", symbol, f"{symbol}-aggTrades-{day}.sec.parquet")
            )
            day_fills = fills_df.filter((pl.col("coin") == coin) & (pl.col("day") == day))
            matched, counts = deviation_stats(day_fills, series)
            n_fills += counts["fills"]
            n_matched += counts["matched"]
            entry: dict[str, Any] = {
                "day": day,
                **counts,
                "no_proxy_second": counts["fills"] - counts["matched"],
            }
            if counts["matched"]:
                last = matched["bps_last"].to_list()
                mid = matched["bps_mid"].to_list()
                stats_last = summarise(last)
                stats_mid = summarise(mid)
                entry["last"] = summarise(last, stats_last["median"])
                entry["mid"] = summarise(mid, stats_mid["median"])
                pooled_last.extend(last)
                pooled_dev.extend(abs(v - stats_last["median"]) for v in last)
                pooled_mid_dev.extend(abs(v - stats_mid["median"]) for v in mid)
            day_rows.append(entry)
        per_coin[coin] = {
            "fills": n_fills,
            "matched": n_matched,
            "days": day_rows,
            "pooled_p95_abs_dev_last": percentile(pooled_dev, 95) if pooled_dev else None,
            "pooled_p95_abs_dev_mid": percentile(pooled_mid_dev, 95) if pooled_mid_dev else None,
            "pooled_median_last": percentile(pooled_last, 50) if pooled_last else None,
            "days_over_threshold_last": [
                d["day"]
                for d in day_rows
                if "last" in d and d["last"]["p95_abs_dev_from_day_median"] > INVALID_ABOVE_BPS
            ],
        }

    short = {c: v["fills"] for c, v in per_coin.items() if v["fills"] < MIN_FILLS_PER_ASSET}
    if all(v["fills"] == 0 for v in per_coin.values()):
        c031 = criterion(
            "não medido", {"per_coin": per_coin}, "ao menos 10.000 fills por ativo", "sem fills"
        )
    else:
        c031 = criterion(
            "ok" if not short else "reprova",
            {
                "per_coin": {
                    c: {"fills": v["fills"], "matched": v["matched"]} for c, v in per_coin.items()
                }
            },
            "ao menos 10.000 fills de líderes por ativo; mediana e p95 em bps por ativo e por dia",
            ""
            if not short
            else "pré-condição não atendida (menos de 10.000 fills): "
            + ", ".join(f"{c}={n}" for c, n in short.items())
            + "; medidas parciais reportadas abaixo",
        )

    verdicts: dict[str, str] = {}
    invalid: list[str] = []
    for coin, v in per_coin.items():
        stat = v["pooled_p95_abs_dev_last"]
        if stat is None:
            verdicts[coin] = "não medido"
        elif stat > INVALID_ABOVE_BPS:
            verdicts[coin] = "proxy inválido"
            invalid.append(coin)
        else:
            verdicts[coin] = "ok"
    insufficient = bool(short)
    if all(x == "não medido" for x in verdicts.values()) or insufficient:
        status032 = "não medido"
    else:
        status032 = "a emendar" if invalid else "ok"
    notes = []
    if insufficient:
        notes.append(
            "amostra insuficiente (menos de 10.000 fills por ativo, ver CA-03.1): os valores são "
            "indicativos, não uma validação"
        )
    if invalid:
        notes.append("ativos inválidos: " + ", ".join(invalid))
    c032 = criterion(
        status032,
        {
            "per_coin": {
                c: {
                    "verdict": verdicts[c],
                    "fills": v["fills"],
                    "pooled_p95_abs_dev_last_bps": v["pooled_p95_abs_dev_last"],
                    "pooled_p95_abs_dev_mid_bps": v["pooled_p95_abs_dev_mid"],
                    "days_over_threshold_last": v["days_over_threshold_last"],
                }
                for c, v in per_coin.items()
            },
        },
        "p95 do desvio absoluto em relação à mediana do dia > 10 bps: 'proxy inválido' (sai "
        "da Rota A)",
        "; ".join(notes),
    )

    result = {
        "step": STEP,
        "seed": SEED,
        "days": days,
        "window_start": day_of(WINDOW_START_MS),
        "wallets_used": len(wallets),
        "proxy_files": files,
        "per_coin": per_coin,
        "window_fills_in_sample": window_totals,
        "criteria": {"RF-VER-03 CA-03.1": c031, "RF-VER-03 CA-03.2": c032},
    }
    write_json(ctx.path("results", "v03.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    run(make_ctx(args.smoke))


if __name__ == "__main__":
    main()
