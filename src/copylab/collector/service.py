"""Processo do coletor: trava, recuperação, laço assíncrono e sinais de parada.

A CLI chama :func:`collect`. O laço assíncrono mora aqui porque ``asyncio`` só é
permitido no coletor (design §2.1).
"""

import asyncio
import signal

from copylab import clock
from copylab.collector.recorder import Recorder, RecorderConfig, run
from copylab.logging import get_logger
from copylab.storage.segments import SegmentStore

__all__ = ["collect"]

log = get_logger(__name__)


async def _main(config: RecorderConfig, segments: SegmentStore, duration_s: float | None) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    if duration_s is not None:
        loop.call_later(duration_s, stop.set)
    recorder = Recorder(segments, config.coins, clock.now)
    await run(config, recorder, clock.now, stop)


def collect(
    config: RecorderConfig, segments: SegmentStore, duration_s: float | None = None
) -> None:
    """Grava até receber SIGINT ou SIGTERM (ou até ``duration_s``, para teste).

    Antes de começar, pega a trava do diretório de dados e fecha os segmentos deixados
    abertos por uma queda, até o último bloco íntegro (RF-COL-04 CA-04.1).
    """
    with segments.exclusive():
        recovered = segments.recover()
        log.info(
            "collector.start",
            coins=len(config.coins),
            subscriptions=3 * len(config.coins),
            recovered_segments=len(recovered),
            url=config.url,
        )
        asyncio.run(_main(config, segments, duration_s))
        log.info("collector.stopped")
