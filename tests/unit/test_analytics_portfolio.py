"""Carteira, subcontas e benchmark (T-051; RF-SIM-07 CA-07.1 e CA-07.2, RF-ANA-02 CA-02.1).

Fixtures de papel (RNF-03): preços e eventos escritos à mão, com a conta do valor esperado na
docstring. Nenhum dado real. As subcontas vêm do simulador do Bloco D.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.analytics.portfolio` (cada uma está na docstring do teste que a pega).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from copylab.analytics.portfolio import (
    BENCHMARK_COIN,
    PortfolioResult,
    benchmark_buy_and_hold,
    portfolio,
    run_cohort,
)
from copylab.exceptions import ConfigError, SimulationError
from copylab.leader import LeaderEvent
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.prices import ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms
from copylab.windows import Window

DAY = MS_PER_DAY
HOUR = MS_PER_HOUR
PERIODS = 365


def ev(t: int, coin: str, position: float, px: float = 100.0) -> LeaderEvent:
    return LeaderEvent(
        t=Ms(t),
        coin=coin,
        kind="perp",
        prev_position=0.0,
        position=position,
        touched_zero=True,
        px=px,
        notional=abs(position) * px,
        unobserved=False,
        n_fills=1,
    )


def sparse(points: Mapping[int, float]) -> list[ProxyBar]:
    """Barras só nos segundos dados; a marcação usa a última barra anterior."""
    return [ProxyBar(s, p, p, p) for s, p in sorted(points.items())]


@dataclass(frozen=True)
class Leader:
    """Um líder de papel: os eventos, os preços que ele vê e a referência de exposição."""

    events: Sequence[LeaderEvent]
    bars: Mapping[str, Sequence[ProxyBar]]
    reference: float


def simulate(leader: Leader, capital: float, end: int) -> SubaccountResult:
    """Subconta do líder com o capital dado, sem atraso, custo, funding nem restrição de
    tamanho (o alvo sai exato)."""
    return run_subaccount(
        LeaderTape(leader.events),
        leader.reference,
        frozenset(leader.bars),
        ProxySource(leader.bars),
        FundingTable({}),
        dict.fromkeys(leader.bars, 0.01),
        capital,
        Window(Ms(0), Ms(end)),
        Frictions(0, {}, 0.0, False, False),
        Mirror(1.0, 1.0, 10.0, False),
    )


def cohort(
    leaders: Sequence[Leader], capital: float, k: int, end: int = 400_000
) -> tuple[PortfolioResult, list[float]]:
    """A carteira da coorte e os capitais que `simulate` recebeu, na ordem."""
    shares: list[float] = []

    def run(leader: Leader, share: float) -> SubaccountResult:
        shares.append(share)
        return simulate(leader, share, end)

    result = run_cohort(leaders, capital, k, run, PERIODS)
    assert result is not None
    return result, shares


# ─── Subcontas independentes com C/K ─────────────────────────────────────────


@pytest.mark.unit
def test_subaccounts_are_independent_with_capital_over_k() -> None:
    """RF-SIM-07 CA-07.1. Capital 1.000, K = 2: duas subcontas de 500, sem compensar posições.
    O líder A compra 5 de `a` a 100 (referência 500: razão 5 x 100 / 500 = 1, alvo 500, tamanho 5);
    o líder B vende 5 de `a` a 100 (razão -1, alvo -500). Em 60 s o preço vai a 110.
      A: 500 + 5 x 10 = 550. B: 500 - 5 x 10 = 450. A soma é 1.000, retorno líquido zero, mas as
      posições seguem separadas: A comprado em 5 e B vendido em 5, sem netar.
      Alavancagem máxima observada: A 5 x 110 / 550 = 1; B 5 x 110 / 450 = 1,2222 no fim. A da
      carteira é a maior das subcontas (1,2222), e não a da posição líquida, que seria zero.
    Um terceiro membro da coorte, além de K = 2, não entra.

    Mutação registrada: simular cada subconta com o capital inteiro (`share = capital`) soma 2.000
    de capital em 1.000 e levanta `ConfigError`; copiar todos os membros (`members` no lugar de
    `members[:k]`) cria uma terceira subconta e o teste cai."""
    price = {"a": sparse({0: 100.0, 10: 100.0, 60: 110.0})}
    long_leader = Leader([ev(10_000, "a", 5.0)], price, 500.0)
    short_leader = Leader([ev(10_000, "a", -5.0)], price, 500.0)
    extra = Leader([ev(10_000, "a", 1.0)], price, 500.0)
    result, shares = cohort([long_leader, short_leader, extra], 1_000.0, 2)
    assert shares == [500.0, 500.0]
    assert len(result.subaccounts) == 2
    long_sub, short_sub = result.subaccounts
    assert long_sub.final_equity == pytest.approx(550.0)
    assert short_sub.final_equity == pytest.approx(450.0)
    assert long_sub.final_positions["a"][0] == pytest.approx(5.0)
    assert short_sub.final_positions["a"][0] == pytest.approx(-5.0)
    assert result.idle == 0.0
    assert result.metrics.final_equity == pytest.approx(1_000.0)
    assert result.net_return == pytest.approx(0.0)
    assert result.metrics.max_leverage == pytest.approx(5 * 110.0 / 450.0)
    assert result.metrics.max_leverage == max(m.max_leverage for m in result.sub_metrics)


@pytest.mark.unit
def test_subaccount_is_the_same_alone_or_in_the_cohort() -> None:
    """Independência: a subconta de um líder dentro da carteira é idêntica à que sai de simulá-lo
    sozinho com o mesmo capital. Capital 600, K = 3, cada uma com 200: o líder compra 2 de `a` a
    100 (referência 200, razão 1, alvo 200)."""
    price = {"a": sparse({0: 100.0, 10: 100.0, 60: 110.0})}
    first = Leader([ev(10_000, "a", 2.0)], price, 200.0)
    second = Leader([ev(20_000, "a", 1.0)], price, 100.0)
    result, _ = cohort([first, second], 600.0, 3)
    alone = simulate(first, 200.0, 400_000)
    assert result.subaccounts[0].orders == alone.orders
    assert result.subaccounts[0].equity_curve == alone.equity_curve


@pytest.mark.unit
def test_short_cohort_leaves_remaining_capital_idle() -> None:
    """RF-SIM-07 CA-07.1. Capital 500, K = 5: cada subconta tem 100. A coorte tem só 2 líderes,
    então 500 - 2 x 100 = 300 ficam parados em caixa, dentro do patrimônio da carteira. O líder A
    compra 1 de `a` a 100 (referência 100, razão 1, alvo 100) e o preço vai a 110: A vale
    100 + 10 = 110. O líder B não opera: 100. A carteira vale 300 + 110 + 100 = 510 e o retorno
    líquido é 10 / 500 = 0,02. A curva começa em 500, e não em 200.

    Mutação registrada: ignorar o capital parado (`idle = 0.0`) dá 210 de patrimônio e o teste
    cai."""
    price = {"a": sparse({0: 100.0, 10: 100.0, 60: 110.0})}
    buyer = Leader([ev(10_000, "a", 1.0)], price, 100.0)
    idle_leader = Leader([], price, 100.0)
    result, shares = cohort([buyer, idle_leader], 500.0, 5)
    assert shares == [100.0, 100.0]
    assert result.idle == pytest.approx(300.0)
    assert result.equity_curve[0][1] == pytest.approx(500.0)
    assert result.metrics.final_equity == pytest.approx(510.0)
    assert result.net_return == pytest.approx(0.02)
    assert not result.any_frozen


@pytest.mark.unit
def test_empty_cohort_has_no_portfolio_and_k_is_validated() -> None:
    """Coorte vazia não tem carteira (`None`), o que o veredito trata como critério não atingido.
    K menor que 1 e capital não positivo são erro de configuração. Uma simulação que não use o
    capital C/K é defeito de quem simula, e levanta `SimulationError`."""
    price = {"a": sparse({0: 100.0})}
    leader = Leader([], price, 100.0)

    def alone(member: Leader, capital: float) -> SubaccountResult:
        return simulate(member, capital, 400_000)

    def wrong_capital(member: Leader, capital: float) -> SubaccountResult:
        return simulate(member, 100.0, 400_000)

    assert run_cohort([], 100.0, 1, alone, PERIODS) is None
    with pytest.raises(ConfigError, match="K precisa"):
        run_cohort([leader], 100.0, 0, alone, PERIODS)
    with pytest.raises(ConfigError, match="capital"):
        run_cohort([leader], 0.0, 1, alone, PERIODS)
    with pytest.raises(SimulationError, match="capital / K"):
        run_cohort([leader], 100.0, 2, wrong_capital, PERIODS)


# ─── Patrimônio da carteira ──────────────────────────────────────────────────


@pytest.mark.unit
def test_portfolio_equity_is_sum_of_subaccounts() -> None:
    """RF-SIM-07 CA-07.2. Capital 600, K = 3: subcontas de 200 e 200 parados (só há 2 líderes), em
    3 dias UTC. O líder A compra 2 de `a` a 100 (referência 200, razão 1, alvo 200); o preço da
    última barra de cada dia é 105, 110 e 120: patrimônio 200 + 2 x (p - 100) = 210, 220, 240. O
    líder B vende 4 de `b` a 50 (razão 1, alvo -200); os preços são 48, 52 e 55: patrimônio
    200 - 4 x (p - 50) = 208, 192, 180. A carteira, dia a dia, mais os 200 parados:
      início 200 + 200 + 200 = 600; dia 1: 210 + 208 + 200 = 618; dia 2: 220 + 192 + 200 = 612;
      fim: 240 + 180 + 200 = 620.
    Retorno líquido 20 / 600.

    Mutação registrada: somar só a primeira subconta dá 410, 420 e 440 no fim, e o teste cai."""
    a = Leader(
        [ev(10_000, "a", 2.0)],
        {"a": sparse({0: 100.0, 10: 100.0, 40_000: 105.0, 100_000: 110.0, 200_000: 120.0})},
        200.0,
    )
    b = Leader(
        [ev(10_000, "b", -4.0, 50.0)],
        {"b": sparse({0: 50.0, 10: 50.0, 40_000: 48.0, 100_000: 52.0, 200_000: 55.0})},
        200.0,
    )
    result, _ = cohort([a, b], 600.0, 3, end=3 * DAY)
    assert [t for t, _ in result.equity_curve] == [0, DAY, 2 * DAY, 3 * DAY]
    assert [v for _, v in result.equity_curve] == pytest.approx([600.0, 618.0, 612.0, 620.0])
    assert result.net_return == pytest.approx(20.0 / 600.0)


@pytest.mark.unit
def test_frozen_subaccount_keeps_its_real_value_in_the_portfolio() -> None:
    """RF-SIM-06 CA-06.4 na carteira. Capital 2.000, K = 2. O líder A vende 10 de `a` a 100 em
    10 s; os preços de fim de dia são 110 e 120 e, em 250.000 s, 250: patrimônio 1.000 - 10 x (p -
    100) = 900, 800 e, no evento seguinte (250.000 s), -500, e a subconta congela ali. O líder B
    não opera: 1.000. A carteira vale 2.000, 1.900, 1.800, depois 500 no instante do congelamento
    (-500 + 1.000), e segue com o valor real da subconta congelada (-500) até o fim, e não com
    zero: 500 no dia 3 e no fim. O patrimônio da carteira é positivo, então o Sharpe é definido,
    mas `any_frozen` fica verdadeiro, e o veredito falha por isso (RF-ANA-05 CA-05.3).

    Mutação registrada: tratar a subconta congelada como zero depois do congelamento (valor 0 em
    vez do último ponto) dá 1.000 no dia 3 e no fim, e o teste cai."""
    bars_a = sparse({0: 100.0, 10: 100.0, 40_000: 110.0, 100_000: 120.0, 200_000: 250.0})
    bars_a.append(ProxyBar(250_000, 250.0, 250.0, 250.0))
    frozen = Leader([ev(10_000, "a", -10.0), ev(250_000_000, "a", -12.0)], {"a": bars_a}, 1_000.0)
    quiet = Leader([], {"a": sparse({0: 100.0})}, 1_000.0)
    result, _ = cohort([frozen, quiet], 2_000.0, 2, end=4 * DAY)
    assert result.subaccounts[0].frozen
    assert [t for t, _ in result.equity_curve] == [0, DAY, 2 * DAY, 250_000_000, 3 * DAY, 4 * DAY]
    assert [v for _, v in result.equity_curve] == pytest.approx(
        [2_000.0, 1_900.0, 1_800.0, 500.0, 500.0, 500.0]
    )
    assert result.any_frozen and result.metrics.frozen
    assert result.metrics.sharpe is not None


@pytest.mark.unit
def test_portfolio_refuses_inconsistent_subaccounts() -> None:
    """Sem subconta, capital não positivo, subcontas que somam mais capital que a carteira, e
    subcontas de janelas diferentes (começam ou terminam em instantes diferentes) são erro de
    configuração, e não uma carteira calculada com o que sobrar."""
    price = {"a": sparse({0: 100.0})}
    leader = Leader([], price, 100.0)
    one = simulate(leader, 100.0, 400_000)
    longer = simulate(leader, 100.0, 500_000)
    with pytest.raises(ConfigError, match="ao menos uma"):
        portfolio([], 100.0, PERIODS)
    with pytest.raises(ConfigError, match="positivo"):
        portfolio([one], 0.0, PERIODS)
    with pytest.raises(ConfigError, match="mais que"):
        portfolio([one, one], 100.0, PERIODS)
    with pytest.raises(ConfigError, match="terminam"):
        portfolio([one, longer], 200.0, PERIODS)
    shifted = run_subaccount(
        LeaderTape([]),
        100.0,
        frozenset({"a"}),
        ProxySource(price),
        FundingTable({}),
        {"a": 0.01},
        100.0,
        Window(Ms(1_000), Ms(400_000)),
        Frictions(0, {}, 0.0, False, False),
        Mirror(1.0, 1.0, 10.0, False),
    )
    with pytest.raises(ConfigError, match="começam"):
        portfolio([one, shifted], 200.0, PERIODS)


# ─── Benchmark: comprar e manter BTC a 1x ────────────────────────────────────

BTC_LOT = 0.001
BENCH_END = 3 * HOUR


def bench(
    *,
    frictions: Frictions,
    mirror: Mirror | None = None,
    bars: Sequence[ProxyBar] | None = None,
    end: int = BENCH_END,
) -> SubaccountResult:
    """Benchmark de capital 1.000 sobre BTC: 100 até 4.000 s, 102 até 8.000 s, 110 depois, com
    taxas de funding de 0,0001 em 1 h e -0,0003 em 2 h."""
    feed = ProxySource(
        {BENCHMARK_COIN: bars or sparse({0: 100.0, 5: 100.0, 4_000: 102.0, 8_000: 110.0})}
    )
    rates = {BENCHMARK_COIN: {Ms(HOUR): 0.0001, Ms(2 * HOUR): -0.0003}}
    return benchmark_buy_and_hold(
        feed,
        FundingTable(rates),
        {BENCHMARK_COIN: BTC_LOT},
        1_000.0,
        Window(Ms(0), Ms(end)),
        frictions,
        mirror or Mirror(1.0, 1.0, 10.0, False),
    )


FULL = Frictions(delay_ms=5_000, slippage_bps={"BTC": 20.0}, fee_bps=10.0, funding=True,
                 size_constraints=True)  # fmt: skip


@pytest.mark.unit
def test_benchmark_buy_and_hold_btc_same_costs_and_funding() -> None:
    """RF-ANA-02 CA-02.1. Capital 1.000, Δ = 5 s, slippage de BTC 20 bps, taxa 10 bps, lote 0,001,
    funding ligado. A compra sai em 5 s, ao máximo do segundo (100) mais o slippage: cotação
    100 x 1,002 = 100,2. Passo 8: o notional X que cabe é (1 x 1.000) / (1 + 1 x 0,001) =
    999,001, tamanho 999,001 / 100,2 = 9,97007, arredondado para baixo ao lote: 9,970 (9,971 já
    passaria do teto depois da taxa). Notional 9,97 x 100,2 = 998,994 e taxa 0,998994.
    Funding (a taxa vezes o tamanho e a marcação da hora): em 1 h, 9,97 x 100 x 0,0001 = 0,0997
    pagos; em 2 h, a marcação é 102 e a taxa é negativa, -0,0003: 9,97 x 102 x (-0,0003) =
    -0,305082, que o seguidor recebe. A hora 3 h é o fim da janela e fica de fora. Funding pago
    líquido: 0,0997 - 0,305082 = -0,205382.
    No fim, a marcação é 110: não realizado 9,97 x (110 - 100,2) = 97,706. Patrimônio final =
    1.000 - 0,998994 + 0,205382 + 97,706 = 1.096,912388.

    Mutação registrada: tirar o slippage ou a taxa da fonte do benchmark muda o tamanho e o
    patrimônio e o teste cai; dimensionar o benchmark pelo `peak` do espelhamento (0,5) no lugar
    de 1x também."""
    result = bench(frictions=FULL)
    (order,) = result.orders
    assert (order.exec_t, order.side) == (5_000, "buy")
    assert order.executed == pytest.approx(9.97)
    assert order.price == pytest.approx(100.2)
    assert order.fee == pytest.approx(0.998994)
    assert [p.amount for p in result.payments] == pytest.approx([0.0997, -0.305082])
    assert result.funding_paid == pytest.approx(-0.205382)
    assert result.final_equity == pytest.approx(1_096.912388)
    assert result.reconciliation.ok
    # O benchmark é 1x do capital: o `peak` do espelhamento do cenário não o dimensiona.
    half = bench(frictions=FULL, mirror=Mirror(0.5, 1.0, 10.0, False))
    assert half.final_equity == pytest.approx(result.final_equity)


@pytest.mark.unit
def test_benchmark_with_negative_funding_credits_the_long() -> None:
    """Funding negativo: a taxa de -0,0003 em 2 h faz o comprado receber. Sem funding, o
    patrimônio final é 1.000 - 0,998994 + 97,706 = 1.096,707006; com funding, 1.096,912388. A
    diferença, 0,205382, é exatamente o funding líquido recebido (a hora de 1 h paga 0,0997 e a
    de 2 h recebe 0,305082).

    Mutação registrada: debitar o funding com o sinal trocado (`self.cash += amount` em
    `Subaccount.pay_funding`) dá 1.096,5016 e o teste cai."""
    with_funding = bench(frictions=FULL)
    without = bench(frictions=Frictions(5_000, {"BTC": 20.0}, 10.0, False, True))
    assert without.final_equity == pytest.approx(1_096.707006)
    assert with_funding.final_equity - without.final_equity == pytest.approx(0.205382)
    assert with_funding.funding_paid < 0.0 < with_funding.payments[0].amount


@pytest.mark.unit
def test_benchmark_always_sizes_with_lot_and_cap_and_waits_the_scenario_delay() -> None:
    """O benchmark tem sempre lote e teto, mesmo que o `Frictions` recebido os desligue (o passo
    de decomposição sem restrições não é o benchmark): com `size_constraints = False` o tamanho
    seria 1.000 / 100,2 = 9,98004, e o lote o leva a 9,970. A compra acontece em `início + Δ`:
    com Δ = 30 s, em 30 s, ao preço do segundo (100, a barra de 30 s)."""
    off = Frictions(30_000, {"BTC": 20.0}, 10.0, False, False)
    bars = sparse({0: 100.0, 30: 100.0, 4_000: 102.0, 8_000: 110.0})
    result = bench(frictions=off, bars=bars)
    (order,) = result.orders
    assert order.exec_t == 30_000
    assert order.executed == pytest.approx(9.97)
    assert math.isclose(order.executed / BTC_LOT, round(order.executed / BTC_LOT))


@pytest.mark.unit
def test_benchmark_without_btc_price_is_pending_and_flat() -> None:
    """Se o BTC não tem preço até o fim da janela, o evento fica pendente: nenhuma ordem, o
    patrimônio é o capital, e o resultado mostra o evento pendente em vez de inventar preço. A
    série só tem barras a partir de 5.000 s, depois do fim da janela (1.000 s)."""
    result = bench(frictions=FULL, bars=sparse({5_000: 100.0}), end=1_000_000)
    assert result.orders == ()
    assert len(result.pending) == 1
    assert result.final_equity == pytest.approx(1_000.0)
