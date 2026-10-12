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

- **Cobertura por dia UTC** (RF-COL-05 CA-05.2): para cada dia desde o primeiro livro até
  hoje, a fração do dia sem lacuna. É o número que a medida de custo usa para escolher os
  3 primeiros dias UTC completos com ao menos 95% de cobertura. O denominador de um dia
  encerrado é o dia inteiro, e o que veio antes do primeiro livro do ativo conta como não
  coberto: um ativo que começou às 18h tem no máximo 25% no primeiro dia, e esse dia não
  entra na medida. O dia de hoje usa o tempo decorrido e vem marcado como incompleto.

**Custo da leitura.** Os dias já compactados saem das tabelas (só as colunas de que o
status precisa) e do registro de lacunas. Só os segmentos brutos que ainda existem, ou
seja, os do dia aberto e os de um dia que a compactação ainda não alcançou, são lidos, e
sem interpretar os níveis do livro: o status só precisa do instante da corretora, do de
recebimento e da conexão de cada mensagem. A latência é a de todos os negócios, mas
guardada como contagem de cada atraso, e não como lista de valores: o percentil de 45
dias de negócios não carrega 45 dias de números na memória.

E para o coletor inteiro, a **projeção de disco**: os bytes que segmentos e tabelas ocupam
hoje, divididos pelo tempo desde o início da gravação e multiplicados pelo horizonte, contra
o orçamento. É uma extrapolação linear: antes da primeira compactação, ela mede o tamanho
dos segmentos gzip, e não o das tabelas.
"""

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

import polars as pl

from copylab.collector.compact import (
    CHANNEL_TABLES,
    GAPS_TABLE,
    BookPoint,
    Gap,
    find_gaps,
)
from copylab.storage import ParquetStore
from copylab.storage.segments import EVENTS, SegmentRef, SegmentStore
from copylab.timeutil import MS_PER_DAY, Ms, day_start, utc_day

__all__ = [
    "AssetStatus",
    "CollectorStatus",
    "DayCoverage",
    "Latency",
    "collector_status",
    "nearest_rank",
]

#: O instante da corretora numa mensagem do livro ou de negócios. O livro tem um só
#: ``time`` (os níveis só têm ``px``, ``sz`` e ``n``); uma mensagem de negócios tem um por
#: negócio. Ler isto no lugar de interpretar a mensagem inteira é o que torna o status
#: barato; a compactação, que grava as tabelas, continua interpretando tudo.
_TIME: Final = re.compile(rb'"time"\s*:\s*(\d+)')
_BOOK_COLUMNS: Final = ("time_ms", "recv_ms", "conn_ms")


@dataclass(frozen=True, slots=True)
class Latency:
    count: int
    p50_ms: int
    p95_ms: int
    p99_ms: int


@dataclass(frozen=True, slots=True)
class DayCoverage:
    """Cobertura de um ativo num dia UTC, no relógio da corretora."""

    day: int
    gap_ms: int
    unrecorded_ms: int
    observed_ms: int
    complete: bool

    @property
    def covered_fraction(self) -> float:
        """Fração de ``observed_ms`` sem lacuna e depois do primeiro livro do ativo."""
        return 1 - (self.gap_ms + self.unrecorded_ms) / self.observed_ms


@dataclass(frozen=True, slots=True)
class AssetStatus:
    coin: str
    since_ms: int | None
    last_book_ms: int | None
    gap_count: int
    gap_ms: int
    covered_fraction: float | None
    latency: Latency | None
    daily: tuple[DayCoverage, ...] = ()


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


def _rank(count: int, p: float) -> int:
    """Posto (a partir de 1) do percentil ``p`` entre ``count`` valores."""
    return max(1, math.ceil(p * count))


def nearest_rank(sorted_values: Sequence[int], p: float) -> int:
    """Percentil ``p`` (0 < p ≤ 1) por posto mais próximo: o menor valor com ao menos uma
    fração ``p`` dos valores nele ou abaixo dele."""
    return sorted_values[_rank(len(sorted_values), p) - 1]


def _latency(delays: Counter[int]) -> Latency | None:
    """Mediana, p95 e p99 por posto mais próximo, de um atraso e quantas vezes ocorreu."""
    count = sum(delays.values())
    if count == 0:
        return None
    wanted = {p: _rank(count, p) for p in (0.50, 0.95, 0.99)}
    found: dict[float, int] = {}
    seen = 0
    for delay in sorted(delays):
        seen += delays[delay]
        for p, rank in wanted.items():
            if p not in found and seen >= rank:
                found[p] = delay
    return Latency(count, found[0.50], found[0.95], found[0.99])


class _Reader:
    def __init__(self, segments: SegmentStore, tables: ParquetStore) -> None:
        self.segments = segments
        self.tables = tables
        self._refs = segments.segments(include_open=True)
        self._days: dict[str, dict[str, list[int]]] = {}

    def days(self, table: str, coin: str) -> list[int]:
        """Dias com partição de ``coin`` em ``table``. A listagem da tabela é feita uma vez."""
        if table not in self._days:
            by_coin: dict[str, list[int]] = {}
            for owner, day in self.tables.partitions(table):
                by_coin.setdefault(owner, []).append(int(day))
            self._days[table] = {owner: sorted(days) for owner, days in by_coin.items()}
        return self._days[table].get(coin, [])

    def edge_row(self, table: str, coin: str, last: bool) -> BookPoint | None:
        """Primeira ou última linha de ``coin`` em ``table``: só as três colunas de tempo e
        conexão, e só a partição do dia de ponta que tem linha."""
        days = self.days(table, coin)
        for day in reversed(days) if last else days:
            frame = self.tables.read(table, (coin, str(day)), _BOOK_COLUMNS)
            if frame.height:
                return BookPoint(*frame.row(-1 if last else 0))
        return None

    def raw(self, channel: str, coin: str) -> list[SegmentRef]:
        return [r for r in self._refs if (r.coin, r.channel) == (coin, channel)]

    def book_points(self, coin: str, live_conn: int | None) -> list[BookPoint]:
        """Mensagens do livro ainda em segmento, sem a primeira de cada assinatura (a
        mesma regra da compactação), só com o que a regra de lacuna precisa."""
        seen = {live_conn} if live_conn is not None else set()
        points: list[BookPoint] = []
        for ref in self.raw("book", coin):
            for record in self.segments.read_live(ref):
                if record.conn_ms not in seen:
                    seen.add(record.conn_ms)
                    continue
                match = _TIME.search(record.raw)
                if match is not None:  # mensagem ilegível: quem a recusa é a compactação
                    points.append(BookPoint(int(match[1]), record.recv_ms, record.conn_ms))
        return points

    def trade_delays(self, coin: str) -> Counter[int]:
        """Atraso de recebimento de todos os negócios de ``coin``, como contagem."""
        delays: Counter[int] = Counter()
        for day in self.days("trades", coin):
            frame = self.tables.read("trades", (coin, str(day)), ("time_ms", "recv_ms", "conn_ms"))
            counted = frame.select((pl.col("recv_ms") - pl.col("time_ms")).alias("d"))
            for delay, n in counted.group_by("d").len().iter_rows():
                delays[delay] += n
        last = self.edge_row("trades", coin, last=True)
        seen = {last.conn_ms} if last is not None else set()
        for ref in self.raw("trades", coin):
            for record in self.segments.read_live(ref):
                if record.conn_ms not in seen:
                    seen.add(record.conn_ms)
                    continue
                for time in _TIME.findall(record.raw):
                    delays[record.recv_ms - int(time)] += 1
        return delays

    def started(self) -> int | None:
        """Instante do primeiro registro de eventos: os segmentos de eventos não são apagados."""
        for ref in self._refs:
            if (ref.coin, ref.channel) == EVENTS:
                for record in self.segments.read_live(ref):
                    return record.recv_ms
        return None


def _daily(gaps: Iterable[Gap], since: int, now_ms: int) -> tuple[DayCoverage, ...]:
    """Cobertura de cada dia UTC de ``since`` até ``now_ms``, no relógio da corretora.

    As lacunas não se sobrepõem (cada uma vai de uma mensagem à seguinte), então somar o
    pedaço de cada uma em cada dia basta.
    """
    spans = [(g.start_ms, g.end_ms) for g in gaps]
    days = []
    for day in range(utc_day(Ms(since)), utc_day(Ms(now_ms)) + 1):
        start, end = day_start(day), day_start(day + 1)
        complete = end <= now_ms
        observed = (end if complete else now_ms) - start
        if observed <= 0:
            continue
        stop = end if complete else now_ms
        gap_ms = sum(max(0, min(b, stop) - max(a, start)) for a, b in spans)
        days.append(DayCoverage(day, gap_ms, max(0, since - start), observed, complete))
    return tuple(days)


def _asset(
    reader: _Reader, coin: str, now_ms: int, max_silence_ms: int
) -> tuple[AssetStatus, Counter[int]]:
    first = reader.edge_row("book", coin, last=False)
    last = reader.edge_row("book", coin, last=True)
    points = reader.book_points(coin, last.conn_ms if last else None)

    gaps: list[Gap] = []
    if reader.tables.exists(GAPS_TABLE, (coin,)):
        gaps = [Gap(*row) for row in reader.tables.read(GAPS_TABLE, (coin,)).rows()]
    gaps.extend(find_gaps(points, last, max_silence_ms))

    since = first.time_ms if first else (points[0].time_ms if points else None)
    newest = points[-1].time_ms if points else (last.time_ms if last else None)
    if newest is not None and now_ms - newest > max_silence_ms:
        gaps.append(Gap(newest, now_ms, "silence"))

    covered = None
    gap_ms = 0
    daily: tuple[DayCoverage, ...] = ()
    if since is not None and now_ms > since:
        gap_ms = sum(max(0, min(g.end_ms, now_ms) - max(g.start_ms, since)) for g in gaps)
        covered = 1 - gap_ms / (now_ms - since)
        daily = _daily(gaps, since, now_ms)

    delays = reader.trade_delays(coin)
    status = AssetStatus(coin, since, newest, len(gaps), gap_ms, covered, _latency(delays), daily)
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
    every_delay: Counter[int] = Counter()
    for coin in coins:
        status, delays = _asset(reader, coin, now_ms, max_silence_ms)
        assets.append(status)
        every_delay.update(delays)

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
