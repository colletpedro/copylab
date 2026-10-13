"""Carteira, coorte e benchmark (RF-SIM-07, RF-ANA-02 CA-02.1; design §3.8, precisões do 1.6).

As subcontas são independentes (cada líder da coorte numa subconta de ``C / K``, sem compensar
posições), e a carteira é a soma delas, dia a dia, mais o capital parado quando a coorte é menor
que K. O benchmark é uma subconta sintética que compra BTC a 1x pelo mesmo laço do simulador.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from copylab.analytics.metrics import (
    Metrics,
    build_metrics,
    copied_episodes,
    subaccount_metrics,
)
from copylab.exceptions import ConfigError, SimulationError
from copylab.leader import LeaderEvent
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.prices import PriceFeed
from copylab.sim.tape import LeaderTape
from copylab.timeutil import Ms
from copylab.windows import Window

__all__ = [
    "BENCHMARK_COIN",
    "PortfolioResult",
    "benchmark_buy_and_hold",
    "portfolio",
    "run_cohort",
]

#: O ativo do benchmark de RF-ANA-02 CA-02.1: comprar e manter BTC perpétuo.
BENCHMARK_COIN = "BTC"

#: Folga relativa de ponto flutuante no capital parado.
_IDLE_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    """A carteira: as subcontas, o capital parado, a curva somada e as métricas dela."""

    capital: float
    idle: float
    subaccounts: tuple[SubaccountResult, ...]
    sub_metrics: tuple[Metrics, ...]
    equity_curve: tuple[tuple[Ms, float], ...]
    metrics: Metrics

    @property
    def net_return(self) -> float:
        return self.metrics.net_return

    @property
    def any_frozen(self) -> bool:
        return any(m.frozen for m in self.sub_metrics)


def portfolio(
    subaccounts: Sequence[SubaccountResult], capital: float, periods_per_year: int
) -> PortfolioResult:
    """A carteira de uma coorte (RF-SIM-07 CA-07.1 e CA-07.2).

    O patrimônio em cada instante é a soma dos patrimônios das subcontas, mais o capital parado,
    ``capital - Σ capital inicial das subcontas``. Cada subconta vale, em cada instante, o último
    ponto da curva dela até ali, e a que congelou segue com o valor real do congelamento.

    Raises:
        ConfigError: sem subconta, capital não positivo, subcontas de janelas diferentes, ou
            subcontas que somam mais capital que a carteira.
    """
    if not subaccounts:
        raise ConfigError("Uma carteira precisa de ao menos uma subconta.")
    if not capital > 0.0:
        raise ConfigError(f"O capital da carteira precisa ser positivo: {capital}.")
    curves = [r.equity_curve for r in subaccounts]
    if len({c[0][0] for c in curves}) != 1:
        raise ConfigError("As subcontas de uma carteira começam em instantes diferentes.")
    if len({r.equity_curve[-1][0] for r in subaccounts if not r.frozen}) > 1:
        raise ConfigError("As subcontas de uma carteira terminam em instantes diferentes.")
    invested = sum(c[0][1] for c in curves)
    idle = capital - invested
    if idle < -_IDLE_TOLERANCE * capital:
        raise ConfigError(
            f"As subcontas somam {invested} de capital, mais que os {capital} da carteira."
        )
    idle = max(idle, 0.0)

    instants = sorted({t for curve in curves for t, _ in curve})
    positions = [0] * len(curves)
    summed: list[tuple[Ms, float]] = []
    for t in instants:
        total = idle
        for k, curve in enumerate(curves):
            while positions[k] + 1 < len(curve) and curve[positions[k] + 1][0] <= t:
                positions[k] += 1
            total += curve[positions[k]][1]
        summed.append((t, total))

    sub_metrics = tuple(subaccount_metrics(r, periods_per_year) for r in subaccounts)
    episodes = [e for r in subaccounts for e in copied_episodes(r.orders, r.payments)]
    peak = max(subaccounts, key=lambda r: r.max_leverage)
    metrics = build_metrics(
        capital=capital,
        curve=summed,
        episodes=episodes,
        notional=sum(o.notional for r in subaccounts for o in r.orders),
        fees=sum(r.fees for r in subaccounts),
        funding=sum(r.funding_paid for r in subaccounts),
        max_leverage=peak.max_leverage,
        max_leverage_at=peak.max_leverage_at,
        frozen=any(r.frozen for r in subaccounts),
        periods_per_year=periods_per_year,
    )
    return PortfolioResult(
        capital=capital,
        idle=idle,
        subaccounts=tuple(subaccounts),
        sub_metrics=sub_metrics,
        equity_curve=tuple(summed),
        metrics=metrics,
    )


def run_cohort[M](
    members: Sequence[M],
    capital: float,
    k: int,
    simulate: Callable[[M, float], SubaccountResult],
    periods_per_year: int,
) -> PortfolioResult | None:
    """Copia os ``k`` primeiros membros da coorte, cada um numa subconta de ``capital / k``.

    Se a coorte tem menos de ``k`` membros, cada subconta continua com ``capital / k`` e o resto
    fica parado em caixa, dentro do patrimônio da carteira (RF-SIM-07 CA-07.1). Coorte vazia
    devolve ``None``, que o veredito trata como critério não atingido.

    Raises:
        ConfigError: ``k`` menor que 1, capital não positivo, ou uma subconta simulada com
            capital diferente de ``capital / k``.
    """
    if k < 1:
        raise ConfigError(f"K precisa ser ao menos 1: {k}.")
    if not capital > 0.0:
        raise ConfigError(f"O capital da carteira precisa ser positivo: {capital}.")
    chosen = members[:k]
    if not chosen:
        return None
    share = capital / k
    results = [simulate(member, share) for member in chosen]
    for result in results:
        start_capital = result.equity_curve[0][1]
        if abs(start_capital - share) > _IDLE_TOLERANCE * capital:
            raise SimulationError(
                f"Uma subconta começou com {start_capital}, e não com {share} (capital / K)."
            )
    return portfolio(results, capital, periods_per_year)


def benchmark_buy_and_hold(
    prices: PriceFeed,
    funding: FundingTable,
    lots: Mapping[str, float],
    capital: float,
    window: Window,
    frictions: Frictions,
    mirror: Mirror,
) -> SubaccountResult:
    """Comprar e manter BTC perpétuo a 1x com o capital inteiro (RF-ANA-02 CA-02.1).

    É uma subconta sintética pelo mesmo laço: um evento de compra em ``window.start``, executado
    em ``início + Δ`` na mesma fonte de preço, com a mesma taxa, o mesmo slippage de BTC e o mesmo
    funding do cenário, marcada no fim. O alvo é o patrimônio inteiro (``peak = 1``, razão 1); o
    passo 8 do espelhamento e o lote cortam o resto, inclusive o encolhimento pela taxa. As
    restrições de tamanho ficam sempre ligadas, e ``mirror`` entrega só o teto e a ordem mínima.
    """
    event = LeaderEvent(
        t=window.start,
        coin=BENCHMARK_COIN,
        kind="perp",
        prev_position=0.0,
        position=1.0,
        touched_zero=True,
        px=1.0,
        notional=1.0,
        unobserved=False,
        n_fills=1,
    )
    return run_subaccount(
        LeaderTape([event]),
        1.0,
        frozenset({BENCHMARK_COIN}),
        prices,
        funding,
        lots,
        capital,
        window,
        replace(frictions, size_constraints=True),
        Mirror(peak=1.0, cap=mirror.cap, min_notional=mirror.min_notional, long_only=False),
    )
