"""A fita do líder presa ao cursor (design §3.7; RF-SIM-01 CA-01.3).

:class:`LeaderTape` guarda os eventos e não tem método de leitura. :meth:`LeaderTape.bind`
a prende ao cursor e ao atraso Δ do cenário e devolve o único acesso que existe,
:class:`BoundTape`. ``until(t)`` recusa um ``t`` acima do cursor menos o atraso: uma decisão
em ``τ`` só pode depender de eventos do líder com instante até ``τ - Δ``. ``next_wake``
devolve só instantes futuros, nunca conteúdo.
"""

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from typing import overload

from copylab.exceptions import LookaheadError
from copylab.leader import LeaderEvent
from copylab.sim.cursor import CursorView
from copylab.timeutil import Ms, iso

__all__ = ["BoundTape", "LeaderTape"]


class _Prefix(Sequence[LeaderEvent]):
    """Os primeiros ``n`` eventos da fita, sem copiá-los (a fita pode ter dezenas de milhares)."""

    def __init__(self, events: Sequence[LeaderEvent], n: int) -> None:
        self._events = events
        self._n = n

    def __len__(self) -> int:
        return self._n

    @overload
    def __getitem__(self, index: int) -> LeaderEvent: ...
    @overload
    def __getitem__(self, index: slice) -> list[LeaderEvent]: ...
    def __getitem__(self, index: int | slice) -> LeaderEvent | list[LeaderEvent]:
        if isinstance(index, slice):
            return [self._events[i] for i in range(*index.indices(self._n))]
        if not -self._n <= index < self._n:
            raise IndexError(index)
        return self._events[index % self._n if index < 0 else index]


class LeaderTape:
    """Os eventos do líder, em ordem de instante e, no empate, de ativo."""

    def __init__(self, events: Iterable[LeaderEvent]) -> None:
        self._events = sorted(events, key=lambda e: (e.t, e.coin))
        self._times = [e.t for e in self._events]

    def bind(self, cursor: CursorView, delay_ms: int) -> "BoundTape":
        return BoundTape(self._events, self._times, cursor, delay_ms)


class BoundTape:
    def __init__(
        self,
        events: Sequence[LeaderEvent],
        times: Sequence[int],
        cursor: CursorView,
        delay_ms: int,
    ) -> None:
        self._events = events
        self._times = times
        self._cursor = cursor
        self._delay = delay_ms

    def until(self, t: Ms) -> Sequence[LeaderEvent]:
        """Os eventos com instante até ``t``, inclusive.

        Raises:
            LookaheadError: se ``t`` passa do cursor menos o atraso.
        """
        limit = self._cursor.now - self._delay
        if t > limit:
            raise LookaheadError(
                f"Leitura de eventos do líder até {iso(t)}, mas o cursor está em "
                f"{iso(self._cursor.now)} e o atraso é de {self._delay} ms: só se pode ler "
                f"até {iso(Ms(limit))} (RF-SIM-01 CA-01.3)."
            )
        return _Prefix(self._events, bisect_right(self._times, t))

    def next_wake(self, after: Ms) -> Ms | None:
        """O primeiro instante de evento estritamente depois de ``after``. Só o instante."""
        index = bisect_right(self._times, after)
        return Ms(self._times[index]) if index < len(self._times) else None

    def all_events(self) -> Sequence[LeaderEvent]:
        """Todos os eventos, para o relatório depois que o laço terminou.

        Raises:
            LookaheadError: se o laço ainda corre.
        """
        if not self._cursor.closed:
            raise LookaheadError("A fita inteira só pode ser lida depois que o laço termina.")
        return self._events
