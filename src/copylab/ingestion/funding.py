"""Funding por ativo (T-024; RF-ING-05 CA-05.1, design §3.3).

Uma taxa para cada hora cheia da janela. Cada registro é associado à hora por
arredondamento para baixo do seu instante: a corretora o carimba alguns milissegundos depois
da hora cheia (0 a 127 ms na verificação, RF-VER-05 CA-05.3). Hora sem registro, ou com
dois, é falha explícita: o simulador cobraria funding errado em silêncio.

A consulta vai em blocos de no máximo :data:`~copylab.ingestion.provider.FUNDING_PAGE_MAX`
horas, o que mantém a reserva de peso exata. Dentro de um bloco, se a resposta para antes
da última hora, a ingestão pede de novo a partir do registro seguinte ao último, até a
resposta vir vazia: o limite de registros por resposta não é documentado.
"""

from dataclasses import dataclass
from typing import Any

import polars as pl

from copylab.exceptions import DataError
from copylab.ingestion.provider import FUNDING_PAGE_MAX, InfoProvider
from copylab.logging import get_logger
from copylab.storage import ParquetStore, Span
from copylab.storage.tables import FUNDING, SCHEMAS
from copylab.timeutil import MS_PER_HOUR, Ms, hour_floor, iso

__all__ = ["FundingResult", "funding_covered", "ingest_funding"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FundingResult:
    coin: str
    hours: int
    requests: int


def _record(item: dict[str, Any], coin: str) -> tuple[int, float, float]:
    t, rate, premium = item.get("time"), item.get("fundingRate"), item.get("premium")
    if item.get("coin") != coin or isinstance(t, bool) or not isinstance(t, int):
        raise DataError(f"Registro de funding fora do formato para {coin}: {item!r}")
    try:
        return t, float(str(rate)), float(str(premium))
    except ValueError as exc:
        raise DataError(f"Taxa de funding ilegível em {coin} {iso(Ms(t))}: {item!r}") from exc


def _chunk(provider: InfoProvider, coin: str, start: Ms, end: Ms) -> tuple[list[Any], int]:
    records: list[tuple[int, float, float]] = []
    cursor = start
    requests = 0
    while cursor < end:
        page = provider.funding_history(coin, cursor, end)
        requests += 1
        if not page:
            break
        parsed = [_record(item, coin) for item in page]
        times = [t for t, _, _ in parsed]
        if min(times) < cursor or max(times) >= end:
            raise DataError(f"Funding de {coin} fora de [{iso(cursor)}, {iso(end)}).")
        records.extend(parsed)
        if hour_floor(Ms(max(times))) >= end - MS_PER_HOUR:
            break
        cursor = Ms(max(times) + 1)
    return records, requests


def funding_covered(store: ParquetStore, coin: str, span: Span) -> bool:
    """A janela inteira já está gravada para o ativo."""
    return any(s.start <= span.start and span.end <= s.end for s in store.spans(FUNDING, (coin,)))


def ingest_funding(
    provider: InfoProvider, store: ParquetStore, coin: str, span: Span
) -> FundingResult:
    """Grava uma taxa por hora cheia de ``span``.

    Raises:
        DataError: janela que não começa e termina em hora cheia, registro fora do formato,
            hora sem registro ou com mais de um.
    """
    if span.start % MS_PER_HOUR or span.end % MS_PER_HOUR or span.empty:
        raise DataError(
            f"Janela de funding fora da hora cheia: [{iso(span.start)}, {iso(span.end)})."
        )
    records: list[tuple[int, float, float]] = []
    requests = 0
    step = FUNDING_PAGE_MAX * MS_PER_HOUR
    for chunk_start in range(span.start, span.end, step):
        chunk_end = Ms(min(chunk_start + step, span.end))
        found, n = _chunk(provider, coin, Ms(chunk_start), chunk_end)
        records.extend(found)
        requests += n

    by_hour: dict[int, tuple[int, float, float]] = {}
    for record in records:
        hour = hour_floor(Ms(record[0]))
        if hour in by_hour:
            raise DataError(f"Funding de {coin}: dois registros na hora {iso(hour)}.")
        by_hour[hour] = record
    missing = [h for h in range(span.start, span.end, MS_PER_HOUR) if h not in by_hour]
    if missing:
        shown = ", ".join(iso(Ms(h)) for h in missing[:5])
        raise DataError(
            f"Funding de {coin}: {len(missing)} hora(s) sem registro (RF-ING-05 CA-05.1), "
            f"a começar por {shown}."
        )
    frame = pl.DataFrame(
        [(hour, t, rate, premium) for hour, (t, rate, premium) in sorted(by_hour.items())],
        schema=SCHEMAS[FUNDING],
        orient="row",
    )
    store.write(FUNDING, (coin,), frame, span=span, instant="hour_ms")
    log.info("ingest.funding", coin=coin, hours=frame.height, requests=requests)
    return FundingResult(coin, frame.height, requests)
