"""Conferência do proxy contra os fills (T-061; RF-ING-06 CA-06.3 e CA-06.4, design 1.7 §3.6).

Cada fill de perpétuo do primeiro dex de uma candidata, na janela de seleção, é comparado ao
último preço do segundo do proxy que contém o instante dele:

    diferença = (preço do fill / último do segundo - 1) * 10^4   (bps)

Por dia UTC, a mediana das diferenças (o deslocamento de nível entre as duas corretoras). O desvio
de um fill é o módulo da diferença dele para a mediana do dia dele, e o p95, o percentil (o do
arquivo de parâmetros, 95, sem interpolação) de todos os desvios da janela. O nível é o maior
módulo de mediana diária. Ativo com p95 acima de ``proxy_max_deviation_p95_bps`` ou nível acima
de ``proxy_max_level_bps`` é "proxy inválido".
Fill em segundo sem negócio, ou sem preço, é pulado e contado.
"""

from dataclasses import dataclass
from typing import Final

import polars as pl

from copylab.stats import nearest_rank_pct
from copylab.timeutil import second_of_expr, utc_day_expr

__all__ = ["DayLevel", "ProxyCheck", "check_proxy"]

_BPS: Final = 10_000.0


@dataclass(frozen=True, slots=True)
class DayLevel:
    """A mediana da diferença, em bps, dos fills de um dia UTC."""

    day: int
    median_bps: float
    n_fills: int


@dataclass(frozen=True, slots=True)
class ProxyCheck:
    """O resultado da conferência de um ativo."""

    coin: str
    compared: int  # fills comparados
    skipped: int  # fills em segundo sem negócio, ou sem preço
    days: tuple[DayLevel, ...]  # em ordem de dia
    deviation_p95_bps: float | None
    level_bps: float | None  # maior módulo de mediana diária
    shift_bps: float | None  # maior menos menor mediana diária (RF-ING-06 CA-06.4)
    valid: bool


def check_proxy(
    coin: str,
    fills: pl.DataFrame,
    proxy: pl.DataFrame,
    *,
    deviation_percentile_pct: int,
    max_deviation_p95_bps: float,
    max_level_bps: float,
) -> ProxyCheck:
    """Confere o proxy de ``coin`` contra os fills dele.

    ``fills`` traz ``time_ms`` e ``px``; ``proxy``, ``second`` e ``last``. Os limiares vêm do
    arquivo de parâmetros e são inclusivos: p95 e nível iguais ao limite são válidos. Ativo sem
    nenhum fill comparável é inválido.
    """
    frame = fills.select("time_ms", "px").with_columns(
        second_of_expr("time_ms").alias("second"), utc_day_expr("time_ms").alias("day")
    )
    joined = frame.join(proxy.select("second", "last"), on="second", how="left")
    usable = pl.col("px").is_not_null() & pl.col("last").is_not_null() & (pl.col("last") > 0)
    compared = joined.filter(usable).with_columns(
        ((pl.col("px") / pl.col("last") - 1.0) * _BPS).alias("diff")
    )
    skipped = joined.height - compared.height
    if compared.height == 0:
        return ProxyCheck(coin, 0, skipped, (), None, None, None, valid=False)

    daily = (
        compared.group_by("day")
        .agg(pl.col("diff").median().alias("median"), pl.len().alias("n"))
        .sort("day")
    )
    days = tuple(DayLevel(int(d), float(m), int(n)) for d, m, n in daily.iter_rows())
    deviations = (
        compared.join(daily.select("day", "median"), on="day")
        .select((pl.col("diff") - pl.col("median")).abs().alias("deviation"))
        .get_column("deviation")
        .sort()
        .to_list()
    )
    p95 = nearest_rank_pct(deviations, deviation_percentile_pct)
    medians = [d.median_bps for d in days]
    level = max(abs(m) for m in medians)
    valid = p95 <= max_deviation_p95_bps and level <= max_level_bps
    return ProxyCheck(
        coin, compared.height, skipped, days, p95, level, max(medians) - min(medians), valid=valid
    )
