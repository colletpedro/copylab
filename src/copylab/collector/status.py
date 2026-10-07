"""Status do coletor (design §3.4; RF-COL-02 CA-02.3, RF-COL-03 CA-03.2, RF-COL-04 CA-04.2;
T-013).

Lê os arquivos, sem falar com o processo do gravador. Para cada ativo:

- **Cobertura**: a fração do tempo sem lacuna desde a primeira mensagem do livro gravada,
  até ``agora``. As lacunas são as da tabela ``gaps`` (dias já compactados), as que a mesma
  regra encontra nos segmentos ainda não compactados, inclusive o que está em escrita, e
  o silêncio desde a última mensagem do livro, se já passou do limite: é uma lacuna em
  curso.
- **Latência de recebimento**: recebimento menos o instante da corretora, nos negócios,
  com mediana, p95 e p99 por posto mais próximo, sem interpolação. Mistura rede e
  diferença entre os relógios das duas máquinas.

E para o coletor inteiro, a **projeção de disco**: os bytes que segmentos e tabelas ocupam
hoje, divididos pelo tempo desde o início da gravação e multiplicados pelo horizonte, contra
o orçamento. É uma extrapolação linear: antes da primeira compactação, ela mede o tamanho
dos segmentos gzip, e não o das tabelas.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from copylab.collector.compact import (
    CHANNEL_TABLES,
    GAPS_TABLE,
    BookPoint,
    Gap,
    find_gaps,
    rows_from_segments,
)
from copylab.storage import ParquetStore
from copylab.storage.segments import EVENTS, SegmentStore
from copylab.timeutil import MS_PER_DAY, Ms

__all__ = ["AssetStatus", "CollectorStatus", "Latency", "collector_status", "nearest_rank"]


@dataclass(frozen=True, slots=True)
class Latency:
    count: int
    p50_ms: int
    p95_ms: int
    p99_ms: int


@dataclass(frozen=True, slots=True)
class AssetStatus:
    coin: str
    since_ms: int | None
    last_book_ms: int | None
    gap_count: int
    gap_ms: int
    covered_fraction: float | None
    latency: Latency | None


@dataclass(frozen=True, slots=True)
class CollectorStatus:
    now_ms: int
    started_ms: int | None
    assets: tuple[AssetStatus, ...]
    latency: Latency | None
    disk_bytes: int
    projected_bytes: int | None
    projection_days: int
    budget_bytes: int

    @property
    def within_budget(self) -> bool | None:
        return None if self.projected_bytes is None else self.projected_bytes <= self.budget_bytes


def nearest_rank(sorted_values: Sequence[int], p: float) -> int:
    """Percentil ``p`` (0 < p ≤ 1) por posto mais próximo: o menor valor com ao menos uma
    fração ``p`` dos valores nele ou abaixo dele."""
    return sorted_values[max(1, math.ceil(p * len(sorted_values))) - 1]


def _latency(values: Sequence[int]) -> Latency | None:
    if not values:
        return None
    ordered = sorted(values)
    return Latency(
        len(ordered),
        nearest_rank(ordered, 0.50),
        nearest_rank(ordered, 0.95),
        nearest_rank(ordered, 0.99),
    )


class _Reader:
    def __init__(self, segments: SegmentStore, tables: ParquetStore) -> None:
        self.segments = segments
        self.tables = tables
        self._refs = segments.segments(include_open=True)

    def days(self, table: str, coin: str) -> list[int]:
        return sorted(int(day) for owner, day in self.tables.partitions(table) if owner == coin)

    def compacted(self, table: str, coin: str) -> pl.DataFrame | None:
        frames = [self.tables.read(table, (coin, str(day))) for day in self.days(table, coin)]
        return pl.concat(frames) if frames else None

    def edge_row(self, table: str, coin: str, last: bool) -> dict[str, Any] | None:
        days = self.days(table, coin)
        for day in reversed(days) if last else days:
            frame = self.tables.read(table, (coin, str(day)))
            if frame.height:
                return frame.row(-1 if last else 0, named=True)
        return None

    def recent(self, channel: str, coin: str, live_conn: int | None) -> pl.DataFrame:
        refs = [r for r in self._refs if (r.coin, r.channel) == (coin, channel)]
        frame, _, _ = rows_from_segments(self.segments, refs, channel, coin, live_conn)
        return frame

    def started(self) -> int | None:
        """Instante do primeiro registro de eventos: os segmentos de eventos não são apagados."""
        for ref in self._refs:
            if (ref.coin, ref.channel) == EVENTS:
                for record in self.segments.read(ref):
                    return record.recv_ms
        return None


def _asset(
    reader: _Reader, coin: str, now_ms: int, max_silence_ms: int
) -> tuple[AssetStatus, list[int]]:
    first = reader.edge_row("book", coin, last=False)
    last = reader.edge_row("book", coin, last=True)
    recent = reader.recent("book", coin, last["conn_ms"] if last else None)

    gaps: list[Gap] = []
    if reader.tables.exists(GAPS_TABLE, (coin,)):
        gaps = [Gap(*row) for row in reader.tables.read(GAPS_TABLE, (coin,)).rows()]
    points = [BookPoint(*row) for row in recent.select("time_ms", "recv_ms", "conn_ms").rows()]
    previous = BookPoint(last["time_ms"], last["recv_ms"], last["conn_ms"]) if last else None
    gaps.extend(find_gaps(points, previous, max_silence_ms))

    since = first["time_ms"] if first else (points[0].time_ms if points else None)
    newest = points[-1].time_ms if points else (last["time_ms"] if last else None)
    if newest is not None and now_ms - newest > max_silence_ms:
        gaps.append(Gap(newest, now_ms, "silence"))

    covered = None
    gap_ms = 0
    if since is not None and now_ms > since:
        gap_ms = sum(max(0, min(g.end_ms, now_ms) - max(g.start_ms, since)) for g in gaps)
        covered = 1 - gap_ms / (now_ms - since)

    trades_last = reader.edge_row("trades", coin, last=True)
    trades = [
        frame
        for frame in (
            reader.compacted("trades", coin),
            reader.recent("trades", coin, trades_last["conn_ms"] if trades_last else None),
        )
        if frame is not None and frame.height
    ]
    delays: list[int] = []
    for frame in trades:
        delays.extend((frame["recv_ms"] - frame["time_ms"]).to_list())

    status = AssetStatus(coin, since, newest, len(gaps), gap_ms, covered, _latency(delays))
    return status, delays


def collector_status(
    segments: SegmentStore,
    tables: ParquetStore,
    coins: Sequence[str],
    *,
    now_ms: Ms,
    max_silence_ms: int,
    projection_days: int,
    budget_bytes: int,
) -> CollectorStatus:
    reader = _Reader(segments, tables)
    assets: list[AssetStatus] = []
    every_delay: list[int] = []
    for coin in coins:
        status, delays = _asset(reader, coin, now_ms, max_silence_ms)
        assets.append(status)
        every_delay.extend(delays)

    used = segments.disk_bytes() + sum(
        tables.disk_bytes(table) for table in (*CHANNEL_TABLES, GAPS_TABLE)
    )
    started = reader.started()
    projected = None
    if started is not None and now_ms > started:
        projected = round(used * projection_days * MS_PER_DAY / (now_ms - started))
    return CollectorStatus(
        now_ms=now_ms,
        started_ms=started,
        assets=tuple(assets),
        latency=_latency(every_delay),
        disk_bytes=used,
        projected_bytes=projected,
        projection_days=projection_days,
        budget_bytes=budget_bytes,
    )
