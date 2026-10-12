"""Tipos do simulador: lado, nível da escada, ordem executada e pagamento de funding
(design §3.7, §4.3 passo 11)."""

import math
from dataclasses import dataclass
from typing import Literal

from copylab.timeutil import Ms

__all__ = ["FundingPayment", "Ladder", "Level", "Order", "Side"]

Side = Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class Level:
    """Um nível da escada: preço e tamanho disponíveis contra o seguidor."""

    price: float
    size: float = math.inf


Ladder = tuple[Level, ...]


@dataclass(frozen=True, slots=True)
class Order:
    """Uma ordem executada (§4.3 passo 11). Ordem não enviada não existe: é contada."""

    event_t: Ms  # instante do evento do líder que a originou
    nominal_t: Ms  # event_t + Δ
    exec_t: Ms  # instante da execução, a primeira observação a partir do nominal
    coin: str
    side: Side
    requested: float  # tamanho pedido, em módulo
    executed: float  # tamanho executado, em módulo
    price: float  # preço médio ponderado dos níveis usados, já com slippage
    fee: float
    reason: str  # target_reduce, target_increase ou cap_reduction

    @property
    def signed(self) -> float:
        return self.executed if self.side == "buy" else -self.executed

    @property
    def notional(self) -> float:
        return self.executed * self.price

    @property
    def delay_ms(self) -> int:
        """Atraso efetivo, do evento à execução: Δ, ou mais se esperou preço."""
        return self.exec_t - self.event_t


@dataclass(frozen=True, slots=True)
class FundingPayment:
    """Funding de uma hora cheia: ``size * mark * rate``, debitado quando positivo."""

    t: Ms
    coin: str
    size: float
    mark: float
    rate: float
    amount: float
