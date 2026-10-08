"""Compactação dos segmentos do coletor em tabelas (design §3.4; RF-COL-02; T-012).

Etapa separada do gravador. Converte os segmentos fechados de um dia UTC de recebimento
nas tabelas ``bbo``, ``book`` e ``trades``, partição ``(ativo, dia)``, confere as
contagens contra os segmentos e só então os apaga. A partir daí a tabela é o registro.
Os segmentos de eventos (conexões, desconexões, ``pong``) não viram tabela e não são
apagados: são pequenos e são a única memória dos motivos de cada queda.

**Primeira mensagem de cada assinatura.** É um retrato do passado e é descartada. Ela é a
primeira mensagem de um ativo e canal trazida por uma conexão. Uma conexão que atravessa
a meia-noite continua no dia seguinte: a última linha gravada do dia anterior diz qual
conexão estava viva.

**Lacunas** (§3.4), no relógio da corretora: entre duas mensagens consecutivas do livro
rápido do mesmo ativo, já sem as descartadas, há lacuna se a conexão mudou entre elas
(desconexão) ou se o instante da corretora andou mais que o silêncio máximo do arquivo de
parâmetros. A lacuna vai do instante da última mensagem antes dela ao da primeira depois.
Negócios e melhor compra e venda não entram na regra.

Colunas além das do design §3.2: ``conn_ms``, o instante de abertura da conexão que trouxe
a linha. Sem ela, a desconexão entre duas mensagens deixaria de ser reconhecível depois
que os segmentos são apagados.
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import polars as pl

from copylab.exceptions import DataError
from copylab.logging import get_logger
from copylab.storage import ParquetStore, Span
from copylab.storage.segments import Record, SegmentRef, SegmentStore
from copylab.storage.tables import BOOK_LEVELS, COLLECTOR_DAY_TABLES, GAPS, SCHEMAS
from copylab.timeutil import Ms, day_start, iso, utc_day

__all__ = [
    "BOOK_LEVELS",
    "CHANNEL_TABLES",
    "GAPS_TABLE",
    "BookPoint",
    "Compactor",
    "DayReport",
    "Gap",
    "find_gaps",
    "rows_from_segments",
]

log = get_logger(__name__)

CHANNEL_TABLES: Final = COLLECTOR_DAY_TABLES
GAPS_TABLE: Final = GAPS
#: Trecho declarado na escrita da tabela de lacunas: ela é reescrita inteira a cada vez.
_ALL_TIME: Final = Span(Ms(-(2**62)), Ms(2**62))

Row = dict[str, Any]


@dataclass(frozen=True, slots=True)
class BookPoint:
    """O que a regra de lacuna precisa de uma mensagem do livro."""

    time_ms: int
    recv_ms: int
    conn_ms: int


@dataclass(frozen=True, slots=True, order=True)
class Gap:
    start_ms: int
    end_ms: int
    reason: str


def find_gaps(
    points: Sequence[BookPoint], previous: BookPoint | None, max_silence_ms: int
) -> list[Gap]:
    """Lacunas entre mensagens consecutivas do livro, em ordem de recebimento.

    ``previous`` é a última mensagem antes de ``points`` (do dia anterior), ou ``None``.
    Silêncio de até ``max_silence_ms`` não é lacuna; acima disso, é (design §3.6).
    """
    gaps: list[Gap] = []
    last = previous
    for point in points:
        if last is not None:
            if point.conn_ms != last.conn_ms:
                gaps.append(Gap(last.time_ms, point.time_ms, "disconnect"))
            elif point.time_ms - last.time_ms > max_silence_ms:
                gaps.append(Gap(last.time_ms, point.time_ms, "silence"))
        last = point
    return gaps


# ─── Leitura das mensagens ───────────────────────────────────────────────────


def _number(value: object, what: str) -> float:
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        raise ValueError(f"{what} não é número: {value!r}")
    return float(value)


def _int(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{what} não é inteiro: {value!r}")
    return value


def _level(level: object, what: str) -> tuple[float | None, float | None]:
    if level is None:
        return None, None
    if not isinstance(level, dict):
        raise ValueError(f"{what} não é nível: {level!r}")
    return _number(level.get("px"), f"{what}.px"), _number(level.get("sz"), f"{what}.sz")


def _bbo_rows(data: dict[str, Any]) -> list[Row]:
    bid, ask = data["bbo"]
    bid_px, bid_sz = _level(bid, "bbo[0]")
    ask_px, ask_sz = _level(ask, "bbo[1]")
    return [
        {
            "time_ms": _int(data["time"], "time"),
            "bid_px": bid_px,
            "bid_sz": bid_sz,
            "ask_px": ask_px,
            "ask_sz": ask_sz,
        }
    ]


def _book_rows(data: dict[str, Any]) -> list[Row]:
    bids, asks = data["levels"]
    row: Row = {"time_ms": _int(data["time"], "time")}
    for side, levels in (("bid", bids), ("ask", asks)):
        if not isinstance(levels, list) or len(levels) > BOOK_LEVELS:
            raise ValueError(f"lado {side} com {levels!r} níveis")
        for index in range(BOOK_LEVELS):
            level = levels[index] if index < len(levels) else None
            px, sz = _level(level, f"{side}[{index}]")
            row[f"{side}_px_{index + 1}"] = px
            row[f"{side}_sz_{index + 1}"] = sz
    return [row]


def _trade_rows(data: list[dict[str, Any]]) -> list[Row]:
    rows = []
    for trade in data:
        buyer, seller = trade["users"]
        rows.append(
            {
                "time_ms": _int(trade["time"], "time"),
                "px": _number(trade["px"], "px"),
                "sz": _number(trade["sz"], "sz"),
                "side": str(trade["side"]),
                "buyer": str(buyer),
                "seller": str(seller),
                "tid": _int(trade["tid"], "tid"),
            }
        )
    return rows


def _parse(channel: str, coin: str, record: Record, where: SegmentRef) -> list[Row]:
    try:
        message = json.loads(record.raw)
        data = message["data"]
        items = data if channel == "trades" else [data]
        if any(item["coin"] != coin for item in items):
            raise ValueError(f"mensagem de outro ativo no segmento de {coin}")
        rows = (
            _bbo_rows(data)
            if channel == "bbo"
            else _book_rows(data)
            if channel == "book"
            else _trade_rows(data)
        )
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise DataError(
            f"Mensagem ilegível em {where.path} (recebida em {iso(record.recv_ms)}): {exc}"
        ) from exc
    for row in rows:
        row["recv_ms"] = record.recv_ms
        row["conn_ms"] = record.conn_ms
    return rows


def rows_from_segments(
    store: SegmentStore,
    refs: Sequence[SegmentRef],
    channel: str,
    coin: str,
    live_conn: int | None,
) -> tuple[pl.DataFrame, int, int]:
    """Linhas de ``refs``, sem a primeira mensagem de cada assinatura.

    ``live_conn`` é a conexão da última linha gravada antes destes segmentos: a mensagem
    seguinte dela não é a primeira da assinatura. Devolve a tabela, o número de mensagens
    lidas e o de mensagens descartadas.
    """
    seen = {live_conn} if live_conn is not None else set()
    rows: list[Row] = []
    messages = dropped = 0
    for ref in refs:
        for record in store.read(ref):
            messages += 1
            if record.conn_ms not in seen:
                seen.add(record.conn_ms)
                dropped += 1
                continue
            rows.extend(_parse(channel, coin, record, ref))
    return pl.DataFrame(rows, schema=SCHEMAS[channel], orient="row"), messages, dropped


# ─── Compactação de um dia ───────────────────────────────────────────────────


@dataclass
class DayReport:
    day: int
    rows: dict[tuple[str, str], int] = field(default_factory=dict)
    dropped_first: dict[tuple[str, str], int] = field(default_factory=dict)
    gaps: dict[str, list[Gap]] = field(default_factory=dict)
    deleted_segments: int = 0


class Compactor:
    """Converte segmentos fechados em tabelas. Só lê segmentos de dias encerrados."""

    def __init__(self, segments: SegmentStore, tables: ParquetStore, max_silence_ms: int) -> None:
        self._segments = segments
        self._tables = tables
        self._max_silence_ms = max_silence_ms

    def pending_days(self, today: int) -> list[int]:
        """Dias anteriores a ``today`` com segmentos fechados de livro, bbo ou negócios.

        Um dia com segmento ainda aberto (deixado por uma queda) fica de fora: o gravador
        o recupera ao reiniciar.
        """
        closed: set[int] = set()
        opened: set[int] = set()
        for ref in self._segments.segments(include_open=True):
            if ref.channel in CHANNEL_TABLES:
                (closed if ref.closed else opened).add(utc_day(ref.hour_ms))
        for day in sorted(opened & closed):
            log.warning("collector.compact.skipped_open_segment", day=iso(day_start(day)))
        return sorted(d for d in closed - opened if d < today)

    def last_row(self, table: str, coin: str, before_day: int) -> dict[str, Any] | None:
        """Última linha gravada de ``coin`` em ``table`` antes do dia ``before_day``."""
        days = [
            int(day)
            for owner, day in self._tables.partitions(table)
            if owner == coin and int(day) < before_day
        ]
        for day in sorted(days, reverse=True):
            frame = self._tables.read(table, (coin, str(day)))
            if frame.height:
                return frame.row(-1, named=True)
        return None

    def _refs(self, day: int) -> Iterator[tuple[str, str, list[SegmentRef]]]:
        grouped: dict[tuple[str, str], list[SegmentRef]] = {}
        for ref in self._segments.segments():
            if ref.channel in CHANNEL_TABLES and utc_day(ref.hour_ms) == day:
                grouped.setdefault((ref.coin, ref.channel), []).append(ref)
        for (coin, channel), refs in sorted(grouped.items()):
            yield coin, channel, refs

    def compact_day(self, day: int) -> DayReport:
        """Compacta o dia ``day`` e apaga os segmentos dele, se as contagens baterem.

        Idempotente: rodar de novo sobre um dia cujos segmentos sobreviveram (queda antes
        de apagar) regrava as mesmas linhas.

        Raises:
            DataError: mensagem ilegível ou contagem divergente. Nada é apagado.
        """
        report = DayReport(day)
        span = Span(day_start(day), day_start(day + 1))
        written: list[SegmentRef] = []
        for coin, channel, refs in self._refs(day):
            previous = self.last_row(channel, coin, day)
            live = previous["conn_ms"] if previous else None
            frame, messages, dropped = rows_from_segments(self._segments, refs, channel, coin, live)
            self._tables.write(channel, (coin, str(day)), frame, span=span, instant="recv_ms")
            stored = self._tables.read(channel, (coin, str(day))).height
            if stored != frame.height:
                raise DataError(
                    f"{channel} de {coin} em {iso(day_start(day))}: {frame.height} linhas lidas "
                    f"dos segmentos, {stored} gravadas. Segmentos mantidos."
                )
            if channel != "trades" and frame.height != messages - dropped:
                raise DataError(
                    f"{channel} de {coin}: {messages} mensagens, {dropped} descartadas, "
                    f"{frame.height} linhas. Segmentos mantidos."
                )
            report.rows[(coin, channel)] = frame.height
            report.dropped_first[(coin, channel)] = dropped
            written.extend(refs)
            if channel == "book":
                report.gaps[coin] = self._record_gaps(coin, frame, previous)

        for ref in written:
            self._segments.delete(ref)
        report.deleted_segments = len(written)
        log.info(
            "collector.compact.day",
            day=iso(day_start(day)),
            tables=len(report.rows),
            segments_deleted=report.deleted_segments,
            gaps=sum(len(g) for g in report.gaps.values()),
        )
        return report

    def _record_gaps(
        self, coin: str, book: pl.DataFrame, previous: dict[str, Any] | None
    ) -> list[Gap]:
        before = (
            BookPoint(previous["time_ms"], previous["recv_ms"], previous["conn_ms"])
            if previous
            else None
        )
        points = [
            BookPoint(r["time_ms"], r["recv_ms"], r["conn_ms"])
            for r in book.select("time_ms", "recv_ms", "conn_ms").iter_rows(named=True)
        ]
        found = find_gaps(points, before, self._max_silence_ms)
        existing: set[Gap] = set()
        if self._tables.exists(GAPS_TABLE, (coin,)):
            existing = {Gap(*row) for row in self._tables.read(GAPS_TABLE, (coin,)).rows()}
        merged = sorted(existing | set(found))
        frame = pl.DataFrame(
            [(g.start_ms, g.end_ms, g.reason) for g in merged],
            schema=SCHEMAS[GAPS_TABLE],
            orient="row",
        )
        self._tables.write(GAPS_TABLE, (coin,), frame, span=_ALL_TIME, instant="start_ms")
        return found
