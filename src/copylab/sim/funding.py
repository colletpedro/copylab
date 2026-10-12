"""A tabela de funding presa ao cursor (design §3.7; RF-SIM-01 CA-01.3)."""

from collections.abc import Mapping

from copylab.exceptions import DataError, LookaheadError
from copylab.sim.cursor import CursorView
from copylab.timeutil import Ms, iso

__all__ = ["BoundFunding", "FundingTable"]


class FundingTable:
    """Taxa de funding de cada hora cheia, por ativo. Sem método de leitura: só ``bind``."""

    def __init__(self, rates: Mapping[str, Mapping[Ms, float]]) -> None:
        self._rates = {coin: dict(hours) for coin, hours in rates.items()}

    def bind(self, cursor: CursorView) -> "BoundFunding":
        return BoundFunding(self._rates, cursor)


class BoundFunding:
    def __init__(self, rates: Mapping[str, Mapping[Ms, float]], cursor: CursorView) -> None:
        self._rates = rates
        self._cursor = cursor

    def rate(self, coin: str, hour: Ms) -> float:
        """A taxa da hora cheia ``hour`` (o registro com ``hour_ms == hour``).

        Raises:
            LookaheadError: se a hora passa do cursor.
            DataError: se não há registro: hora faltante é falha explícita (RF-ING-05).
        """
        if hour > self._cursor.now:
            raise LookaheadError(
                f"Leitura do funding de {coin} em {iso(hour)}, mas o cursor está em "
                f"{iso(self._cursor.now)} (RF-SIM-01 CA-01.3)."
            )
        try:
            return self._rates[coin][hour]
        except KeyError as exc:
            raise DataError(f"Sem taxa de funding de {coin} em {iso(hour)}.") from exc
