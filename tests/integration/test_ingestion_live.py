"""Ingestão contra a API real e a Binance (Bloco B).

Fora da suíte default: precisa de rede. Roda com `make test-integration`. Somente leitura:
``POST /info``, o ``GET`` do leaderboard e os arquivos públicos da Binance.

Faz, em escala pequena, o que o marco M-B faz inteiro: snapshot do leaderboard e dos lotes,
bloco 0 do pool, fills das 5 primeiras carteiras do bloco na janela de seleção da Rota A,
um dia de proxy de BTC de julho e um dia de funding de BTC, este só para conferir o formato
real da resposta. Nada de setembro: a janela termina no corte, e o teste confere que nenhuma
consulta passou dele.
"""

from pathlib import Path
from typing import Any

import pytest

from copylab import clock
from copylab.config import Settings
from copylab.ingestion.budget import WeightBudget
from copylab.ingestion.fills import ingest_fills
from copylab.ingestion.funding import ingest_funding
from copylab.ingestion.provider import HyperliquidInfo
from copylab.ingestion.proxy import BinanceDaily, ingest_proxy
from copylab.ingestion.snapshots import ingest_snapshot
from copylab.logging import get_logger
from copylab.params import DEFAULT_PATH, load_params
from copylab.selection.pool import pool_block
from copylab.storage import ParquetRepository, ParquetStore, Span
from copylab.timeutil import MS_PER_DAY, Ms, iso, parse_utc_date

REPO_ROOT = Path(__file__).resolve().parents[2]
WALLETS = 5
PROXY_DAY = "2026-07-15"

log = get_logger(__name__)


class Recording(HyperliquidInfo):
    """O provedor real, guardando o fim de cada janela pedida."""

    ends: list[int]

    def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
        self.ends.append(end)
        return super().user_fills(address, start, end)

    def funding_history(self, coin: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
        self.ends.append(end)
        return super().funding_history(coin, start, end)


@pytest.mark.integration
def test_five_wallets_of_block_zero_and_one_day_of_btc_proxy(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    params = load_params(REPO_ROOT / DEFAULT_PATH)
    store = ParquetStore(tmp_path)
    repo = ParquetRepository(store)
    budget = WeightBudget(settings.weight_limit_per_minute, clock.monotonic, clock.sleep)
    provider = Recording(
        budget,
        http=HyperliquidInfo.client(settings.api_timeout_seconds),
        sleep=clock.sleep,
        max_retries=settings.api_max_retries,
        backoff_initial_s=settings.api_backoff_initial_seconds,
        backoff_max_s=settings.api_backoff_max_seconds,
    )
    provider.ends = []
    began = clock.monotonic()

    snapshot = ingest_snapshot(provider, store, clock.now())
    t_snapshot = clock.monotonic() - began
    perps = frozenset(repo.meta(snapshot.snapshot_ms).get_column("coin").to_list())
    block = pool_block(
        repo.leaderboard(snapshot.snapshot_ms),
        params.filters.f2_min_account_value_usd,
        0,
        params.pool.block_size,
        params.pool.seed,
    )
    assert len(block) == params.pool.block_size
    window = Span(params.route_a.selection_start, params.route_a.selection_end)

    t0 = clock.monotonic()
    report = ingest_fills(
        provider, store, block[:WALLETS], window, perps,
        params.ingestion.max_fills_per_wallet, clock.now,
    )  # fmt: skip
    t_fills = clock.monotonic() - t0

    t0 = clock.monotonic()
    day = parse_utc_date(PROXY_DAY)
    archive = BinanceDaily(
        HyperliquidInfo.client(settings.api_timeout_seconds),
        sleep=clock.sleep,
        max_retries=settings.api_max_retries,
        backoff_initial_s=settings.api_backoff_initial_seconds,
        backoff_max_s=settings.api_backoff_max_seconds,
    )
    one_day = Span(day, Ms(day + MS_PER_DAY))
    proxy = ingest_proxy(archive, store, "BTC", params.binance.symbol("BTC"), one_day)
    t_proxy = clock.monotonic() - t0
    funding = ingest_funding(provider, store, "BTC", one_day)

    assert not report.failed, [w.error for w in report.failed]
    assert proxy.complete
    assert funding.hours == 24
    assert max(provider.ends) <= params.route_a.cutoff  # nada de setembro
    assert budget.peak <= settings.weight_limit_per_minute
    seconds = repo.proxy("BTC", one_day.start, one_day.end)
    assert seconds.height > 10_000

    kinds: dict[str, int] = {}
    for wallet in report.wallets:
        frame = repo.fills(wallet.address, window.start, window.end)
        for kind, n in frame.group_by("kind").len().iter_rows():
            kinds[kind] = kinds.get(kind, 0) + n
    log.info(
        "ingestion.live_test",
        snapshot_at=iso(snapshot.snapshot_ms),
        snapshot_mb=round(snapshot.body_bytes / 10**6, 2),
        leaderboard_wallets=snapshot.wallets,
        meta_perps=snapshot.perps,
        wallets=[(w.address, w.status, w.n_fills, w.pages) for w in report.wallets],
        fills_by_kind=kinds,
        invalid_perp_fills=sum(w.invalid_perp_fills for w in report.wallets),
        other_coins=report.other_coins,
        proxy_seconds=seconds.height,
        proxy_trades=int(seconds.get_column("n_trades").sum()),
        proxy_zip_mb=round(archive.downloaded_bytes / 10**6, 2),
        funding_hours=funding.hours,
        requests=provider.requests,
        retries=provider.retries,
        rate_limited=provider.rate_limited,
        weight=budget.total,
        weight_peak_60s=budget.peak,
        seconds_snapshot=round(t_snapshot, 1),
        seconds_fills=round(t_fills, 1),
        seconds_proxy=round(t_proxy, 1),
        seconds_total=round(clock.monotonic() - began, 1),
    )
