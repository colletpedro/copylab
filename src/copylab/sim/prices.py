"""Fontes de preço do simulador (design §3.7; RF-SIM-03, ADR-0003).

:class:`PriceFeed` é o dado, sem método de leitura; ``bind`` o prende ao cursor e devolve a
:class:`PriceSource`, que é o que o motor enxerga. A fonte da Rota A é :class:`ProxySource`,
sobre a série por segundo da Binance. A da Rota B (``BookSource``) é do Bloco H.

``available_from`` devolve só um instante, e ``ladder`` e ``mark`` levantam
:class:`~copylab.exceptions.LookaheadError` para um instante além do cursor. A fonte pode
ler, ao executar em ``tau``, o resto do segundo de ``tau`` (ADR-0003), e ``horizon`` diz até
onde ela já leu: é daí em diante que o teste de mutação altera os preços.
"""

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

from copylab.exceptions import DataError, LookaheadError
from copylab.sim.cursor import CursorView
from copylab.sim.model import Ladder, Level, Side
from copylab.timeutil import MS_PER_SECOND, Ms, iso, second_of

__all__ = ["PriceFeed", "PriceSource", "ProxyBar", "ProxySource"]


class PriceSource(Protocol):
    def available_from(self, coin: str, t: Ms) -> Ms | None:
        """Primeiro instante ``>= t`` com observação utilizável, ou ``None``."""
        ...

    def ladder(self, coin: str, t: Ms, side: Side) -> Ladder:
        """Níveis de preço e tamanho contra o seguidor, para executar em ``t``."""
        ...

    def mark(self, coin: str, t: Ms) -> float:
        """Preço de marcação em ``t``, só com o que era conhecido antes dele."""
        ...

    def horizon(self) -> Ms:
        """A observação mais avançada já consumida."""
        ...


class PriceFeed(Protocol):
    def bind(self, cursor: CursorView) -> PriceSource: ...


@dataclass(frozen=True, slots=True)
class ProxyBar:
    """Um segundo do proxy: mínimo, máximo e último preço negociado (RF-ING-06 CA-06.1)."""

    second: int
    low: float
    high: float
    last: float


class _Series:
    def __init__(self, coin: str, bars: Sequence[ProxyBar]) -> None:
        for a, b in pairwise(bars):
            if b.second <= a.second:
                raise DataError(f"As barras de {coin} não estão em ordem estrita de segundo.")
        self.seconds = [b.second for b in bars]
        self.low = [b.low for b in bars]
        self.high = [b.high for b in bars]
        self.last = [b.last for b in bars]


class ProxySource:
    """Preço proxy por segundo (Rota A). Segundo sem negócio não tem barra: não é preenchido."""

    def __init__(self, bars: Mapping[str, Sequence[ProxyBar]]) -> None:
        self._series = {coin: _Series(coin, series) for coin, series in bars.items()}

    def bind(self, cursor: CursorView) -> PriceSource:
        return _BoundProxy(self._series, cursor)


class _BoundProxy:
    def __init__(self, series: Mapping[str, _Series], cursor: CursorView) -> None:
        self._series = series
        self._cursor = cursor
        self._horizon = Ms(-(2**62))

    def _guard(self, what: str, coin: str, t: Ms) -> _Series:
        if t > self._cursor.now:
            raise LookaheadError(
                f"Leitura de {what} de {coin} em {iso(t)}, mas o cursor está em "
                f"{iso(self._cursor.now)} (RF-SIM-01 CA-01.3)."
            )
        try:
            return self._series[coin]
        except KeyError as exc:
            raise DataError(f"Sem série de preço para {coin}.") from exc

    def available_from(self, coin: str, t: Ms) -> Ms | None:
        series = self._series.get(coin)
        if series is None:
            return None
        second = second_of(t)
        index = bisect_left(series.seconds, second)
        if index == len(series.seconds):
            return None
        if series.seconds[index] == second:
            return t
        return Ms(series.seconds[index] * MS_PER_SECOND)

    def ladder(self, coin: str, t: Ms, side: Side) -> Ladder:
        series = self._guard("preço", coin, t)
        second = second_of(t)
        index = bisect_left(series.seconds, second)
        if index == len(series.seconds) or series.seconds[index] != second:
            raise DataError(f"Sem negócio de {coin} no segundo de {iso(t)}: a ordem não executa.")
        self._horizon = Ms(max(self._horizon, second * MS_PER_SECOND))
        price = series.high[index] if side == "buy" else series.low[index]
        return (Level(price),)

    def mark(self, coin: str, t: Ms) -> float:
        series = self._guard("marcação", coin, t)
        index = bisect_left(series.seconds, second_of(t)) - 1
        if index < 0:
            raise DataError(f"Sem preço de {coin} antes de {iso(t)} para marcar.")
        return series.last[index]

    def horizon(self) -> Ms:
        return self._horizon
