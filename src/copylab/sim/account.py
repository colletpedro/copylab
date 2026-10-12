"""Contabilidade da subconta (design §5; RF-SIM-04 CA-04.1, RF-SIM-06).

Uma subconta guarda saldo em dólares e, por ativo, tamanho com sinal e custo médio. Abrir
ou aumentar não realiza nada e faz a média ponderada. Reduzir ou fechar realiza
``tamanho reduzido * (preço - custo médio) * sinal da posição`` e o credita no saldo. Cruzar
o zero são duas ordens: :meth:`Subaccount.trade` recusa a que cruza, e o espelhamento envia
o fechamento e a abertura separados. Taxa e funding saem do saldo e vão para contadores
próprios.

Patrimônio: ``saldo + Σ tamanho * (marcação - custo médio)``.

**Identidade de conciliação** (RF-SIM-06 CA-06.2): ``patrimônio final - capital inicial =
PnL realizado + PnL não realizado - taxas - funding pago``. :func:`reconcile` recalcula as
parcelas da direita só das listas de ordens e de pagamentos, repetindo o custo médio por um
caminho que não lê o saldo; do contrário a identidade fecharia por construção.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from copylab.exceptions import SimulationError
from copylab.sim.model import FundingPayment, Order

__all__ = ["RELATIVE_TOLERANCE", "Reconciliation", "Subaccount", "reconcile"]

#: Tolerância relativa da identidade de conciliação (design §5).
RELATIVE_TOLERANCE = 1e-9
#: Resíduo de ponto flutuante que ainda é posição zero.
_DUST = 1e-12


def _sign(x: float) -> int:
    return (x > 0.0) - (x < 0.0)


@dataclass(slots=True)
class _Position:
    size: float = 0.0
    avg: float = 0.0


class Subaccount:
    """Saldo e posições de uma subconta. Não conhece preço: quem marca passa as marcações."""

    def __init__(self, capital: float) -> None:
        self.capital = capital
        self.cash = capital
        self.realized = 0.0
        self.fees = 0.0
        self.funding_paid = 0.0
        self._positions: dict[str, _Position] = {}

    def size(self, coin: str) -> float:
        position = self._positions.get(coin)
        return 0.0 if position is None else position.size

    def avg_cost(self, coin: str) -> float:
        position = self._positions.get(coin)
        return 0.0 if position is None else position.avg

    def open_coins(self) -> list[str]:
        """Ativos com posição, em ordem alfabética."""
        return sorted(c for c, p in self._positions.items() if p.size != 0.0)

    def trade(self, coin: str, signed_size: float, price: float, fee: float) -> float:
        """Aplica uma execução e devolve o PnL que ela realizou.

        Raises:
            SimulationError: se a execução cruza o zero (são duas ordens, design §5).
        """
        position = self._positions.setdefault(coin, _Position())
        realized = 0.0
        if position.size == 0.0 or _sign(position.size) == _sign(signed_size):
            total = abs(position.size) + abs(signed_size)
            position.avg = (abs(position.size) * position.avg + abs(signed_size) * price) / total
            position.size += signed_size
        else:
            if abs(signed_size) > abs(position.size) * (1 + _DUST):
                raise SimulationError(
                    f"A execução de {signed_size} em {coin} cruza o zero (posição "
                    f"{position.size}): são duas ordens."
                )
            realized = abs(signed_size) * (price - position.avg) * _sign(position.size)
            position.size += signed_size
            if abs(position.size) <= _DUST * max(1.0, abs(signed_size)):
                position.size = 0.0
                position.avg = 0.0
        self.realized += realized
        self.cash += realized - fee
        self.fees += fee
        return realized

    def pay_funding(self, coin: str, mark: float, rate: float) -> float:
        """Funding de uma hora cheia sobre a posição atual; devolve o valor debitado."""
        amount = self.size(coin) * mark * rate
        self.cash -= amount
        self.funding_paid += amount
        return amount

    def unrealized(self, marks: Mapping[str, float]) -> float:
        return sum(p.size * (marks[c] - p.avg) for c, p in self._positions.items() if p.size != 0.0)

    def equity(self, marks: Mapping[str, float]) -> float:
        """``saldo + Σ tamanho * (marcação - custo médio)`` (RF-SIM-06 CA-06.1)."""
        return self.cash + self.unrealized(marks)

    def gross_exposure(self, marks: Mapping[str, float]) -> float:
        """Soma dos módulos dos notionals das posições abertas, à marcação."""
        return sum(abs(p.size) * marks[c] for c, p in self._positions.items() if p.size != 0.0)

    def positions(self) -> dict[str, tuple[float, float]]:
        """Tamanho e custo médio das posições abertas."""
        return {c: (p.size, p.avg) for c, p in self._positions.items() if p.size != 0.0}


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Os dois lados da identidade, e a diferença entre eles."""

    lhs: float  # patrimônio final - capital inicial
    realized: float
    unrealized: float
    fees: float
    funding: float
    scale: float

    @property
    def rhs(self) -> float:
        return self.realized + self.unrealized - self.fees - self.funding

    @property
    def residual(self) -> float:
        return self.lhs - self.rhs

    @property
    def ok(self) -> bool:
        return abs(self.residual) <= RELATIVE_TOLERANCE * self.scale


def reconcile(
    capital: float,
    final_equity: float,
    orders: Sequence[Order],
    payments: Sequence[FundingPayment],
    marks: Mapping[str, float],
) -> Reconciliation:
    """Confere a identidade a partir das listas de ordens e de pagamentos.

    O custo médio é refeito aqui, ordem a ordem, guardando o custo total da posição no
    lugar do preço médio, e nada é lido do saldo da subconta: só ``final_equity`` entra,
    do outro lado da igualdade.
    """
    net: dict[str, float] = {}
    cost: dict[str, float] = {}
    realized = 0.0
    for order in orders:
        d = order.signed
        n = net.get(order.coin, 0.0)
        c = cost.get(order.coin, 0.0)
        if n == 0.0 or _sign(n) == _sign(d):
            net[order.coin] = n + d
            cost[order.coin] = c + abs(d) * order.price
        else:
            average = c / abs(n)
            realized += abs(d) * (order.price - average) * _sign(n)
            remaining = n + d
            if abs(remaining) <= _DUST * max(1.0, abs(d)):
                net[order.coin], cost[order.coin] = 0.0, 0.0
            else:
                net[order.coin], cost[order.coin] = remaining, average * abs(remaining)
    unrealized = sum(n * marks[coin] - _sign(n) * cost[coin] for coin, n in net.items() if n != 0.0)
    fees = sum(o.fee for o in orders)
    funding = sum(p.amount for p in payments)
    scale = max(
        1.0, abs(capital), abs(final_equity), abs(realized), abs(unrealized), fees, abs(funding)
    )
    return Reconciliation(final_equity - capital, realized, unrealized, fees, funding, scale)
