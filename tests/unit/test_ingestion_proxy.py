"""Preço proxy e percurso dos ativos candidatos (T-025; RF-ING-06 CA-06.1 e CA-06.2,
RF-SEL-08 CA-08.5; design §3.3).

Os arquivos da Binance são montados em memória: um zip com um CSV de negócios agregados.
O dia é ``DAY`` = 20.635 (2026-07-01), que começa em ``D0`` = 1.782.864.000.000 ms; o
segundo ``S0`` = ``D0`` / 1.000 = 1.782.864.000.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
``copylab.ingestion.proxy`` e ``copylab.ingestion.market``:

- ``reduce_to_seconds`` sem ordenar por ``agg_trade_id``: falhou
  ``test_proxy_series_has_low_high_last_and_leaves_empty_seconds_absent``, nos dois
  formatos (o último do segundo virou o da última linha do arquivo, que está fora de ordem
  de propósito).
- ``ingest_proxy_day`` sem comparar o checksum: falhou ``test_proxy_checksum_mismatch_fails``.
- O percurso sem o laço de ``always``: falharam os três testes do percurso, inclusive
  ``test_btc_is_always_collected_and_ingested``.
- O percurso baixando inteiro também o ativo com poucos fills: falharam
  ``test_walk_downloads_candidates_and_only_checks_files_of_the_rest`` e o da falha de um
  ativo (SOL passou a pedir funding).
"""

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.ingestion.fake import FakeArchive, FakeInfo
from copylab.ingestion.market import ingest_market
from copylab.ingestion.proxy import (
    BINANCE_BASE,
    BinanceDaily,
    files_exist,
    ingest_proxy,
    ingest_proxy_day,
)
from copylab.storage import ParquetRepository, ParquetStore, Span
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms

DAY = 20_635
D0 = 1_782_864_000_000
S0 = D0 // 1_000
HEADER = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"


def csv(rows: list[tuple[int, float, int]], header: bool = True) -> bytes:
    lines = [HEADER] if header else []
    lines += [f"{i},{px},0.5,{i},{i},{t},false" for i, px, t in rows]
    return ("\n".join(lines) + "\n").encode()


def archive_bytes(content: bytes, name: str = "BTCUSDT-aggTrades-2026-07-01.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, content)
    return buffer.getvalue()


#: Segundo S0: ids 1, 2, 3 com preços 100,0, 101,5 e 100,5; o arquivo traz o id 3 antes
#: dos outros, mas o último do segundo é o de maior id, 3: low 100,0, high 101,5, last 100,5,
#: 3 negócios. Segundo S0 + 1: sem negócio, ausente. Segundo S0 + 2: id 4 a 99,0.
TRADES = [(3, 100.5, D0 + 999), (1, 100.0, D0 + 100), (2, 101.5, D0 + 900), (4, 99.0, D0 + 2_000)]
EXPECTED = [(S0, 100.0, 101.5, 100.5, 3), (S0 + 2, 99.0, 99.0, 99.0, 1)]


@pytest.mark.unit
@pytest.mark.parametrize("header", [True, False], ids=["com-cabecalho", "sem-cabecalho"])
def test_proxy_series_has_low_high_last_and_leaves_empty_seconds_absent(
    tmp_path: Path, header: bool
) -> None:
    archive = FakeArchive({("BTCUSDT", DAY): archive_bytes(csv(TRADES, header))})
    store = ParquetStore(tmp_path / "dados")
    result = ingest_proxy_day(archive, store, "BTC", "BTCUSDT", DAY)

    stored = ParquetRepository(store).proxy("BTC", Ms(D0), Ms(D0 + MS_PER_DAY))
    assert stored.rows() == EXPECTED
    assert (result.seconds, result.trades) == (2, 4)
    # O arquivo bruto foi para uma pasta temporária, que já não existe.
    (_, _, dest) = archive.downloads[0]
    assert not dest.exists() and not dest.parent.exists()


@pytest.mark.unit
def test_proxy_checksum_mismatch_fails(tmp_path: Path) -> None:
    archive = FakeArchive({("BTCUSDT", DAY): archive_bytes(csv(TRADES))}, wrong_sum=True)
    store = ParquetStore(tmp_path)
    with pytest.raises(DataError, match=r"difere do \.CHECKSUM"):
        ingest_proxy_day(archive, store, "BTC", "BTCUSDT", DAY)
    assert not store.exists("proxy", ("BTC", str(DAY)))


@pytest.mark.unit
def test_proxy_timestamps_outside_the_day_fail(tmp_path: Path) -> None:
    # Instantes em microssegundos: mil vezes maiores, caem muito depois do dia.
    micro = [(1, 100.0, (D0 + 100) * 1_000)]
    archive = FakeArchive({("BTCUSDT", DAY): archive_bytes(csv(micro))})
    with pytest.raises(DataError, match="fora do dia"):
        ingest_proxy_day(archive, ParquetStore(tmp_path), "BTC", "BTCUSDT", DAY)


@pytest.mark.unit
def test_missing_day_stops_the_asset_and_is_reported(tmp_path: Path) -> None:
    # Três dias; o segundo não existe na Binance. O primeiro é gravado, o terceiro nem é
    # pedido: o ativo já falhou na condição (i).
    files = {("SOLUSDT", DAY): archive_bytes(csv([(1, 150.0, D0 + 5)]))}
    archive = FakeArchive(files)
    store = ParquetStore(tmp_path)
    span = Span(Ms(D0), Ms(D0 + 3 * MS_PER_DAY))
    result = ingest_proxy(archive, store, "SOL", "SOLUSDT", span)
    assert (result.complete, result.missing_day, result.downloaded) == (False, DAY + 1, 1)
    assert [d for _, d, _ in archive.downloads] == [DAY, DAY + 1]
    assert files_exist(archive, "SOL", "SOLUSDT", span).missing_day == DAY + 1


@pytest.mark.unit
def test_days_already_stored_are_skipped(tmp_path: Path) -> None:
    files = {("BTCUSDT", DAY): archive_bytes(csv(TRADES))}
    store = ParquetStore(tmp_path)
    span = Span(Ms(D0), Ms(D0 + MS_PER_DAY))
    ingest_proxy(FakeArchive(files), store, "BTC", "BTCUSDT", span)
    again = FakeArchive(files)
    assert ingest_proxy(again, store, "BTC", "BTCUSDT", span).complete
    assert again.downloads == []


# ─── Cliente HTTP da Binance ─────────────────────────────────────────────────


@pytest.mark.unit
def test_binance_client_urls_404_and_retry(tmp_path: Path) -> None:
    body = archive_bytes(csv(TRADES))
    digest = hashlib.sha256(body).hexdigest()
    seen: list[str] = []
    flaky = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "ETHUSDT" in url:
            return httpx.Response(404)
        if url.endswith(".CHECKSUM"):
            return httpx.Response(200, text=f"{digest}  BTCUSDT-aggTrades-2026-07-01.zip\n")
        flaky["n"] += 1
        return httpx.Response(503) if flaky["n"] == 1 else httpx.Response(200, content=body)

    sleeps: list[float] = []
    client = BinanceDaily(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        max_retries=2,
        backoff_initial_s=1.0,
        backoff_max_s=10.0,
    )
    assert client.checksum("ETHUSDT", DAY) is None
    assert client.checksum("BTCUSDT", DAY) == digest
    dest = tmp_path / "x.zip"
    assert client.download("BTCUSDT", DAY, dest)
    assert dest.read_bytes() == body
    assert sleeps == [1.0]
    assert f"{BINANCE_BASE}/BTCUSDT/BTCUSDT-aggTrades-2026-07-01.zip" in seen


# ─── Percurso dos candidatos (design §3.3) ───────────────────────────────────


def candidate_fills(counts: dict[str, tuple[int, float]]) -> pl.DataFrame:
    """``counts[coin] = (fills, notional de cada fill)``, todos perpétuos com sz 1."""
    rows = [(c, "perp", px, 1.0) for c, (n, px) in counts.items() for _ in range(n)]
    return pl.DataFrame(
        rows,
        schema={"coin": pl.String, "kind": pl.String, "px": pl.Float64, "sz": pl.Float64},
        orient="row",
    )


def symbol(coin: str) -> str:
    return ("1000" + coin[1:] if coin.startswith("k") else coin) + "USDT"


def funding(coins: list[str], hours: int) -> dict[str, list[dict[str, Any]]]:
    return {
        c: [
            {"coin": c, "fundingRate": "0.00001", "premium": "0", "time": D0 + h * MS_PER_HOUR}
            for h in range(hours)
        ]
        for c in coins
    }


def walk_fixture() -> tuple[FakeArchive, FakeInfo, pl.DataFrame, Span]:
    # Dois dias. Notional: ETH 3 x 300 = 900, SOL 1 x 800 = 800, DOGE 2 x 350 = 700,
    # kPEPE 2 x 300 = 600, XRP 2 x 100 = 200. BTC não está entre os candidatos.
    # Mínimo de fills 2, máximo de ativos 3.
    # ETH (3 fills): baixa os dois dias, cumpre (i). 1 cumprindo.
    # SOL (1 fill): só confere os .CHECKSUM, cumpre (i). 2 cumprindo.
    # DOGE (2 fills): baixa o dia 1, falta o dia 2: não cumpre (i).
    # kPEPE (2 fills, 1000PEPEUSDT): baixa os dois, cumpre (i). 3 cumprindo: para.
    # XRP não é visitado. BTC entra sempre. Funding: ETH, kPEPE e BTC; SOL não, porque não
    # tem fills para entrar no universo (iii).
    span = Span(Ms(D0), Ms(D0 + 2 * MS_PER_DAY))
    day_file = archive_bytes(csv([(1, 10.0, D0 + 5)]))
    day2_file = archive_bytes(csv([(1, 10.0, D0 + MS_PER_DAY + 5)]))
    files: dict[tuple[str, int], bytes] = {}
    for s in ("ETHUSDT", "SOLUSDT", "1000PEPEUSDT", "XRPUSDT", "BTCUSDT"):
        files[(s, DAY)], files[(s, DAY + 1)] = day_file, day2_file
    files[("DOGEUSDT", DAY)] = day_file
    fills = candidate_fills(
        {
            "ETH": (3, 300.0),
            "SOL": (1, 800.0),
            "DOGE": (2, 350.0),
            "kPEPE": (2, 300.0),
            "XRP": (2, 100.0),
        }
    )
    info = FakeInfo(funding=funding(["ETH", "kPEPE", "BTC", "SOL"], 48))
    return FakeArchive(files), info, fills, span


@pytest.mark.unit
def test_walk_downloads_candidates_and_only_checks_files_of_the_rest(tmp_path: Path) -> None:
    archive, info, fills, span = walk_fixture()
    report = ingest_market(
        info,
        archive,
        ParquetStore(tmp_path),
        fills,
        span,
        max_assets=3,
        min_fills=2,
        symbol_of=symbol,
    )
    assert report.meeting_i == ["ETH", "SOL", "kPEPE"]
    assert report.proxied == ["ETH", "kPEPE", "BTC"]
    downloaded = {s for s, _, _ in archive.downloads}
    assert downloaded == {"ETHUSDT", "DOGEUSDT", "1000PEPEUSDT", "BTCUSDT"}
    assert ("SOLUSDT", DAY + 1) in archive.sums
    assert not any(s == "XRPUSDT" for s, _ in archive.sums)
    assert sorted(f.coin for f in report.funding) == ["BTC", "ETH", "kPEPE"]
    assert report.failures == []


@pytest.mark.unit
def test_btc_is_always_collected_and_ingested(tmp_path: Path) -> None:
    archive, info, fills, span = walk_fixture()
    store = ParquetStore(tmp_path)
    ingest_market(info, archive, store, fills, span, max_assets=3, min_fills=2, symbol_of=symbol)
    repo = ParquetRepository(store)
    assert repo.proxy("BTC", span.start, span.end).height == 2
    assert repo.funding("BTC", span.start, span.end).height == 48


@pytest.mark.unit
def test_market_failure_of_one_asset_does_not_stop_the_others(tmp_path: Path) -> None:
    archive, info, fills, span = walk_fixture()
    info = FakeInfo(funding=funding(["ETH", "BTC"], 48))  # kPEPE sem funding
    report = ingest_market(
        info,
        archive,
        ParquetStore(tmp_path),
        fills,
        span,
        max_assets=3,
        min_fills=2,
        symbol_of=symbol,
    )
    assert [what for what, _ in report.failures] == ["funding kPEPE"]
    assert sorted(f.coin for f in report.funding) == ["BTC", "ETH"]
