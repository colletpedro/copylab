"""Diagnóstico das quebras de continuidade (design §3.5; RF-ING-03 CA-03.4).

A medida é informativa: serve para investigar a causa das quebras, que o estudo não conhece.
A hipótese em teste é que parte dos fills de TWAP some do histórico depois de alguns meses.
Por isso se agrupam as quebras por idade, que é o tempo entre a quebra e a coleta, e por
haver ou não fill de TWAP do mesmo ativo perto dela.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from itertools import pairwise

import polars as pl

from copylab.exceptions import ConfigError, DataError
from copylab.leader.model import AgeBucket, Break, BreakReport
from copylab.timeutil import Ms

__all__ = ["break_report"]


def _twap_times(fills: pl.DataFrame) -> dict[str, list[int]]:
    for column in ("coin", "time_ms", "twap_id"):
        if column not in fills.columns:
            raise DataError(f"A tabela de fills não tem a coluna {column!r}.")
    twap = fills.filter(pl.col("twap_id").is_not_null()).select("coin", "time_ms")
    times: dict[str, list[int]] = {}
    for coin, time_ms in twap.iter_rows():
        times.setdefault(coin, []).append(time_ms)
    for series in times.values():
        series.sort()
    return times


def break_report(
    breaks: Sequence[Break],
    fills: pl.DataFrame,
    collected_at_ms: Ms,
    *,
    neighbourhood_ms: int,
    age_edges_ms: Sequence[int],
) -> BreakReport:
    """Distribuição das quebras por idade e por fill de TWAP na vizinhança.

    A idade de uma quebra é ``collected_at_ms`` menos o instante do fill que a revela
    (``Break.t``). As faixas são ``[0, e₁)``, ``[e₁, e₂)``, …, ``[eₙ, ∞)``, com ``e`` em
    ``age_edges_ms``. Há TWAP na vizinhança se algum fill do mesmo ativo com ``twap_id`` tem
    instante entre ``prev_t - neighbourhood_ms`` e ``t + neighbourhood_ms``, inclusive.

    Raises:
        ConfigError: faixas que não são positivas e crescentes, ou vizinhança negativa.
        DataError: quebra posterior à coleta, ou tabela sem as colunas.
    """
    edges = tuple(age_edges_ms)
    if any(b <= a for a, b in pairwise(edges)) or any(e <= 0 for e in edges):
        raise ConfigError(f"As faixas de idade precisam ser positivas e crescentes: {edges}.")
    if neighbourhood_ms < 0:
        raise ConfigError(f"A vizinhança não pode ser negativa: {neighbourhood_ms}.")
    twap = _twap_times(fills)
    counts = [0] * (len(edges) + 1)
    with_twap = [0] * (len(edges) + 1)
    for found in breaks:
        age = collected_at_ms - found.t
        if age < 0:
            raise DataError(f"A quebra de {found.coin} em {found.t} é posterior à coleta.")
        bucket = bisect_right(edges, age)
        counts[bucket] += 1
        times = twap.get(found.coin, [])
        low = bisect_left(times, found.prev_t - neighbourhood_ms)
        if low < len(times) and times[low] <= found.t + neighbourhood_ms:
            with_twap[bucket] += 1
    by_age = tuple(
        AgeBucket(
            age_from_ms=0 if i == 0 else edges[i - 1],
            age_to_ms=edges[i] if i < len(edges) else None,
            breaks=counts[i],
            with_twap=with_twap[i],
        )
        for i in range(len(counts))
    )
    return BreakReport(total=sum(counts), with_twap=sum(with_twap), by_age=by_age)
