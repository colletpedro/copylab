"""Intervalos semiabertos de tempo, ``[start, end)`` em ``Ms``, e a aritmética deles.

Servem a duas coisas no armazenamento: o registro do que já foi gravado em cada
partição e o registro das janelas congeladas (design §3.2). Uma linha está protegida
quando o instante dela cai na interseção dos dois.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from copylab.exceptions import DataError
from copylab.timeutil import Ms, iso

__all__ = ["Span", "intersect", "normalize"]


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """Intervalo ``[start, end)``. ``start == end`` é vazio e permitido."""

    start: Ms
    end: Ms

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise DataError(
                f"Intervalo invertido: fim {iso(self.end)} antes do início {iso(self.start)}."
            )

    @property
    def empty(self) -> bool:
        return self.start == self.end

    def contains(self, t: int) -> bool:
        return self.start <= t < self.end


def normalize(spans: Iterable[Span]) -> tuple[Span, ...]:
    """Ordena, funde os que se tocam ou se sobrepõem e descarta os vazios."""
    merged: list[Span] = []
    for span in sorted(s for s in spans if not s.empty):
        if merged and span.start <= merged[-1].end:
            last = merged[-1]
            merged[-1] = Span(last.start, max(last.end, span.end))
        else:
            merged.append(span)
    return tuple(merged)


def intersect(a: Iterable[Span], b: Iterable[Span]) -> tuple[Span, ...]:
    """Instantes que estão ao mesmo tempo em ``a`` e em ``b``."""
    left, right = normalize(a), normalize(b)
    out: list[Span] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i].start, right[j].start)
        end = min(left[i].end, right[j].end)
        if start < end:
            out.append(Span(start, end))
        if left[i].end <= right[j].end:
            i += 1
        else:
            j += 1
    return tuple(out)
