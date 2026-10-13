"""Contadores de não cópia e excesso sobre o teto (RF-ANA-04, RF-SIM-02 CA-02.7; design §3.8,
precisões do 1.6).

O laço do simulador já calcula, para cada evento do líder, a fração que deixou de ser copiada
(``1 - executado / pedido``, com o pedido sem teto, mínimo, lote nem profundidade) e o motivo (a
primeira restrição que cortou, na ordem teto, mínimo, profundidade). Aqui só se somam as
subcontas. O sexto motivo, "fora do universo", não sai do laço: chega pronto de quem lê a tabela
de fills (:func:`outside_universe`).
"""

from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass

from copylab.sim.loop import SubaccountResult
from copylab.sim.mirror import (
    BELOW_MINIMUM,
    CAP_REACHED,
    DEPTH_EXCEEDED,
    PENDING,
    PRE_WINDOW,
)

__all__ = [
    "NON_COPY_REASONS",
    "OUTSIDE_UNIVERSE",
    "CapExcess",
    "NonCopy",
    "cap_excess",
    "non_copy",
    "outside_universe",
]

OUTSIDE_UNIVERSE = "outside_universe"

#: Os seis motivos de RF-ANA-04 CA-04.1, na ordem em que a spec os lista.
NON_COPY_REASONS = (
    BELOW_MINIMUM,
    CAP_REACHED,
    DEPTH_EXCEEDED,
    OUTSIDE_UNIVERSE,
    PRE_WINDOW,
    PENDING,
)


@dataclass(frozen=True, slots=True)
class NonCopy:
    """Quanto deixou de ser copiado por um motivo: eventos do líder (fills, para "fora do
    universo") e o notional do líder que eles representam, já multiplicado pela fração não
    copiada."""

    events: int
    notional: float


def outside_universe(fills: Iterable[tuple[str, float]], universe: Set[str]) -> NonCopy:
    """Os fills do líder, na janela, em instrumento que não está no universo.

    ``fills`` são pares ``(ativo, notional)`` de todos os fills do líder na janela, de qualquer
    instrumento (perpétuo fora do universo, HIP-3, spot, token de resultado). A unidade é o fill:
    fora do universo não há evento do líder, porque o laço não o vê (design §3.8)."""
    outside = [notional for coin, notional in fills if coin not in universe]
    return NonCopy(len(outside), sum(outside))


def non_copy(results: Sequence[SubaccountResult], outside: NonCopy) -> dict[str, NonCopy]:
    """Os seis contadores de RF-ANA-04 CA-04.1, somados nas subcontas, na ordem da spec.

    Os cinco motivos do laço vêm dos contadores de cada subconta; ``outside`` é o sexto."""
    totals: dict[str, NonCopy] = {}
    for reason in NON_COPY_REASONS:
        if reason == OUTSIDE_UNIVERSE:
            totals[reason] = outside
            continue
        totals[reason] = NonCopy(
            sum(r.counters.not_copied_events[reason] for r in results),
            sum(r.counters.not_copied_notional[reason] for r in results),
        )
    return totals


@dataclass(frozen=True, slots=True)
class CapExcess:
    """Excesso sobre o teto (RF-SIM-02 CA-02.7): o número de execuções que terminaram com
    exposição acima de ``teto * patrimônio`` e o maior excesso, em dólares e em fração do
    patrimônio (os dois máximos podem vir de subcontas diferentes)."""

    executions: int
    max_usd: float
    max_fraction: float


def cap_excess(results: Sequence[SubaccountResult]) -> CapExcess:
    """O excesso sobre o teto somado nas subcontas."""
    return CapExcess(
        sum(r.counters.cap_excess_executions for r in results),
        max((r.counters.max_cap_excess_usd for r in results), default=0.0),
        max((r.counters.max_cap_excess_fraction for r in results), default=0.0),
    )
