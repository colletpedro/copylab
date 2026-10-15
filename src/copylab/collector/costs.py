"""Medida de custo sobre as tabelas do coletor (T-062; RF-COL-05 CA-05.2, design 1.7 §3.9).

Escolhe os dias que se qualificam pela mesma cobertura por dia do ``collect status``
(:class:`~copylab.collector.status.DayCoverage`), lê as observações de melhor compra e venda e
as lacunas desses dias e entrega a conta a :func:`copylab.costs.half_spread_bps`. Quem decide
quais ativos medir e grava o arquivo é a CLI.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import polars as pl

from copylab.collector.status import DayCoverage
from copylab.costs import CostEntry, half_spread_bps
from copylab.exceptions import DataError
from copylab.storage import ParquetRepository, content_hash
from copylab.timeutil import day_start, iso

__all__ = ["Measurement", "measure_coin", "qualifying_days"]

_BBO_KEYS: Final = ("time_ms", "recv_ms", "conn_ms")
_GAP_KEYS: Final = ("start_ms", "end_ms")


@dataclass(frozen=True, slots=True)
class Measurement:
    """O resultado de medir um ativo: o custo, ou quantos dias ainda faltam para ele."""

    coin: str
    entry: CostEntry | None
    qualifying: tuple[int, ...]  # dias que já se qualificam, em ordem
    days_missing: int  # 0 quando medido


def qualifying_days(daily: Sequence[DayCoverage], min_coverage_pct: float) -> tuple[int, ...]:
    """Os dias UTC encerrados com cobertura de ao menos ``min_coverage_pct``, em ordem.

    A comparação é em inteiros (milissegundos cobertos contra o dia observado), de modo que
    exatamente 95% qualifica sem depender do arredondamento de uma fração.
    """
    return tuple(
        d.day
        for d in sorted(daily, key=lambda d: d.day)
        if d.complete
        and 100 * (d.observed_ms - d.gap_ms - d.unrecorded_ms) >= min_coverage_pct * d.observed_ms
    )


def _data_hash(bbo: pl.DataFrame, gaps: pl.DataFrame) -> str:
    text = f"bbo:{content_hash(bbo, _BBO_KEYS)}\ngaps:{content_hash(gaps, _GAP_KEYS)}"
    return hashlib.sha256(text.encode()).hexdigest()


def measure_coin(
    repo: ParquetRepository,
    coin: str,
    daily: Sequence[DayCoverage],
    *,
    min_days: int,
    min_coverage_pct: float,
) -> Measurement:
    """Mede o meio-spread de ``coin`` nos ``min_days`` primeiros dias que se qualificam.

    Com menos dias que isso, não mede e diz quantos faltam.

    Raises:
        DataError: um dia que se qualifica não tem ``bbo`` compactado, ou não há cotação válida.
    """
    qualifying = qualifying_days(daily, min_coverage_pct)
    if len(qualifying) < min_days:
        return Measurement(coin, None, qualifying, min_days - len(qualifying))
    used = qualifying[:min_days]
    bbo_days: list[pl.DataFrame] = []
    gap_days: list[pl.DataFrame] = []
    for day in used:
        start, end = day_start(day), day_start(day + 1)
        rows = repo.bbo(coin, start, end)
        if rows.height == 0:
            raise DataError(
                f"{coin}: o dia {iso(start)[:10]} tem cobertura, mas não há `bbo` compactado. "
                "Rode `copylab collect compact` e repita."
            )
        bbo_days.append(rows)
        gap_days.append(repo.gaps(coin, start, end))
    bbo = pl.concat(bbo_days)
    gaps = pl.concat(gap_days).unique().sort("start_ms", "end_ms")
    result = half_spread_bps(bbo, ((a, b) for a, b, *_ in gaps.iter_rows()), used)
    entry = CostEntry(result.value_bps, used, _data_hash(bbo, gaps), result.skipped)
    return Measurement(coin, entry, qualifying, 0)
