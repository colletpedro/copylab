"""Referência de exposição N* (T-064; RF-SEL-03, ADR-0007, design 1.7 §3.6 e 1.8).

N* é o percentil (95, em ``[reference] percentile_pct``), ponderado pelo tempo, da exposição bruta
em dólares do líder no universo, medido só sobre o tempo em que ele tem alguma posição aberta
no universo, sem interpolação. A posição de cada ativo é medida ao preço do último fill dele; a
que já existia no início da janela, ao preço do primeiro fill dela, que é onde a posição
declarada aparece (``start_position``).

A conta percorre os fills pela passada de :func:`copylab.leader.ledger.walk`, e não os eventos,
porque o evento guarda o preço do último fill do milissegundo e o da posição que já existia
precisa ser o do primeiro.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass

import polars as pl

from copylab.leader.ledger import walk
from copylab.stats import weighted_percentile
from copylab.timeutil import MS_PER_HOUR
from copylab.windows import Window

__all__ = ["Reference", "reference_exposure"]


@dataclass(frozen=True, slots=True)
class Reference:
    """N* e as horas em posição que o sustentam (ADR-0007, relatório de seleção)."""

    n_star: float
    hours_in_position: float


def reference_exposure(
    fills: pl.DataFrame,
    lots: Mapping[str, float],
    universe: Set[str],
    window: Window,
    percentile_pct: int,
) -> Reference | None:
    """N* do líder na janela, ou ``None`` se ele nunca tem posição no universo (RF-SEL-03 CA-03.2).

    Raises:
        DataError: tabela sem as colunas do livro-razão, ou perpétuo sem lote.
    """
    steps = {c: s for c, s in walk(fills, lots).items() if c in universe}
    position: dict[str, float] = {}
    price: dict[str, float] = {}
    changes: list[tuple[int, int, str, float, float]] = []
    for coin, coin_steps in steps.items():
        first = coin_steps[0]
        position[coin] = first.before
        price[coin] = first.fill.px
        changes.extend((s.fill.t, s.fill.seq, coin, s.after, s.fill.px) for s in coin_steps)
    changes.sort()

    def exposure() -> float:
        return sum(abs(position[c]) * price[c] for c in position if position[c] != 0.0)

    weights: dict[float, int] = {}
    current = exposure()
    previous: int = window.start
    for t, _, coin, after, px in changes:
        if current > 0.0 and t > previous:
            weights[current] = weights.get(current, 0) + (t - previous)
        position[coin], price[coin] = after, px
        current = exposure()
        previous = max(previous, t)
    if current > 0.0 and window.end > previous:
        weights[current] = weights.get(current, 0) + (window.end - previous)

    n_star = weighted_percentile(weights.items(), percentile_pct)
    if n_star is None or n_star <= 0.0:
        return None
    return Reference(n_star, sum(weights.values()) / MS_PER_HOUR)
