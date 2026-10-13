"""Espelhamento e laço da subconta (T-042 e T-043, design §3.7, §4.2, §4.3, §5).

Fixtures de papel (RNF-03): preço constante de 100 por segundo, salvo onde o teste diz outro,
referência de exposição `N* = 1.000`, capital 1.000, `pico = teto = 1`, ordem mínima de 10 e lote de
0,01. Cada evento do líder é montado à mão, e a conta do valor esperado está na docstring do teste.
Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez nos módulos de
`copylab.sim` (cada uma está na docstring do teste que a pega).
"""

import random
from collections.abc import Mapping, Sequence

import pytest

from copylab.leader import LeaderEvent
from copylab.sim.account import Subaccount
from copylab.sim.cursor import Cursor, CursorView
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Counters, Frictions, Mirror
from copylab.sim.model import Ladder, Level, Order, Side
from copylab.sim.prices import PriceSource, ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import Ms
from copylab.windows import Window

SECONDS = 600
END = 600_000


def flat(price: float, seconds: Sequence[int] | range = range(SECONDS)) -> list[ProxyBar]:
    return [ProxyBar(s, price, price, price) for s in seconds]


def ev(
    t: int,
    coin: str,
    position: float,
    px: float = 100.0,
    *,
    zero: bool = True,
    unobserved: bool = False,
) -> LeaderEvent:
    """Evento do líder. `zero` é o `touched_zero`: por default o ativo começa a ser rastreado."""
    return LeaderEvent(
        t=Ms(t),
        coin=coin,
        kind="perp",
        prev_position=0.0,
        position=position,
        touched_zero=zero,
        px=px,
        notional=abs(position) * px,
        unobserved=unobserved,
        n_fills=1,
    )


class Laddered:
    """Fonte de preço com a escada de cada (ativo, segundo, lado) dada à mão; o resto vem do
    `ProxySource`. Serve para escadas de mais de um nível, que a Rota A não tem."""

    def __init__(
        self,
        bars: Mapping[str, Sequence[ProxyBar]],
        ladders: Mapping[tuple[str, int, Side], Ladder],
    ) -> None:
        self._proxy = ProxySource(bars)
        self._ladders = ladders

    def bind(self, cursor: CursorView) -> PriceSource:
        inner = self._proxy.bind(cursor)
        ladders = self._ladders

        class Bound:
            def available_from(self, coin: str, t: Ms) -> Ms | None:
                return inner.available_from(coin, t)

            def ladder(self, coin: str, t: Ms, side: Side) -> Ladder:
                inner.ladder(coin, t, side)
                return ladders.get((coin, t // 1_000, side), inner.ladder(coin, t, side))

            def mark(self, coin: str, t: Ms) -> float:
                return inner.mark(coin, t)

            def horizon(self) -> Ms:
                return inner.horizon()

        return Bound()


def run(
    events: Sequence[LeaderEvent],
    bars: Mapping[str, Sequence[ProxyBar]],
    *,
    reference: float = 1_000.0,
    capital: float = 1_000.0,
    delay: int = 0,
    fee_bps: float = 0.0,
    slip: Mapping[str, float] | None = None,
    constraints: bool = True,
    peak: float = 1.0,
    cap: float = 1.0,
    min_notional: float = 10.0,
    long_only: bool = False,
    lots: Mapping[str, float] | None = None,
    rates: Mapping[str, Mapping[Ms, float]] | None = None,
    start: int = 0,
    end: int = END,
    funding_on: bool = False,
    universe: Sequence[str] | None = None,
    feed: Laddered | None = None,
) -> SubaccountResult:
    coins = sorted(bars)
    return run_subaccount(
        LeaderTape(events),
        reference,
        frozenset(universe if universe is not None else coins),
        feed if feed is not None else ProxySource(bars),
        FundingTable(rates or {}),
        dict(lots) if lots is not None else dict.fromkeys(coins, 0.01),
        capital,
        Window(Ms(start), Ms(end)),
        Frictions(delay, dict(slip or {}), fee_bps, funding_on, constraints),
        Mirror(peak, cap, min_notional, long_only),
    )


def sizes(orders: Sequence[Order]) -> list[tuple[str, str, float]]:
    return [(o.coin, o.side, round(o.executed, 6)) for o in orders]


# ─── RF-SIM-01: instante de execução ─────────────────────────────────────────


@pytest.mark.unit
def test_order_executes_at_event_time_plus_delay() -> None:
    """RF-SIM-01 CA-01.1. Evento em 10.000 com Δ = 5.000: a ordem é do evento de 10.000, tem
    instante nominal e de execução 15.000, atraso efetivo de 5.000, e compra 10 a 100 (a
    posição do líder é a referência: alvo = 1 x 1.000 = 1.000, tamanho 1.000 / 100 = 10)."""
    result = run([ev(10_000, "a", 10.0)], {"a": flat(100.0)}, delay=5_000)
    (order,) = result.orders
    assert (order.event_t, order.nominal_t, order.exec_t, order.delay_ms) == (
        10_000,
        15_000,
        15_000,
        5_000,
    )
    assert (order.coin, order.side, order.executed, order.price) == ("a", "buy", 10.0, 100.0)
    assert result.delayed_executions == 0  # nenhuma esperou preço além do nominal


@pytest.mark.unit
def test_event_past_window_end_is_reported_pending() -> None:
    """RF-SIM-01 CA-01.4. Janela até 600.000, Δ = 20.000. Evento em 590.000: nominal 610.000,
    depois do fim, e não executa. Evento em 100.000 num ativo sem preço depois de 50 s: o
    instante de execução não existe, e também fica pendente. Os dois são reportados, com o
    notional do evento (10 x 100 = 1.000), e a contabilidade não muda.

    Mutação registrada: não contar o que ficou pendente (apagar a contagem de `PENDING` no fim do
    laço) zera os contadores, e o teste cai.
    """
    events = [ev(590_000, "a", 10.0), ev(100_000, "b", 10.0)]
    bars = {"a": flat(100.0), "b": flat(100.0, range(50))}
    result = run(events, bars, delay=20_000)
    assert result.orders == ()
    assert [(e.t, e.coin) for e in result.pending] == [(100_000, "b"), (590_000, "a")]
    assert result.counters.not_copied_events["pending"] == 2
    assert result.counters.not_copied_notional["pending"] == pytest.approx(2_000.0)
    assert result.final_equity == pytest.approx(1_000.0)


@pytest.mark.unit
def test_missing_price_uses_next_observation_and_records_delay() -> None:
    """RF-SIM-01 CA-01.5. `a` sem negócio nos segundos 10 a 14. Evento em 10.000, Δ = 0: a
    ordem executa na primeira observação, 15.000, ao máximo do segundo 15 (a barra é 99-101),
    com atraso efetivo de 5.000 ms e instante nominal 10.000. Nenhum preço é inventado."""
    bars = {
        "a": flat(100.0, range(10)) + [ProxyBar(s, 99.0, 101.0, 100.0) for s in range(15, SECONDS)]
    }
    result = run([ev(10_000, "a", 10.0)], bars)
    (order,) = result.orders
    assert (order.nominal_t, order.exec_t, order.delay_ms) == (10_000, 15_000, 5_000)
    assert order.price == 101.0
    assert result.delayed_executions == 1


@pytest.mark.unit
def test_delayed_execution_is_processed_at_effective_instant() -> None:
    """ADR-0008: nada é contabilizado antes de tau, e o dimensionamento usa o patrimônio de tau.
    Evento 1: `a` +10 a 100, executa em 10.000: compra 10. O preço de `a` cai para 50 no
    segundo 12. Evento 2: `b` +10 em 10.500, mas `b` só tem preço a partir do segundo 20: tau =
    20.000.
    Em tau: marcação de `a` 50, patrimônio 1.000 + 10 x (50 - 100) = 500 (e não 1.000, que era
    o de 10.500). Visão: `a` com razão 1, `b` com razão 1; g = 2, f = 0,5; alvos 0,5 x 500 =
    250 cada. Redução em `a`: valor 500, projetado 500 + 250 = 750, excesso 750 - 500 = 250,
    sobra de `a` 500 - 250 = 250, vende 250 / 50 = 5. Ordem em `b`: 250 / 100 = 2,5 compras.

    Mutação registrada: dimensionar com a marcação do instante nominal (`self.marks(nominal)` no
    lugar de `self.marks(tau)`, em `Engine.process`) dá patrimônio 1.000, alvo de 500 em `b` e
    compra de 5, e o teste cai.
    """
    bars = {
        "a": flat(100.0, range(12)) + flat(50.0, range(12, SECONDS)),
        "b": flat(100.0, range(5)) + flat(100.0, range(20, SECONDS)),
    }
    result = run([ev(10_000, "a", 10.0), ev(10_500, "b", 10.0)], bars)
    assert sizes(result.orders) == [("a", "buy", 10.0), ("a", "sell", 5.0), ("b", "buy", 2.5)]
    assert [o.exec_t for o in result.orders] == [10_000, 20_000, 20_000]


@pytest.mark.unit
def test_delayed_order_uses_view_of_processed_events() -> None:
    """ADR-0008: o que o seguidor sabe do líder são os eventos já processados. `a` só tem preço a
    partir do segundo 20, `b` desde o começo. Evento de `a` em 10.000 (tau = 20.000) e de `b` em
    12.000 (tau = 12.000), ambos de razão 1.
    Em 12.000 o evento de `a` ainda não foi processado: a visão tem só `b`, g = 1, f = 1, alvo
    1.000 e compra de 10. Se a visão tivesse os eventos até 12.000, g = 2 e a compra seria de 5.
    Em 20.000 a visão tem os dois: alvos 500; redução de `b` (valor 1.000, projetado 1.500,
    excesso 500) vende 5, e `a` compra 5.

    Mutação registrada: atualizar a visão no instante em que o evento é lido (nominal), e não
    quando executa, deixa `a` na visão de `b` e dá compra de 5 em `b`, e o teste cai.
    """
    bars = {"a": flat(100.0, range(5)) + flat(100.0, range(20, SECONDS)), "b": flat(100.0)}
    result = run([ev(10_000, "a", 10.0), ev(12_000, "b", 10.0)], bars)
    assert sizes(result.orders) == [("b", "buy", 10.0), ("b", "sell", 5.0), ("a", "buy", 5.0)]


@pytest.mark.unit
def test_round_trip_inside_gap_pays_costs_and_captures_nothing() -> None:
    """ADR-0008. `a` sem negócio nos segundos 10 a 14. O líder abre em 10.000 e fecha em 11.000,
    tudo
    dentro do buraco: as duas ordens executam em 15.000, na ordem dos eventos. Barra do 15:
    mínimo 99, máximo 101; taxa 10 bps.
    A compra pede 1.000 / 101 = 9,90, mas a pós-condição do teto desconta a taxa: o notional X cabe
    se X <= 1.000 / (1 + 1 x 0,001) = 999,0009, ou 9,8911 de tamanho, 9,89 no lote. Compra de
    9,89 ao máximo, 101 (taxa 0,001 x 998,89 = 0,99889); venda de 9,89 ao mínimo, 99 (taxa
    0,001 x 979,11 = 0,97911). Realizado 9,89 x (99 - 101) = -19,78; taxas 1,978; patrimônio
    1.000 - 19,78 - 1,978 = 978,242: paga o spread e as duas taxas e não captura movimento
    nenhum."""
    bars = {
        "a": flat(100.0, range(10)) + [ProxyBar(s, 99.0, 101.0, 100.0) for s in range(15, SECONDS)]
    }
    result = run([ev(10_000, "a", 10.0), ev(11_000, "a", 0.0)], bars, fee_bps=10.0)
    assert [(o.side, o.exec_t, o.price) for o in result.orders] == [
        ("buy", 15_000, 101.0),
        ("sell", 15_000, 99.0),
    ]
    assert [o.executed for o in result.orders] == pytest.approx([9.89, 9.89])
    assert result.realized == pytest.approx(-19.78)
    assert result.fees == pytest.approx(1.978)
    assert result.final_equity == pytest.approx(978.242)
    assert result.delayed_executions == 2


@pytest.mark.unit
def test_follower_price_is_independent_of_leader_fill_price() -> None:
    """ADR-0003. O líder abre 10 a 100 com N* = 1.000, ou 10 a 200 com N* = 2.000: a razão é a
    mesma (1), o alvo é o mesmo, e o seguidor paga o preço da barra (150), nunca o do fill do
    líder.

    Mutação registrada: usar `event.px` como preço de execução faz a ordem sair a 100 ou 200, e
    o teste cai.
    """
    results = [
        run([ev(10_000, "a", 10.0, px=px)], {"a": flat(150.0)}, reference=ref, capital=1_500.0)
        for px, ref in ((100.0, 1_000.0), (200.0, 2_000.0))
    ]
    for result in results:
        (order,) = result.orders
        assert (order.price, order.executed) == (150.0, 10.0)  # alvo 1 x 1.500 = 1.500 = 10 x 150
    assert results[0].orders == results[1].orders


# ─── RF-SIM-02: dimensionamento ──────────────────────────────────────────────


@pytest.mark.unit
def test_target_at_reference_exposure_equals_peak_times_equity() -> None:
    """RF-SIM-02 CA-02.1. Líder com posição de 10 a 100: notional 1.000 = N*. Pico 1: alvo 1.000,
    compra de 10. Pico 0,5: alvo 500, compra de 5."""
    for peak, size in ((1.0, 10.0), (0.5, 5.0)):
        result = run([ev(10_000, "a", 10.0)], {"a": flat(100.0)}, peak=peak)
        assert sizes(result.orders) == [("a", "buy", size)]


@pytest.mark.unit
def test_target_scales_linearly_with_leader_notional() -> None:
    """Posição do líder de 5 (razão 0,5): alvo 500, compra de 5. De 2,5 (razão 0,25): alvo 250,
    compra de 2,5. De -5 (vendido): vende 5."""
    for position, expected in ((5.0, 5.0), (2.5, 2.5), (-5.0, -5.0)):
        result = run([ev(10_000, "a", position)], {"a": flat(100.0)})
        (order,) = result.orders
        assert order.signed == pytest.approx(expected)


@pytest.mark.unit
def test_cap_scales_all_targets_proportionally_reductions_first() -> None:
    """RF-SIM-02 CA-02.2. `a` e `b` com razão 1 cada. Evento de `a`: g = 1, alvo 1.000, compra de
    10.
    Evento de `b`: g = 2, f = 0,5, alvos 500 e 500. Excesso: projetado 1.000 (a) + 500 (b) =
    1.500, menos o teto 1.000 = 500; a sobra de `a` é 1.000 - 500 = 500, e a redução, 500 x 500 /
    500 = 500, vende 5. Depois `b` compra 5. A redução vem antes do aumento, e a soma final dos
    módulos é 1.000, o teto.

    Mutação registrada: executar a ordem de `b` antes das reduções (ou não reduzir `a`) deixa a
    ordem de venda depois da compra, ou a exposição em 1.500, e o teste cai.
    """
    bars = {"a": flat(100.0), "b": flat(100.0)}
    result = run([ev(10_000, "a", 10.0), ev(20_000, "b", 10.0)], bars)
    assert sizes(result.orders) == [("a", "buy", 10.0), ("a", "sell", 5.0), ("b", "buy", 5.0)]
    assert [o.reason for o in result.orders] == [
        "target_increase",
        "cap_reduction",
        "target_increase",
    ]
    exposure = sum(abs(size) * 100.0 for size, _ in result.final_positions.values())
    assert exposure == pytest.approx(1_000.0)


@pytest.mark.unit
def test_other_assets_only_receive_reductions() -> None:
    """RF-SIM-02 CA-02.2. Com `a` = 5 e `b` = 5 (do teste anterior, razões 0,5 cada depois da
    redução), um evento de `a` com posição 4 (razão 0,4) em vez de 10: g = 0,4 + 1 = 1,4... os
    números aqui: razões a = 0,4 e b = 1 (a visão guarda a posição 10 de `b`).
    f = 1 / 1,4; alvo de `a` = 0,4 x 1.000 / 1,4 = 285,71; de `b` = 714,29. Posição atual: `a` 500,
    `b` 500.
    Evento em `a`: projetado = 500 (b) + 285,71 = 785,71 <= 1.000: sem excesso, sem redução.
    `b` está abaixo do alvo (500 < 714,29), mas não recebe ordem: só aumenta no evento dele. `a`
    vende (500 - 285,71) / 100 = 2,14 (arredondado ao lote)."""
    bars = {"a": flat(100.0), "b": flat(100.0)}
    events = [ev(10_000, "a", 10.0), ev(20_000, "b", 10.0), ev(30_000, "a", 4.0, zero=False)]
    result = run(events, bars)
    last = [o for o in result.orders if o.event_t == 30_000]
    assert sizes(last) == [("a", "sell", 2.14)]
    assert all(o.coin != "b" for o in last)


@pytest.mark.unit
def test_cap_reductions_are_minimal_and_proportional() -> None:
    """RF-SIM-02 CA-02.2, §4.3 passo 6. Deriva com compra de `a` e venda de `b` (razões +0,5 e
    -0,5, alvos 500 e -500, 5 e -5 de tamanho a 100). Os preços de `a` e `b` sobem a 200:
    patrimônio 1.000 + 5 x 100 - 5 x 100 = 1.000, exposição 1.000 + 1.000 = 2.000.
    Evento de `c` (razão 0,1): g = 0,5 + 0,5 + 0,1 = 1,1, f = 10 / 11; alvos `a` 454,545, `b`
    -454,545, `c` 90,909. Projetado 1.000 + 1.000 + 90,909 = 2.090,909, excesso 1.090,909. Sobras:
    `a` 1.000 - 454,545 = 545,455 e `b` o mesmo, S = 1.090,909 = E: cada um reduz a sua sobra
    inteira (545,455), que a 200 dá 2,727; no lote de 0,01, 2,72 cada, em ordem alfabética (a e b).
    Depois da redução, exposição dos outros 456 + 456 = 912; sobra para `c` 1.000 - 912 = 88, e
    `c` pede 0,909 -> 0,90 no lote, limitado a 0,88 pelo teto (88 / 100). Não copiado por teto:
    1 - 0,88 / 1,0 = 0,12 do evento (notional 100), ou seja 12.

    Mutação registrada: reduzir em ordem não alfabética (`reversed` na ordem das reduções) troca a
    ordem das duas vendas, e o teste cai. A proporção em si, com excesso menor que a sobra, é a de
    `test_drifted_exposure_triggers_cap_reductions`.
    """
    bars = {
        "a": flat(100.0, range(100)) + flat(200.0, range(100, SECONDS)),
        "b": flat(100.0, range(100)) + flat(200.0, range(100, SECONDS)),
        "c": flat(100.0),
    }
    events = [ev(10_000, "a", 5.0), ev(11_000, "b", -5.0), ev(200_000, "c", 1.0)]
    result = run(events, bars)
    drift = [o for o in result.orders if o.event_t == 200_000]
    assert sizes(drift) == [("a", "sell", 2.72), ("b", "buy", 2.72), ("c", "buy", 0.88)]
    assert [o.reason for o in drift] == ["cap_reduction", "cap_reduction", "target_increase"]
    assert result.counters.not_copied_events["cap_reached"] == 1
    assert result.counters.not_copied_notional["cap_reached"] == pytest.approx(12.0)
    exposure = sum(
        abs(size) * 200.0 for coin, (size, _) in result.final_positions.items() if coin != "c"
    )
    assert exposure + 0.88 * 100.0 == pytest.approx(1_000.0)


@pytest.mark.unit
def test_drifted_exposure_triggers_cap_reductions() -> None:
    """Exemplo da revisão do design (§4.3, passo 6). Subconta de capital 30 com 6 de `a` a 10 (valor
    60: o dobro do patrimônio de 30) e leitura da visão com `a` de razão 0,8 e `b` de razão 0,1
    (alvos 24 e 3, f = 1, soma 27 <= 30). Evento de `b`:
      projetado = 60 + 3 = 63; excesso 63 - 30 = 33; sobra de `a` 60 - 24 = 36; E <= S;
      redução 36 x 33 / 36 = 33 dólares, 3,3 de tamanho: `a` fica com 2,7 (valor 27).
      `b` compra 3 / 10 = 0,3: exposição 27 + 3 = 30 = teto x patrimônio. O gatilho é a
      exposição real, e não o fator f (que aqui é 1).

    Mutação registrada: reduzir a sobra inteira (`dollars = room`) no lugar da parte proporcional
    vende 3,6 de `a`, e não 3,3, e o teste cai.
    """
    bars = {"a": flat(10.0), "b": flat(10.0)}
    events = [ev(10_000, "a", 8.0, px=100.0), ev(20_000, "b", 1.0, px=100.0)]
    # Posição de 6 de `a` (valor 60 com patrimônio 30), montada na conta antes do evento de `b`.
    from copylab.sim.cursor import Cursor
    from copylab.sim.mirror import Engine

    cursor = Cursor(Ms(0))
    prices = ProxySource(bars).bind(cursor.view())
    account = Subaccount(30.0)
    engine = Engine(
        account=account,
        prices=prices,
        lots={"a": 0.01, "b": 0.01},
        reference=1_000.0,
        universe=frozenset({"a", "b"}),
        frictions=Frictions(0, {}, 0.0, False, True),
        mirror=Mirror(1.0, 1.0, 1.0, False),
    )
    cursor.advance(Ms(10_000))
    engine.process(events[0], Ms(10_000), Ms(10_000))  # alvo de `a`: 0,8 x 30 = 24 -> compra 2,4
    assert account.size("a") == pytest.approx(2.4)
    account.trade("a", 3.6, 10.0, 0.0)  # a posição passa a 6, valor 60, patrimônio 30
    cursor.advance(Ms(20_000))
    engine.process(events[1], Ms(20_000), Ms(20_000))
    assert account.size("a") == pytest.approx(2.7)
    assert account.size("b") == pytest.approx(0.3)
    assert [(o.coin, o.reason) for o in engine.orders[-2:]] == [
        ("a", "cap_reduction"),
        ("b", "target_increase"),
    ]


@pytest.mark.unit
def test_unsendable_cap_reduction_is_counted_and_blocks_increases() -> None:
    """RF-SIM-02 CA-02.7. Patrimônio 1.000, 11 de `a` a 100 (valor 1.100), com lote de 3 em
    `a` (cada lote vale 300). Visão: `a` 0,9 (alvo 900), `b` 0,1 (alvo 100). Evento de `b`:
    projetado 1.100 + 100 = 1.200, excesso 200; a sobra de `a` é 200: a redução é de 200
    dólares, 2 de tamanho, que arredondado ao lote de 3 dá zero: não há ordem a enviar, e a
    redução é contada. A exposição segue em 1.100, acima do teto de 1.000, e o aumento de `b`
    é impedido (nenhum lote cabe), apesar de pedir 100 e de passar da ordem mínima de 10.
    Excesso sobre o teto: 1 execução, 100 dólares, 0,1 do patrimônio.

    Mutação registrada: ignorar a pós-condição do passo 8 (`return equity > 0.0` em
    `_max_lots`) deixa o aumento de `b` sair, e o teste cai.
    """
    from copylab.sim.cursor import Cursor
    from copylab.sim.mirror import Engine

    bars = {"a": flat(100.0), "b": flat(100.0)}
    cursor = Cursor(Ms(0))
    prices = ProxySource(bars).bind(cursor.view())
    account = Subaccount(1_000.0)
    engine = Engine(
        account=account,
        prices=prices,
        lots={"a": 3.0, "b": 0.01},
        reference=1_000.0,
        universe=frozenset({"a", "b"}),
        frictions=Frictions(0, {}, 0.0, False, True),
        mirror=Mirror(1.0, 1.0, 10.0, False),
    )
    cursor.advance(Ms(10_000))
    engine.process(ev(10_000, "a", 9.0), Ms(10_000), Ms(10_000))  # alvo 900: compra 9
    account.trade("a", 2.0, 100.0, 0.0)  # 11 de `a`: valor 1.100
    before = len(engine.orders)
    cursor.advance(Ms(20_000))
    engine.process(ev(20_000, "b", 1.0), Ms(20_000), Ms(20_000))
    assert len(engine.orders) == before  # nada enviado
    assert engine.counters.cap_reduction_below_minimum == 1
    assert engine.counters.cap_excess_executions == 1
    assert engine.counters.max_cap_excess_usd == pytest.approx(100.0)
    assert engine.counters.max_cap_excess_fraction == pytest.approx(0.1)
    assert account.size("b") == 0.0


@pytest.mark.unit
def test_cap_reduction_without_price_is_counted() -> None:
    """RF-SIM-02 CA-02.7, errata do ADR-0002. `a` sem negócio no segundo 50. Na posição de `a` o
    valor passou do teto (patrimônio 1.000, 11 de `a`: 1.100), e o evento de `b` em 50.000 pede a
    redução de `a`: sem observação de `a` naquele instante, ela não é enviada, e é contada. O
    aumento de `b` fica impedido pelo excesso que sobra.

    Mutação registrada: tentar a redução sem a guarda de `available_from` (executar sem observação)
    levanta `DataError` por falta de negócio no segundo, e o teste cai; nenhum preço é inventado.
    """
    from copylab.sim.cursor import Cursor
    from copylab.sim.mirror import Engine

    bars = {"a": flat(100.0, [s for s in range(SECONDS) if s != 50]), "b": flat(100.0)}
    cursor = Cursor(Ms(0))
    prices = ProxySource(bars).bind(cursor.view())
    account = Subaccount(1_000.0)
    engine = Engine(
        account=account,
        prices=prices,
        lots={"a": 0.01, "b": 0.01},
        reference=1_000.0,
        universe=frozenset({"a", "b"}),
        frictions=Frictions(0, {}, 0.0, False, True),
        mirror=Mirror(1.0, 1.0, 10.0, False),
    )
    cursor.advance(Ms(10_000))
    engine.process(ev(10_000, "a", 9.0), Ms(10_000), Ms(10_000))
    account.trade("a", 2.0, 100.0, 0.0)
    before = len(engine.orders)
    cursor.advance(Ms(50_000))
    engine.process(ev(50_000, "b", 1.0), Ms(50_000), Ms(50_000))
    assert len(engine.orders) == before
    assert engine.counters.cap_reduction_without_price == 1
    assert account.size("b") == 0.0


@pytest.mark.unit
def test_preexisting_leader_position_is_ignored_until_flat() -> None:
    """RF-SIM-02 CA-02.3. Evento 1: a posição do líder vai de 5 a 3 sem tocar o zero: o ativo não
    é rastreado, o alvo é zero e nenhuma ordem sai; conta como "posição anterior à janela" com o
    notional do evento, 3 x 100 = 300. Evento 2: chega a zero (toca): passa a ser rastreado,
    alvo zero, nada a fazer. Evento 3: abre 4 a partir de zero: razão 0,4, compra de 4.

    Mutação registrada: rastrear o ativo desde o primeiro evento (tratar `touched_zero` como
    sempre verdadeiro) faz o evento 1 comprar 3, e o teste cai.
    """
    events = [
        ev(10_000, "a", 3.0, zero=False),
        ev(20_000, "a", 0.0),
        ev(30_000, "a", 4.0),
    ]
    result = run(events, {"a": flat(100.0)})
    assert sizes(result.orders) == [("a", "buy", 4.0)]
    assert result.orders[0].event_t == 30_000
    assert result.counters.not_copied_events["pre_window"] == 1
    assert result.counters.not_copied_notional["pre_window"] == pytest.approx(300.0)


@pytest.mark.unit
def test_tracking_starts_when_leader_position_touches_zero() -> None:
    """§4.3 passo 1. O líder estava com 5 antes da janela e cruza o zero num evento, indo a -3:
    toca o zero (cruzou), o ativo passa a ser rastreado já na posição nova, e o seguidor vende 3
    (razão -0,3, alvo -300). O evento seguinte, que só aumenta o vendido para -4, já é copiado
    (rastreado): o alvo é -400, vende mais 1."""
    events = [ev(10_000, "a", -3.0, zero=True), ev(20_000, "a", -4.0, zero=False)]
    result = run(events, {"a": flat(100.0)})
    assert sizes(result.orders) == [("a", "sell", 3.0), ("a", "sell", 1.0)]


@pytest.mark.unit
def test_below_minimum_order_is_skipped_and_delta_persists() -> None:
    """RF-SIM-02 CA-02.4. Líder com 0,05 (razão 0,005, alvo 5 dólares, 0,05 de tamanho): notional 5
    <
    10: não é enviada, e conta "abaixo do mínimo" com a fração 1 do evento (notional 5). No evento
    seguinte, 0,1 (alvo 10, 0,1 de tamanho, notional 10 >= 10): a diferença persiste, pois o alvo é
    recalculado do zero, e a ordem sai inteira, de 0,1.

    Mutação registrada: tirar a verificação do mínimo (`size * quote < min_notional`) faz o
    primeiro evento comprar 0,05, e o teste cai.
    """
    result = run([ev(10_000, "a", 0.05), ev(20_000, "a", 0.1, zero=False)], {"a": flat(100.0)})
    assert sizes(result.orders) == [("a", "buy", 0.1)]
    assert result.counters.not_copied_events["below_minimum"] == 1
    assert result.counters.not_copied_notional["below_minimum"] == pytest.approx(5.0)


@pytest.mark.unit
def test_order_size_is_floored_to_lot() -> None:
    """RF-SIM-02 CA-02.4. Lote de 1,0: alvo 250 a 100 = 2,5, arredondado para baixo a 2. Sem o
    arredondamento, seria 2,5. A fração 0,2 do evento não é "não copiada por mínimo, teto ou
    profundidade": é só arredondamento, e não entra em nenhum contador."""
    result = run(
        [ev(10_000, "a", 2.5)],
        {"a": flat(100.0)},
        lots={"a": 1.0},
        capital=1_000.0,
        reference=1_000.0,
    )
    assert sizes(result.orders) == [("a", "buy", 2.0)]
    assert sum(result.counters.not_copied_events.values()) == 0


@pytest.mark.unit
def test_full_close_executes_below_minimum() -> None:
    """RF-SIM-02 CA-02.5. O líder abre 0,1 a 100 (alvo 10 dólares, compra de 0,1, notional 10). O
    preço cai
    para 50: valor 5, abaixo do mínimo de 10. O líder zera: alvo zero, e a venda de 0,1 (notional 5
    <
    10) executa, porque zera a posição inteira.

    Mutação registrada: aplicar o mínimo também ao fechamento total deixa a posição aberta, e
    o teste cai.
    """
    bars = {"a": flat(100.0, range(100)) + flat(50.0, range(100, SECONDS))}
    result = run([ev(10_000, "a", 0.1), ev(200_000, "a", 0.0)], bars)
    assert sizes(result.orders) == [("a", "buy", 0.1), ("a", "sell", 0.1)]
    assert result.final_positions == {}


@pytest.mark.unit
def test_sign_flip_closes_then_opens_with_minimum_on_the_opening_only() -> None:
    """§4.3 passo 7. Seguidor comprado de 5. O líder inverte para -3 (razão -0,3, alvo -300): duas
    ordens
    no mesmo instante, venda de 5 (fecha, `target_reduce`) e venda de 3 (abre, `target_increase`).
    Com a abertura pequena, -0,05 (alvo -5, abaixo do mínimo de 10): o fechamento sai inteiro e a
    abertura não é enviada ("abaixo do mínimo"): a posição final é zero, e não -0,05."""
    big = run([ev(10_000, "a", 5.0), ev(20_000, "a", -3.0)], {"a": flat(100.0)})
    assert [(o.reason, o.executed) for o in big.orders[1:]] == [
        ("target_reduce", 5.0),
        ("target_increase", 3.0),
    ]
    assert big.final_positions["a"][0] == pytest.approx(-3.0)
    small = run([ev(10_000, "a", 5.0), ev(20_000, "a", -0.05)], {"a": flat(100.0)})
    assert [(o.reason, o.executed) for o in small.orders[1:]] == [("target_reduce", 5.0)]
    assert small.final_positions == {}
    assert small.counters.not_copied_events["below_minimum"] == 1


@pytest.mark.unit
def test_order_walks_two_ladder_levels_and_consumption_persists() -> None:
    """§4.3 passo 10. `a` sem negócio nos segundos 10 a 14: os dois eventos (10.000 e 11.000)
    executam em 15.000. Escada de compra do segundo 15: 3 a 100 e 5 a 101.
    Evento 1: razão 0,3, alvo 300, 3 a 100: percorre só o primeiro nível, preço 100.
    Evento 2: razão 0,6, alvo 600; o patrimônio segue 1.000; faltam 3 (6 - 3): o primeiro nível
    já foi consumido pela ordem anterior, e as 3 saem ao segundo nível, a 101 (e não a 100).
    Se a escada fosse zerada a cada ordem, a segunda sairia a 100.

    Mutação registrada: recriar a escada a cada ordem (sem guardar o consumo) faz a segunda ordem
    sair
    a 100, e o teste cai.
    """
    bars = {
        "a": flat(100.0, range(10)) + [ProxyBar(s, 100.0, 100.0, 100.0) for s in range(15, SECONDS)]
    }
    ladders: dict[tuple[str, int, Side], Ladder] = {
        ("a", 15, "buy"): (Level(100.0, 3.0), Level(101.0, 5.0))
    }
    feed = Laddered(bars, ladders)
    result = run([ev(10_000, "a", 3.0), ev(11_000, "a", 6.0, zero=False)], bars, feed=feed)
    assert [(o.executed, o.price) for o in result.orders] == [(3.0, 100.0), (3.0, 101.0)]


@pytest.mark.unit
def test_order_beyond_depth_fills_partially_and_counts() -> None:
    """Escada de compra só com 4 de tamanho (a 100); a ordem pede 10 (alvo 1.000): executa 4, o
    resto
    é "profundidade excedida", com a fração 0,6 do evento (notional 1.000 x 0,6 = 600)."""
    bars = {"a": flat(100.0)}
    feed = Laddered(bars, {("a", 10, "buy"): (Level(100.0, 4.0),)})
    result = run([ev(10_000, "a", 10.0)], bars, feed=feed)
    assert [(o.requested, o.executed) for o in result.orders] == [(10.0, 4.0)]
    assert result.counters.not_copied_events["depth_exceeded"] == 1
    assert result.counters.not_copied_notional["depth_exceeded"] == pytest.approx(600.0)


@pytest.mark.unit
def test_unobserved_position_change_is_absorbed_at_next_fill_and_counted() -> None:
    """RF-SIM-02 CA-02.8. O líder abre 5 (razão 0,5, compra de 5). No evento seguinte a posição
    declarada é 3, e o evento vem marcado `unobserved`: a mudança é incorporada ali (a razão passa a
    0,3, o alvo a 300), contada uma vez, e o seguidor vende 2. Nada retroage."""
    events = [ev(10_000, "a", 5.0), ev(20_000, "a", 3.0, zero=False, unobserved=True)]
    result = run(events, {"a": flat(100.0)})
    assert sizes(result.orders) == [("a", "buy", 5.0), ("a", "sell", 2.0)]
    assert result.counters.unobserved_changes == 1


@pytest.mark.unit
def test_events_outside_the_universe_do_not_trade() -> None:
    """Evento de `x`, fora do universo {a}: nenhuma ordem, nenhum contador."""
    result = run([ev(10_000, "x", 10.0)], {"a": flat(100.0), "x": flat(100.0)}, universe=["a"])
    assert result.orders == ()
    assert sum(result.counters.not_copied_events.values()) == 0


# ─── RF-SIM-03 a RF-SIM-06: preço, custos, funding, contabilidade ────────────


@pytest.mark.unit
def test_route_a_uses_worst_price_of_execution_second_with_slippage() -> None:
    """RF-SIM-03 CA-03.1. Barra de `a` em 10: mínimo 98, máximo 102. Slippage de 10 bps, contra o
    seguidor: compra a 102 x 1,001 = 102,102; venda a 98 x 0,999 = 97,902."""
    bars = {
        "a": flat(100.0, range(10)) + [ProxyBar(s, 98.0, 102.0, 100.0) for s in range(10, SECONDS)]
    }
    result = run(
        [ev(10_000, "a", 2.0), ev(20_000, "a", 0.0)], bars, slip={"a": 10.0}, constraints=False
    )
    buy, sell = result.orders
    assert buy.price == pytest.approx(102.102)
    assert sell.price == pytest.approx(97.902)


@pytest.mark.unit
def test_taker_fee_is_debited_and_recorded_on_order() -> None:
    """RF-SIM-04 CA-04.1. Taxa de 5 bps, sem restrições de tamanho (o teto descontaria a taxa e
    encolheria a ordem). Compra de 10 a 100 (notional 1.000): taxa 0,5, registrada na ordem. Venda
    de 10 a 100: outra taxa de 0,5. Patrimônio final 1.000 - 1,0 = 999."""
    result = run(
        [ev(10_000, "a", 10.0), ev(20_000, "a", 0.0)],
        {"a": flat(100.0)},
        fee_bps=5.0,
        constraints=False,
    )
    assert [o.fee for o in result.orders] == [pytest.approx(0.5), pytest.approx(0.5)]
    assert result.fees == pytest.approx(1.0)
    assert result.final_equity == pytest.approx(999.0)


@pytest.mark.unit
def test_funding_closed_form_ten_hours() -> None:
    """RF-SIM-05 CA-05.3. Posição constante de 5 a 100 (razão 0,5), aberta em 10.000, taxa 0,0001
    por hora e preço 100. A janela vai até 10,5 h: as horas cheias 1 a 10 caem dentro (a de 0 h, no
    início, não tem posição). Cada hora paga 5 x 100 x 0,0001 = 0,05; em 10 horas, 0,5 (forma
    fechada). O patrimônio final é 1.000 - 0,5."""
    hour = 3_600_000
    rates = {"a": {Ms(h * hour): 0.0001 for h in range(0, 12)}}
    seconds = range(0, 10 * 3_600 + 1_800)
    result = run(
        [ev(10_000, "a", 5.0)],
        {"a": flat(100.0, seconds)},
        rates=rates,
        funding_on=True,
        end=10 * hour + 1_800_000,
    )
    assert len(result.payments) == 10
    assert [p.t for p in result.payments] == [h * hour for h in range(1, 11)]
    assert result.funding_paid == pytest.approx(0.5)
    assert result.final_equity == pytest.approx(1_000.0 - 0.5)


@pytest.mark.unit
def test_funding_short_with_negative_rate_pays() -> None:
    """RF-SIM-05 CA-05.1. Vendido de 5 a 100 (razão -0,5), taxa -0,0002: pagamento = -5 x 100 x
    -0,0002 =
    +0,1 por hora, debitado (com taxa negativa, o vendido paga). Duas horas: 0,2."""
    hour = 3_600_000
    rates = {"a": {Ms(h * hour): -0.0002 for h in range(0, 4)}}
    result = run(
        [ev(10_000, "a", -5.0)],
        {"a": flat(100.0, range(0, 2 * 3_600 + 1_800))},
        rates=rates,
        funding_on=True,
        end=2 * hour + 1_800_000,
    )
    assert [p.amount for p in result.payments] == [pytest.approx(0.1), pytest.approx(0.1)]
    assert result.funding_paid == pytest.approx(0.2)


@pytest.mark.unit
def test_funding_is_applied_before_execution_at_the_same_instant_and_end_hour_is_excluded() -> None:
    """Design §4.2: funding antes da execução no mesmo instante, e o funding da hora que coincide
    com
    o fim fica de fora. Evento exatamente em 1 h: o funding das 1 h incide sobre a posição que
    existia durante a hora (nenhuma), e a posição aberta em 1 h só paga as horas seguintes. Janela
    até 3 h: paga a hora 2 h, e a hora 3 h (o fim) fica de fora.

    Mutação registrada: executar antes do funding no mesmo instante (mover o bloco de funding para
    depois das execuções, no laço) faz a hora 1 h cobrar a posição nova, e o teste cai. A exclusão
    da hora do fim vem de `now >= end` encerrar o laço antes de qualquer ocorrência.
    """
    hour = 3_600_000
    rates = {"a": {Ms(h * hour): 0.0001 for h in range(0, 4)}}
    result = run(
        [ev(hour, "a", 5.0)],
        {"a": flat(100.0, range(0, 3 * 3_600))},
        rates=rates,
        funding_on=True,
        end=3 * hour,
    )
    assert [p.t for p in result.payments] == [2 * hour]


@pytest.mark.unit
def test_open_position_at_end_is_marked_and_reported_separately() -> None:
    """RF-SIM-06 CA-06.3. Compra de 5 a 100; o preço sobe para 110 a partir do segundo 100. No fim,
    a
    posição segue aberta e é marcada pelo último preço (110): não realizado 5 x 10 = 50, realizado
    zero, patrimônio 1.050, e a posição é reportada à parte, sem liquidação forçada."""
    bars = {"a": flat(100.0, range(100)) + flat(110.0, range(100, SECONDS))}
    result = run([ev(10_000, "a", 5.0)], bars)
    assert result.final_positions["a"] == pytest.approx((5.0, 100.0))
    assert result.realized == 0.0
    assert result.unrealized == pytest.approx(50.0)
    assert result.final_equity == pytest.approx(1_050.0)
    # `final_marks` guarda a marcação das posições abertas: 5 x (110 - 100) = 50 do não realizado.
    assert result.final_marks == {"a": pytest.approx(110.0)}


@pytest.mark.unit
def test_reconciliation_identity_closes_over_a_full_run() -> None:
    """RF-SIM-06 CA-06.2 sobre uma rodada completa, com slippage de 10 bps, taxa de 5 bps, funding e
    três ativos, com preços que se mexem. O conferente roda dentro de `run_subaccount` e levanta se
    o
    resíduo passar de 1e-9; aqui se confere o resultado e os dois lados."""
    hour = 3_600_000
    bars = {
        coin: [
            ProxyBar(s, p - 0.5, p + 0.5, p)
            for s in range(0, 3 * 3_600)
            for p in [100.0 + 10.0 * ((s // 600) % 3) * (1 if coin != "b" else -1)]
        ]
        for coin in ("a", "b", "c")
    }
    rates = {c: {Ms(h * hour): 0.00005 * (h + 1) for h in range(0, 4)} for c in "abc"}
    events = [
        ev(5_000, "a", 6.0),
        ev(700_000, "b", -4.0),
        ev(1_400_000, "c", 3.0),
        ev(2_900_000, "a", 0.0),
        ev(4_000_000, "c", -2.0, zero=True),
    ]
    result = run(
        events, bars, slip={"a": 10.0, "b": 10.0, "c": 10.0}, fee_bps=5.0, rates=rates,
        funding_on=True, end=3 * hour, delay=2_000,
    )  # fmt: skip
    rec = result.reconciliation
    assert rec.ok
    assert rec.lhs == pytest.approx(result.final_equity - 1_000.0)
    assert rec.rhs == pytest.approx(
        result.realized + result.unrealized - result.fees - result.funding_paid
    )
    assert result.fees > 0 and len(result.payments) > 0 and len(result.orders) >= 5


@pytest.mark.unit
def test_subaccount_freezes_at_nonpositive_equity_with_explicit_missing_metrics() -> None:
    """RF-SIM-06 CA-06.4. Vendido de 10 a 100 (alvo -1.000 com capital 1.000). O preço sobe para
    250 a
    partir do segundo 100: patrimônio 1.000 + (-10) x (250 - 100) = -500. No evento seguinte, em
    150.000,
    a marcação dá patrimônio -500 <= 0: a subconta congela naquele instante, o valor real (-500) é o
    patrimônio final, a curva termina ali e as ordens param. O evento que não executou fica
    pendente, e a conta fecha."""
    bars = {"a": flat(100.0, range(100)) + flat(250.0, range(100, SECONDS))}
    events = [ev(10_000, "a", -10.0), ev(150_000, "a", -12.0, zero=False), ev(300_000, "a", 0.0)]
    result = run(events, bars)
    assert result.frozen and result.frozen_at == 150_000
    assert result.final_equity == pytest.approx(-500.0)
    assert result.equity_curve[-1][0] == 150_000
    assert result.equity_curve[-1][1] == pytest.approx(-500.0)
    assert len(result.orders) == 1
    assert [e.t for e in result.pending] == [300_000]
    assert result.reconciliation.ok


@pytest.mark.unit
def test_max_leverage_is_observed_after_every_occurrence() -> None:
    """Alavancagem observada. Comprado em `a` e vendido em `b`, 5 de cada a 100 (exposição 1.000,
    patrimônio
    1.000, alavancagem 1). Os dois preços sobem a 200 a partir do segundo 1.000: patrimônio 1.000 +
    5 x 100
    - 5 x 100 = 1.000, exposição 2.000, alavancagem 2. A primeira ocorrência depois da deriva é o
    funding das 1 h (3.600.000), com a alavancagem 2 medida ali; é o máximo, e o instante é o
    dela."""
    hour = 3_600_000
    bars = {
        "a": flat(100.0, range(1_000)) + flat(200.0, range(1_000, 3_700)),
        "b": flat(100.0, range(1_000)) + flat(200.0, range(1_000, 3_700)),
    }
    rates = {c: {Ms(0): 0.0, Ms(hour): 0.0} for c in "ab"}
    result = run(
        [ev(10_000, "a", 5.0), ev(11_000, "b", -5.0)], bars, rates=rates, funding_on=True,
        end=hour + 100_000,
    )  # fmt: skip
    assert result.max_leverage == pytest.approx(2.0)
    assert result.max_leverage_at == hour


@pytest.mark.unit
def test_equity_curve_has_start_each_utc_midnight_and_end() -> None:
    """Design §5: um ponto por meia-noite UTC, mais o instante inicial e o final. Janela de 1,5 dia
    a
    partir da meia-noite 0: pontos em 0 (início, que é meia-noite e não se repete), 86.400.000 (a
    meia-noite) e no fim, 129.600.000."""
    day = 86_400_000
    result = run([], {"a": flat(100.0, range(0, 1_000))}, end=day + day // 2)
    assert [t for t, _ in result.equity_curve] == [0, day, day + day // 2]


@pytest.mark.unit
def test_counters_by_reason_are_reported() -> None:
    """RF-ANA-04 CA-04.1, os cinco motivos do laço. Eventos de papel: posição anterior à janela
    (notional 300), abaixo do mínimo (5), pendente (1.000). Os de teto e profundidade têm testes
    próprios. Cada motivo traz eventos e notional."""
    events = [
        ev(10_000, "a", 3.0, zero=False),
        ev(20_000, "b", 0.05),
        ev(590_000, "c", 10.0),
    ]
    bars = {c: flat(100.0) for c in "abc"}
    result = run(events, bars, delay=20_000)
    events_by = result.counters.not_copied_events
    assert (events_by["pre_window"], events_by["below_minimum"], events_by["pending"]) == (1, 1, 1)
    notional = result.counters.not_copied_notional
    assert notional["pre_window"] == pytest.approx(300.0)
    assert notional["below_minimum"] == pytest.approx(5.0)
    assert notional["pending"] == pytest.approx(1_000.0)
    assert isinstance(result.counters, Counters)


@pytest.mark.unit
def test_gross_exposure_never_exceeds_cap_after_event() -> None:
    """RF-SIM-02 CA-02.7 (i), ADR-0002 e errata. Simulação semeada: três ativos com preço em passeio
    aleatório (fixo pela semente 7), 40 eventos do líder com posições positivas e negativas, taxa
    de 5
    bps, slippage de 10 bps e atraso de 2 s. Para cada ordem que aumenta o módulo da posição, a
    exposição bruta, com o ativo da ordem ao preço médio dela e os demais à marcação, não passa de
    teto x patrimônio, com o patrimônio já líquido da taxa (o teto é 1). A conferência refaz a conta
    das ordens numa subconta à parte, e vale para toda ordem que aumenta, venha o excesso de onde
    vier.

    Mutação registrada: tirar a pós-condição do passo 8 (`return equity > 0.0` em `_max_lots`) deixa
    ordens que aumentam acima do teto, e o teste cai.
    """
    rng = random.Random(7)
    coins = ("a", "b", "c")
    bars: dict[str, list[ProxyBar]] = {}
    for coin in coins:
        price, series = 100.0, []
        for second in range(SECONDS):
            price *= 1.0 + rng.uniform(-0.02, 0.02)
            series.append(ProxyBar(second, price * 0.999, price * 1.001, price))
        bars[coin] = series
    events = [
        ev(5_000 + 13_000 * i, rng.choice(coins), rng.choice((-1, 1)) * rng.uniform(2.0, 14.0))
        for i in range(40)
    ]
    result = run(events, bars, fee_bps=5.0, slip={c: 10.0 for c in coins}, delay=2_000)
    marks = ProxySource(bars).bind(Cursor(Ms(10**12)).view())
    account = Subaccount(1_000.0)
    increases = 0
    for order in result.orders:
        before = abs(account.size(order.coin))
        account.trade(order.coin, order.signed, order.price, order.fee)
        if abs(account.size(order.coin)) <= before * (1 + 1e-12):
            continue
        increases += 1
        others = [c for c in account.open_coins() if c != order.coin]
        mark = {c: marks.mark(c, order.exec_t) for c in others}
        size, avg = account.size(order.coin), account.avg_cost(order.coin)
        equity = account.cash + sum(
            account.size(c) * (mark[c] - account.avg_cost(c)) for c in others
        )
        equity += size * (order.price - avg)
        exposure = sum(abs(account.size(c)) * mark[c] for c in others) + abs(size) * order.price
        assert exposure <= 1.0 * equity * (1 + 1e-9) + 1e-9, order
    assert increases >= 10
