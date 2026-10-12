"""O laço do simulador e o resultado de uma subconta (design §3.7, §4.2; RF-SIM-01, RF-SIM-05).

O laço é o único dono do cursor. Percorre, em ordem de instante, quatro tipos de ocorrência,
com estas prioridades quando caem no mesmo instante: funding de uma hora cheia, execução em um
ativo, amostra diária de patrimônio e fim da janela. A janela é semiaberta: no fim a subconta só
é marcada.

Cada evento do líder, lido no instante nominal ``t + delay``, é executado em ``tau``, o primeiro
instante a partir dele em que a fonte de preço tem observação do ativo (ADR-0003, ADR-0008).
Nada é contabilizado antes de ``tau``. Se ``tau`` não existe ou não é anterior ao fim, o evento
fica pendente.
"""

import heapq
from collections.abc import Mapping, Set
from dataclasses import dataclass

from copylab.exceptions import ConfigError, SimulationError
from copylab.leader import LeaderEvent
from copylab.sim.account import Reconciliation, Subaccount, reconcile
from copylab.sim.cursor import Cursor
from copylab.sim.funding import FundingTable
from copylab.sim.mirror import PENDING, Counters, Engine, Frictions, Mirror
from copylab.sim.model import FundingPayment, Order
from copylab.sim.prices import PriceFeed
from copylab.sim.tape import LeaderTape
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms, day_start, hour_floor, utc_day
from copylab.windows import Window

__all__ = ["SubaccountResult", "run_subaccount"]


@dataclass(frozen=True, slots=True)
class SubaccountResult:
    """O que uma subconta fez (design §3.7). Os contadores são só para leitura."""

    orders: tuple[Order, ...]
    payments: tuple[FundingPayment, ...]
    equity_curve: tuple[tuple[Ms, float], ...]
    max_leverage: float
    max_leverage_at: Ms | None
    counters: Counters
    final_positions: Mapping[str, tuple[float, float]]
    final_equity: float
    realized: float
    unrealized: float
    fees: float
    funding_paid: float
    pending: tuple[LeaderEvent, ...]
    frozen: bool
    frozen_at: Ms | None
    reconciliation: Reconciliation

    @property
    def delayed_executions(self) -> int:
        """Ordens executadas depois do instante nominal, porque o ativo esperou preço."""
        return sum(order.exec_t > order.nominal_t for order in self.orders)


def _first_hour_at_or_after(t: Ms) -> Ms:
    floor = hour_floor(t)
    return floor if floor == t else Ms(floor + MS_PER_HOUR)


def run_subaccount(
    tape: LeaderTape,
    reference: float,
    universe: Set[str],
    prices: PriceFeed,
    funding: FundingTable,
    lots: Mapping[str, float],
    capital: float,
    window: Window,
    frictions: Frictions,
    mirror: Mirror,
) -> SubaccountResult:
    """Simula uma subconta que copia um líder na janela.

    Raises:
        ConfigError: referência de exposição não positiva.
        SimulationError: a identidade de conciliação não fecha.
        LookaheadError: alguma leitura além do que o cursor permite (defeito do laço).
    """
    if not reference > 0.0:
        raise ConfigError(f"A referência de exposição precisa ser positiva: {reference}.")
    start, end, delay = window.start, window.end, frictions.delay_ms
    cursor = Cursor(start)
    view = cursor.view()
    bound_tape = tape.bind(view, delay)
    bound_prices = prices.bind(view)
    bound_funding = funding.bind(view)
    account = Subaccount(capital)
    engine = Engine(
        account=account,
        prices=bound_prices,
        lots=lots,
        reference=reference,
        universe=universe,
        frictions=frictions,
        mirror=mirror,
    )

    payments: list[FundingPayment] = []
    curve: list[tuple[Ms, float]] = [(start, capital)]
    waiting: list[
        tuple[Ms, Ms, str, int, LeaderEvent, Ms]
    ] = []  # (tau, t, ativo, n, evento, nominal)
    executed: set[tuple[Ms, str]] = set()
    counter = 0
    consumed = 0
    last_read = Ms(start - 1)
    next_hour = _first_hour_at_or_after(start)
    next_midnight = day_start(utc_day(start) + 1)
    max_leverage = 0.0
    max_leverage_at: Ms | None = None
    frozen_at: Ms | None = None
    last_marks: dict[str, float] = {}
    last_equity = capital

    def observe(t: Ms) -> float:
        """Marca a subconta em ``t``: patrimônio, alavancagem e congelamento."""
        nonlocal max_leverage, max_leverage_at, frozen_at, last_marks, last_equity
        marks = engine.marks(t)
        equity = account.equity(marks)
        last_marks, last_equity = marks, equity
        if equity <= 0.0:
            frozen_at = frozen_at if frozen_at is not None else t
        elif marks:
            leverage = account.gross_exposure(marks) / equity
            if leverage > max_leverage:
                max_leverage, max_leverage_at = leverage, t
        return equity

    def is_frozen() -> bool:
        return frozen_at is not None

    while not is_frozen():
        wake = bound_tape.next_wake(last_read)
        candidates = [end, next_midnight]
        if wake is not None:
            candidates.append(Ms(wake + delay))
        if waiting:
            candidates.append(waiting[0][0])
        if frictions.funding:
            candidates.append(next_hour)
        now = Ms(min(candidates))
        if now >= end:
            break
        cursor.advance(now)

        # 1. Funding da hora cheia, sobre as posições abertas.
        if frictions.funding and now == next_hour:
            for coin in account.open_coins():
                rate = bound_funding.rate(coin, now)
                mark = bound_prices.mark(coin, now)
                size = account.size(coin)
                amount = account.pay_funding(coin, mark, rate)
                payments.append(FundingPayment(now, coin, size, mark, rate, amount))
            next_hour = Ms(next_hour + MS_PER_HOUR)
            observe(now)
            if is_frozen():
                break

        # 2. Execuções. Primeiro lê o que acabou de chegar ao instante nominal.
        if wake is not None and now == wake + delay:
            prefix = bound_tape.until(Ms(now - delay))
            fresh = prefix[consumed:]
            consumed = len(prefix)
            last_read = Ms(now - delay)
            for event in fresh:
                if not window.contains(event.t) or event.coin not in universe:
                    continue
                tau = bound_prices.available_from(event.coin, now)
                if tau is None or tau >= end:
                    continue  # pendente: nunca executa dentro da janela
                counter += 1
                heapq.heappush(waiting, (tau, event.t, event.coin, counter, event, now))
        while waiting and waiting[0][0] == now:
            *_, event, nominal = heapq.heappop(waiting)
            engine.process(event, nominal, now)
            executed.add((event.t, event.coin))
            if engine.frozen:
                frozen_at = now
                break
        if is_frozen():
            break

        # 3. Amostra diária de patrimônio.
        equity = observe(now)
        if now == next_midnight:
            curve.append((now, equity))
            next_midnight = Ms(next_midnight + MS_PER_DAY)

    if not is_frozen():
        cursor.advance(end)
        observe(end)
        curve.append((end, last_equity))
    elif frozen_at is not None and curve[-1][0] != frozen_at:
        last_marks = engine.marks(frozen_at)
        last_equity = account.equity(last_marks)
        curve.append((frozen_at, last_equity))
    cursor.close()

    pending = tuple(
        e
        for e in bound_tape.all_events()
        if window.contains(e.t) and e.coin in universe and (e.t, e.coin) not in executed
    )
    for event in pending:
        engine.counters.not_copied(PENDING, event.notional)

    reconciliation = reconcile(capital, last_equity, engine.orders, payments, last_marks)
    if not reconciliation.ok:
        raise SimulationError(
            f"A identidade de conciliação não fecha: resíduo {reconciliation.residual} "
            f"sobre a escala {reconciliation.scale} (RF-SIM-06 CA-06.2)."
        )
    return SubaccountResult(
        orders=tuple(engine.orders),
        payments=tuple(payments),
        equity_curve=tuple(curve),
        max_leverage=max_leverage,
        max_leverage_at=max_leverage_at,
        counters=engine.counters,
        final_positions=account.positions(),
        final_equity=last_equity,
        realized=account.realized,
        unrealized=account.unrealized(last_marks),
        fees=account.fees,
        funding_paid=account.funding_paid,
        pending=pending,
        frozen=frozen_at is not None,
        frozen_at=frozen_at,
        reconciliation=reconciliation,
    )
