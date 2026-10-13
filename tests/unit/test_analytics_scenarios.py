"""Grade, referência de Δ = 0, decomposição e aviso de cenário irrealista (T-052; RF-SIM-08,
RF-SIM-04 CA-04.2, RF-ANA-02 CA-02.2, RF-ANA-03).

Fixtures de papel (RNF-03): preços e eventos escritos à mão, com a conta do valor esperado na
docstring. Nenhum dado real. A grade usa os parâmetros pré-registrados do repositório
(`preregistro/parametros.toml`), que não são dado de mercado.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.analytics.scenarios` (cada uma está na docstring do teste que a pega).
"""

from dataclasses import replace

import pytest

from copylab.analytics.portfolio import PortfolioResult, portfolio
from copylab.analytics.scenarios import (
    Grid,
    Route,
    Scenario,
    decomposition,
    decomposition_total,
    delay_reference,
    frictions_for,
    mirror_for,
    run_grid,
    scenarios,
    unrealistic_warnings,
)
from copylab.exceptions import ConfigError
from copylab.leader import LeaderEvent
from copylab.params import load_params
from copylab.sim.funding import FundingTable
from copylab.sim.loop import run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.prices import ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import MS_PER_HOUR, Ms
from copylab.windows import Window

PARAMS = load_params()
PERIODS = 365
END = 3 * MS_PER_HOUR


def event(t: int, coin: str, position: float, px: float = 100.0) -> LeaderEvent:
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


#: `a` vale 100 até 14 s, 110 de 15 s a 9.999 s e 120 depois. O funding das horas 1 e 2 é -0,001
#: (quem está comprado recebe), e a janela vai de 0 a 3 h.
BARS = {
    "a": [
        ProxyBar(0, 100.0, 100.0, 100.0),
        ProxyBar(10, 100.0, 100.0, 100.0),
        ProxyBar(15, 110.0, 110.0, 110.0),
        ProxyBar(10_000, 120.0, 120.0, 120.0),
    ]
}
RATES = {"a": {Ms(MS_PER_HOUR): -0.001, Ms(2 * MS_PER_HOUR): -0.001}}


def simulate(frictions: Frictions) -> PortfolioResult:
    """Uma subconta de capital 1.000 (K = 1) que copia o líder que compra 10 de `a` a 100 em 10 s
    (referência 1.000: razão 1, alvo 1.000), com lote de 0,1 e ordem mínima de 10."""
    sub = run_subaccount(
        LeaderTape([event(10_000, "a", 10.0)]),
        1_000.0,
        frozenset({"a"}),
        ProxySource(BARS),
        FundingTable(RATES),
        {"a": 0.1},
        1_000.0,
        Window(Ms(0), Ms(END)),
        frictions,
        Mirror(1.0, 1.0, 10.0, False),
    )
    return portfolio([sub], 1_000.0, PERIODS)


PRIMARY = Frictions(delay_ms=5_000, slippage_bps={"a": 100.0}, fee_bps=10.0, funding=True,
                    size_constraints=True)  # fmt: skip


def fake(net_return: float) -> PortfolioResult:
    """Uma carteira de capital 100 cujo retorno líquido é o dado, sem passar pelo laço."""
    base = run_subaccount(
        LeaderTape([]),
        1.0,
        frozenset({"a"}),
        ProxySource(BARS),
        FundingTable({}),
        {"a": 0.1},
        100.0,
        Window(Ms(0), Ms(END)),
        Frictions(0, {}, 0.0, False, False),
        Mirror(1.0, 1.0, 10.0, False),
    )
    final = 100.0 * (1.0 + net_return)
    sub = replace(base, equity_curve=((Ms(0), 100.0), (Ms(END), final)), final_equity=final)
    return portfolio([sub], 100.0, PERIODS)


# ─── Grade (RF-SIM-08) ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_grid_has_eleven_scenarios_in_route_a_and_nine_in_route_b() -> None:
    """RF-SIM-08 CA-08.1, §7.2. Os nove pares de capital (50, 100, 500, com K = 1, 2, 5) e Δ (1, 5,
    30 s), com o slippage primário (multiplicador 1). Na Rota A, mais a sensibilidade de slippage
    no capital e no Δ primários (50, K = 1, 5 s): multiplicador 0 e multiplicador 2. 9 + 2 = 11 na
    Rota A e 9 na Rota B, que não tem slippage. O primário é um só: capital 50, Δ 5 s, multiplicador
    1.

    Mutação registrada: gerar a sensibilidade também na Rota B (tirar o `if route == "A"`) dá 11
    cenários nela, e o teste cai."""
    a = scenarios("A", PARAMS)
    b = scenarios("B", PARAMS)
    assert (len(a), len(b)) == (11, 9)
    assert {(s.capital, s.k) for s in a} == {(50.0, 1), (100.0, 2), (500.0, 5)}
    assert [(s.capital, s.delay_ms, s.slippage_multiplier) for s in a[:9]] == [
        (c, d, 1.0) for c in (50.0, 100.0, 500.0) for d in (1_000, 5_000, 30_000)
    ]
    assert [(s.capital, s.k, s.delay_ms, s.slippage_multiplier) for s in a[9:]] == [
        (50.0, 1, 5_000, 0.0),
        (50.0, 1, 5_000, 2.0),
    ]
    assert all(s.slippage_multiplier == 1.0 for s in b)
    for grid in (a, b):
        primary = [s for s in grid if s.primary]
        assert primary == [Scenario(50.0, 1, 5_000, 1.0, primary=True)]


_ROUTES: tuple[tuple[Route, int], ...] = (("A", 22), ("B", 18))


def _run_recorded_grid(route: Route) -> tuple[Grid, list[tuple[Scenario, bool]]]:
    """Roda a grade com um `run` que devolve um retorno que identifica o cenário (capital / 1.000 +
    Δ / 1e6) e a variante (+0,5 só compras), e registra as chamadas."""
    calls: list[tuple[Scenario, bool]] = []

    def run(scenario: Scenario, long_only: bool) -> PortfolioResult | None:
        calls.append((scenario, long_only))
        return fake(
            scenario.capital / 1_000.0 + scenario.delay_ms / 1e6 + (0.5 if long_only else 0.0)
        )

    return run_grid(run, route, PARAMS), calls


@pytest.mark.unit
def test_grid_runs_every_scenario_and_only_primary_feeds_verdict() -> None:
    """RF-SIM-08 CA-08.1. `run_grid` roda cada cenário duas vezes, copia completa e só compras
    (11 x 2 = 22 execuções na Rota A, 18 na B), na ordem da grade, e a grade inteira fica na
    resposta. Só a célula primária alimenta o veredito: `Grid.primary` é a do cenário primário, e
    nenhuma outra. Cada execução devolve um retorno que identifica o cenário e a variante, para
    provar que a célula primária traz a cópia completa do cenário primário.

    Mutação registrada: marcar como primário o último cenário (Δ = 30 s) no lugar do de Δ = 5 s, ou
    pular a variante só compras, faz o teste cair."""
    for route, expected in _ROUTES:
        grid, calls = _run_recorded_grid(route)
        assert len(calls) == expected
        assert [(c.scenario, False) for c in grid.cells] == [(s, lo) for s, lo in calls if not lo]
        assert sum(c.scenario.primary for c in grid.cells) == 1
        primary = grid.primary
        assert primary.scenario == Scenario(50.0, 1, 5_000, 1.0, primary=True)
        assert primary.full is not None and primary.long_only is not None
        assert primary.full.net_return == pytest.approx(0.05 + 0.005)
        assert primary.long_only.net_return == pytest.approx(0.05 + 0.005 + 0.5)


@pytest.mark.unit
def test_grid_refuses_a_grid_without_exactly_one_primary() -> None:
    """Uma grade sem cenário primário (parâmetros com o primário fora da grade) é erro de
    configuração. Os parâmetros já recusam isso ao carregar; aqui a guarda do `run_grid`."""
    other = PARAMS.model_copy(
        update={"capital": PARAMS.capital.model_copy(update={"primary_usd": 999.0})}
    )
    with pytest.raises(ConfigError, match="primário"):
        run_grid(lambda s, lo: None, "B", other)


@pytest.mark.unit
def test_frictions_and_mirror_follow_the_frozen_parameters() -> None:
    """Os atritos do cenário vêm dos parâmetros: o atraso dele, o slippage primário vezes o
    multiplicador (100 bps vezes 2 = 200; vezes 0 = 0), a taxa de 4,5 bps, funding e restrições
    ligados. Na Rota B o mapa primário é vazio e continua vazio. O espelhamento vem de `[mirror]`:
    pico 1, teto 1, ordem mínima 10."""
    double = Scenario(50.0, 1, 5_000, 2.0, primary=False)
    zero = Scenario(50.0, 1, 5_000, 0.0, primary=False)
    f = frictions_for(double, {"BTC": 100.0, "ETH": 3.0}, PARAMS)
    assert (f.delay_ms, f.fee_bps, f.funding, f.size_constraints) == (5_000, 4.5, True, True)
    assert dict(f.slippage_bps) == {"BTC": 200.0, "ETH": 6.0}
    assert dict(frictions_for(zero, {"BTC": 100.0}, PARAMS).slippage_bps) == {"BTC": 0.0}
    assert dict(frictions_for(double, {}, PARAMS).slippage_bps) == {}
    assert mirror_for(PARAMS, long_only=False) == Mirror(1.0, 1.0, 10.0, False)
    assert mirror_for(PARAMS, long_only=True).long_only


# ─── Referência de Δ = 0 (RF-ANA-02 CA-02.2) ─────────────────────────────────


@pytest.mark.unit
def test_zero_delay_reference_uses_same_price_source() -> None:
    """RF-ANA-02 CA-02.2. O líder compra 10 de `a` a 100 em 10 s (alvo 1.000) e o preço de `a` é
    100 até 14 s, 110 de 15 s e 120 no fim. Sem custo, funding nem restrição de tamanho. Com Δ = 0
    a compra sai em 10 s a 100: tamanho 1.000 / 100 = 10, ganho 10 x (120 - 100) = 200, retorno
    0,2. Com Δ = 5 s sai em 15 s a 110: 1.000 / 110 = 9,0909, ganho 9,0909 x 10 = 90,909, retorno
    0,0909. A referência roda o mesmo cenário (mesma coorte e mesma fonte de preço, a de `run`)
    com só o atraso zerado.

    Mutação registrada: zerar também a taxa na referência, ou não zerar o atraso, muda o retorno
    (a segunda dá 0,0909 no lugar de 0,2) e o teste cai."""
    primary = Frictions(5_000, {}, 0.0, False, False)
    seen: list[Frictions] = []

    def run(f: Frictions) -> PortfolioResult:
        seen.append(f)
        return simulate(f)

    reference = delay_reference(run, primary)
    assert seen == [replace(primary, delay_ms=0)]
    assert reference.net_return == pytest.approx(0.2)
    assert simulate(primary).net_return == pytest.approx(1_000.0 / 110.0 * 10.0 / 1_000.0)
    # Os custos do cenário seguem na referência: só o atraso muda.
    with_costs = replace(PRIMARY, delay_ms=3_000)
    delay_reference(run, with_costs)
    assert seen[-1] == replace(with_costs, delay_ms=0)


# ─── Decomposição (RF-ANA-03) ────────────────────────────────────────────────


@pytest.mark.unit
def test_decomposition_has_six_steps_in_fixed_order() -> None:
    """RF-ANA-03 CA-03.1. Seis simulações, cada uma com um fator a mais, na ordem: (1) cópia ideal
    (Δ = 0, sem slippage, taxa, funding nem restrição de tamanho); (2) atraso; (3) slippage; (4)
    taxas; (5) funding; (6) lote, ordem mínima e teto, que é o cenário primário completo. Cada
    degrau liga só o fator novo, e os já ligados continuam ligados.

    Mutação registrada: trocar a ordem do slippage e das taxas, ou ligar o funding já no degrau
    4, faz o teste cair."""
    seen: list[Frictions] = []

    def run(f: Frictions) -> PortfolioResult:
        seen.append(f)
        return fake(0.0)

    steps = decomposition(run, PRIMARY)
    assert [s.name for s in steps] == [
        "ideal", "delay", "slippage", "fees", "funding", "size_constraints"
    ]  # fmt: skip
    assert seen == [s.frictions for s in steps]
    ideal, delay, slip, fees, funding, full = (s.frictions for s in steps)
    assert ideal == Frictions(0, {}, 0.0, False, False)
    assert delay == Frictions(5_000, {}, 0.0, False, False)
    assert slip == Frictions(5_000, {"a": 100.0}, 0.0, False, False)
    assert fees == Frictions(5_000, {"a": 100.0}, 10.0, False, False)
    assert funding == Frictions(5_000, {"a": 100.0}, 10.0, True, False)
    assert full == PRIMARY


@pytest.mark.unit
def test_decomposition_step_differences_sum_to_total() -> None:
    """RF-ANA-03 CA-03.2, com o laço de verdade. O líder compra 10 de `a` a 100 em 10 s (alvo
    1.000); `a` vale 100 até 14 s, 110 até 9.999 s e 120 no fim; funding de -0,001 nas horas 1 e
    2; lote 0,1. Capital 1.000. Cenário primário: Δ = 5 s, slippage de 100 bps, taxa de 10 bps.
      1. Ideal: compra 1.000 / 100 = 10 a 100, ganho 10 x 20 = 200. Retorno 0,2.
      2. Atraso: compra em 15 s a 110: 1.000 / 110 = 9,0909, ganho 9,0909 x 10 = 90,909. 0,090909.
      3. Slippage: preço 110 x 1,01 = 111,1, tamanho 1.000 / 111,1 = 9,0009, ganho 9,0009 x
         (120 - 111,1) = 80,108. 0,080108.
      4. Taxas: 0,001 x 1.000 = 1 de taxa: 79,108. 0,079108.
      5. Funding: posição comprada, taxa negativa: recebe 2 x 9,0009 x 110 x 0,001 = 1,98020, e o
         retorno sobe para 0,081088 (o degrau melhora).
      6. Lote, mínimo e teto: o teto com a taxa limita o tamanho a 1.000 / (111,1 x 1,001) =
         8,9919, que o lote de 0,1 leva a 8,9: ganho 8,9 x 8,9 = 79,21, taxa 0,001 x 8,9 x 111,1 =
         0,98879, funding recebido 2 x 8,9 x 110 x 0,001 = 1,958. 1.000 + 79,21 - 0,98879 + 1,958
         = 1.080,17921: 0,080179.
    Diferenças: -0,109091; -0,010801; -0,001; +0,001980; -0,000909. A soma, -0,119821, é o último
    menos o primeiro: 0,080179 - 0,2. O funding melhora o resultado depois de a taxa piorá-lo.

    Mutação registrada: calcular a diferença contra o primeiro degrau (`steps[0]`) no lugar do
    anterior, ou pular o último degrau na soma, faz o teste cair."""
    steps = decomposition(simulate, PRIMARY)
    returns = [s.net_return for s in steps]
    assert returns == pytest.approx(
        [0.2, 0.090909, 0.0801080, 0.0791080, 0.0810882, 0.0801792], abs=1e-6
    )
    deltas = [s.delta for s in steps]
    assert deltas[0] is None
    assert deltas[1:] == pytest.approx(
        [-0.1090909, -0.0108011, -0.001, 0.0019802, -0.0009090], abs=1e-6
    )
    assert deltas[4] is not None and deltas[3] is not None and deltas[3] < 0.0 < deltas[4]
    total = decomposition_total(steps)
    assert total == pytest.approx(returns[-1] - returns[0])
    assert sum(d for d in deltas if d is not None) == pytest.approx(total)
    assert total == pytest.approx(-0.1198208, abs=1e-6)
    assert steps[-1].result.net_return == pytest.approx(simulate(PRIMARY).net_return)
    assert all(s.inert is None for s in steps)


@pytest.mark.unit
def test_decomposition_differences_with_a_step_that_worsens_then_one_that_improves() -> None:
    """RF-ANA-03 CA-03.2 com retornos escritos à mão: 0,10; 0,04; 0,03; 0,025; 0,03; 0,028. As
    diferenças são -0,06; -0,01; -0,005; +0,005; -0,002 (o funding melhora depois de a taxa
    piorar), e a soma é -0,072 = 0,028 - 0,10, tanto com quedas como com um aumento no meio."""
    values = iter([0.10, 0.04, 0.03, 0.025, 0.03, 0.028])
    steps = decomposition(lambda f: fake(next(values)), PRIMARY)
    deltas = [s.delta for s in steps[1:]]
    assert deltas == pytest.approx([-0.06, -0.01, -0.005, 0.005, -0.002])
    assert sum(d for d in deltas if d is not None) == pytest.approx(-0.072)
    assert decomposition_total(steps) == pytest.approx(-0.072)


@pytest.mark.unit
def test_decomposition_slippage_step_is_inert_in_route_b() -> None:
    """RF-ANA-03, Rota B: o livro já é o preço real, o mapa de slippage é vazio, e o degrau do
    slippage roda a mesma simulação do degrau do atraso: diferença exatamente zero, marcado como
    sem efeito (`no_slippage`) para o relatório explicar por quê. Os demais degraus seguem com
    efeito (`inert` ausente).

    Mutação registrada: marcar `inert` quando o slippage é vazio só na Rota A, ou calcular o
    degrau 3 com o slippage da Rota A, faz o teste cair."""
    route_b = replace(PRIMARY, slippage_bps={})
    steps = decomposition(simulate, route_b)
    assert steps[2].name == "slippage"
    assert steps[2].delta == 0.0
    assert steps[2].net_return == steps[1].net_return
    assert [s.inert for s in steps] == [None, None, "no_slippage", None, None, None]
    assert steps[1].delta is not None and steps[1].delta < 0.0


@pytest.mark.unit
def test_decomposition_marks_every_factor_that_is_off_in_the_primary() -> None:
    """Atraso zero, taxa zero, sem funding e sem restrição de tamanho no primário: os quatro
    degraus correspondentes ficam marcados como sem efeito, cada um com o seu motivo, e o
    degrau do slippage também (mapa com zero)."""
    flat = Frictions(0, {"a": 0.0}, 0.0, False, False)
    steps = decomposition(lambda f: fake(0.0), flat)
    assert [s.inert for s in steps] == [
        None,
        "delay_zero",
        "no_slippage",
        "fee_zero",
        "funding_off",
        "size_constraints_off",
    ]


# ─── Aviso de cenário irrealista (RF-SIM-04 CA-04.2) ─────────────────────────


@pytest.mark.unit
def test_zero_fee_or_zero_slippage_is_flagged_unrealistic() -> None:
    """RF-SIM-04 CA-04.2. Taxa zero é irrealista nas duas rotas. Slippage zero é irrealista na
    Rota A (a fonte é um proxy, e o slippage é premissa), em qualquer ativo do universo sem
    slippage positivo; na Rota B o mapa vazio é correto, porque o livro já é o preço real.

    Mutação registrada: avisar de slippage também na Rota B, ou só quando o mapa inteiro é zero
    (e não quando falta um ativo), faz o teste cair."""
    universe = {"BTC", "ETH"}
    ok = Frictions(5_000, {"BTC": 2.0, "ETH": 3.0}, 4.5, True, True)
    assert unrealistic_warnings(ok, "A", universe) == ()
    assert unrealistic_warnings(replace(ok, fee_bps=0.0), "A", universe) == ("fee_zero",)
    assert unrealistic_warnings(replace(ok, fee_bps=0.0), "B", universe) == ("fee_zero",)
    zero_slippage = replace(ok, slippage_bps={"BTC": 0.0, "ETH": 0.0})
    assert unrealistic_warnings(zero_slippage, "A", universe) == ("slippage_zero",)
    missing_one = replace(ok, slippage_bps={"BTC": 2.0})
    assert unrealistic_warnings(missing_one, "A", universe) == ("slippage_zero",)
    both = replace(zero_slippage, fee_bps=0.0)
    assert unrealistic_warnings(both, "A", universe) == ("fee_zero", "slippage_zero")
    assert unrealistic_warnings(replace(ok, slippage_bps={}), "B", universe) == ()
