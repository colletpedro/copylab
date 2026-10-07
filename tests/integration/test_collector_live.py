"""Coletor contra a corretora real (T-010, RF-COL-01 e RF-COL-03).

Fora da suíte default: precisa de rede e fala com a Hyperliquid. Roda com
`make test-integration`. Grava 60 segundos de BTC pelo mesmo gravador da CLI, no
WebSocket público de mainnet, e confere que os três canais chegaram e que a compactação
os lê. Somente leitura: assinaturas públicas, sem chave e sem assinatura de usuário.
"""

import asyncio
from pathlib import Path

import pytest

from copylab import clock
from copylab.collector.compact import Compactor
from copylab.collector.recorder import WS_URL, Recorder, RecorderConfig, run
from copylab.logging import get_logger
from copylab.storage import ParquetStore
from copylab.storage.segments import EVENTS, SegmentStore
from copylab.timeutil import utc_day

SECONDS = 60.0

log = get_logger(__name__)


@pytest.mark.integration
def test_sixty_seconds_of_btc_bring_all_three_channels(tmp_path: Path) -> None:
    segments = SegmentStore(tmp_path)
    config = RecorderConfig(WS_URL, ("BTC",), 5.0, 30.0, 1.0, 60.0)

    async def record() -> None:
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(SECONDS, stop.set)
        await run(config, Recorder(segments, ("BTC",), clock.now), clock.now, stop)

    started = clock.now()
    asyncio.run(record())

    counts: dict[str, int] = {}
    for ref in segments.segments():
        counts[ref.channel] = counts.get(ref.channel, 0) + sum(1 for _ in segments.read(ref))
    assert counts.get("bbo", 0) > 1, counts
    assert counts.get("book", 0) > 1, counts
    assert counts.get("trades", 0) > 1, counts
    assert counts.get(EVENTS[1], 0) >= 2, counts  # conexão e parada, e a resposta das assinaturas

    tables = ParquetStore(tmp_path)
    report = Compactor(segments, tables, max_silence_ms=10_000).compact_day(utc_day(started))
    for channel in ("bbo", "book", "trades"):
        assert report.rows[("BTC", channel)] > 0, report.rows
    trades = tables.read("trades", ("BTC", str(utc_day(started))))
    assert trades["buyer"].str.starts_with("0x").all()
    assert trades["seller"].str.starts_with("0x").all()
    latency = (trades["recv_ms"] - trades["time_ms"]).median()
    log.info(
        "collector.live_test",
        messages=counts,
        rows={f"{coin}/{channel}": n for (coin, channel), n in report.rows.items()},
        gaps={coin: len(found) for coin, found in report.gaps.items()},
        trade_latency_median_ms=latency,
    )
