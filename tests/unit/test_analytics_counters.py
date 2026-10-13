"""Contadores de não cópia e excesso sobre o teto (T-053; RF-ANA-04 CA-04.1, RF-SIM-02 CA-02.7).

Fixtures de papel (RNF-03): quatro subcontas de capital 1.000 e referência de exposição 1.000, ordem
mínima de 10, lote de 0,01, preço de 100 por segundo, salvo onde o teste diz outro. Cada evento do
líder é montado à mão, e a conta de cada contador está na docstring. Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.analytics.counters` (cada uma está na docstring do teste que a pega).
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace

import pytest

from copylab.analytics.counters import (
    NON_COPY_REASONS,
    CapExcess,
    NonCopy,
    cap_excess,
    non_copy,
    outside_universe,
)
from copylab.leader import LeaderEvent
from copylab.sim.cursor import CursorView
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Counters, Frictions, Mirror
from copylab.sim.model import Ladder, Level, Side
from copylab.sim.prices import PriceFeed, PriceSource, ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import Ms
from copylab.windows import Window

SECONDS = 600
END = 600_000


def flat(price: float, skip: Sequence[int] = ()) -> list[ProxyBar]:
    return [ProxyBar(s, price, price, price) for s in range(SECONDS) if s not in skip]


def ev(t: int, coin: str, position: float, *, zero: bool = True) -> LeaderEvent:
    return LeaderEvent(
        t=Ms(t),
        coin=coin,
        kind="perp",
        prev_position=0.0,
        position=position,
        touched_zero=zero,
        px=100.0,
        notional=abs(position) * 100.0,
        unobserved=False,
        n_fills=1,
    )


class Shallow:
    """Fonte de preço cujos níveis têm no máximo `depth` de tamanho, para forçar a profundidade
    excedida. O resto vem do `ProxySource`."""

    def __init__(self, bars: Mapping[str, Sequence[ProxyBar]], depth: float) -> None:
        self._proxy = ProxySource(bars)
        self._depth = depth

    def bind(self, cursor: CursorView) -> PriceSource:
        inner, depth = self._proxy.bind(cursor), self._depth

        class Bound:
            def available_from(self, coin: str, t: Ms) -> Ms | None:
                return inner.available_from(coin, t)

            def ladder(self, coin: str, t: Ms, side: Side) -> Ladder:
                return tuple(Level(level.price, depth) for level in inner.ladder(coin, t, side))

            def mark(self, coin: str, t: Ms) -> float:
                return inner.mark(coin, t)

            def horizon(self) -> Ms:
                return inner.horizon()

        return Bound()


def run(
    events: Sequence[LeaderEvent],
    bars: Mapping[str, Sequence[ProxyBar]],
    *,
    delay: int = 0,
    feed: PriceFeed | None = None,
) -> SubaccountResult:
    return run_subaccount(
        LeaderTape(events),
        1_000.0,
        frozenset(bars),
        feed if feed is not None else ProxySource(bars),
        FundingTable({}),
        dict.fromkeys(bars, 0.01),
        1_000.0,
        Window(Ms(0), Ms(END)),
        Frictions(delay, {}, 0.0, False, True),
        Mirror(1.0, 1.0, 10.0, False),
    )


def sub_pre_below_pending() -> SubaccountResult:
    """Δ = 20 s. Três eventos: `a` (3 a 100, notional 300) com a posição anterior à janela
    (`touched_zero` falso: o ativo não é rastreado); `b` (0,05 a 100, notional 5), alvo 5 abaixo
    da ordem mínima de 10; `c` (10 a 100, notional 1.000) em 590 s, cujo instante de execução,
    610 s, é depois do fim da janela (600 s): pendente. Fração 1 nos três."""
    bars = {c: flat(100.0) for c in "abc"}
    events = [ev(10_000, "a", 3.0, zero=False), ev(20_000, "b", 0.05), ev(590_000, "c", 10.0)]
    return run(events, bars, delay=20_000)


def sub_cap() -> SubaccountResult:
    """`a` e `b` com razão 1 cada. Evento de `a` em 10 s: g = 1, compra de 10. Evento de `b` em 20
    s: g = 2, f = 0,5: alvo 500, pedido sem teto 1.000 / 100 = 10, executado 5. Fração 1 - 5 / 10 =
    0,5 do notional do evento (1.000): 500 de teto atingido."""
    return run([ev(10_000, "a", 10.0), ev(20_000, "b", 10.0)], {c: flat(100.0) for c in "ab"})


def sub_depth() -> SubaccountResult:
    """Escada de compra com 4 de tamanho: o evento de `a` (10 a 100, alvo 1.000) pede 10 e executa
    4. Fração 1 - 4 / 10 = 0,6 do notional (1.000): 600 de profundidade excedida."""
    bars = {"a": flat(100.0)}
    return run([ev(10_000, "a", 10.0)], bars, feed=Shallow(bars, 4.0))


def sub_excess() -> SubaccountResult:
    """O líder vende 10 de `a` a 100 em 10 s (razão -1, alvo -1.000: vende 10). `a` sobe a 110 em
    60 s e não tem negócio no segundo 120. Em 120 s o líder compra 1 de `b` (razão 0,1). Patrimônio
    1.000 + (-10) x (110 - 100) = 900, teto 1 x 900, exposição 10 x 110 = 1.100: já há excesso de
    200. Visão: g = 1 + 0,1 = 1,1, f = 1 / 1,1, alvo de `a` = -900 / 1,1 = -818,18, e a sobra de `a`
    é 1.100 - 818,18 = 281,82. A redução de `a` não pode ser enviada: `a` não tem observação em
    120 s, e ela é contada. Sem a redução, o aumento de `b` é impedido pela pós-condição do passo 8.
    O excesso fica: 1 execução acima do teto, de 1.100 - 900 = 200 dólares, 200 / 900 = 0,2222 do
    patrimônio. O evento de `b` é teto atingido, fração 1 (nada executou), notional 100."""
    bars = {
        "a": [ProxyBar(s, 100.0, 100.0, 100.0) for s in range(60)]
        + [ProxyBar(s, 110.0, 110.0, 110.0) for s in range(60, SECONDS) if s != 120],
        "b": flat(100.0),
    }
    return run([ev(10_000, "a", -10.0), ev(120_000, "b", 1.0)], bars)


@pytest.mark.unit
def test_non_copy_counters_by_reason() -> None:
    """RF-ANA-04 CA-04.1. Quatro subcontas e fills de papel, somados nos seis motivos, na ordem da
    spec (abaixo do mínimo, teto atingido, profundidade excedida, fora do universo, posição
    anterior à janela, pendente no fim). Cada motivo traz eventos e notional do líder já vezes a
    fração não copiada:
      abaixo do mínimo:  `b`, 5 x 1 = 5.                                        1 evento, 5.
      teto atingido:     `b` da subconta do teto, 1.000 x 0,5 = 500, e `b` da subconta do
                         excesso, 100 x 1 = 100.                               2 eventos, 600.
      profundidade:      1.000 x 0,6 = 600.                                    1 evento, 600.
      fora do universo:  fills de `x` (100) e `y` (50), que não estão no universo {a, b, c}; o de
                         `a` (70) está: 2 fills, 150.
      posição anterior:  `a`, 300 x 1 = 300.                                   1 evento, 300.
      pendente:          `c`, 1.000 x 1 = 1.000.                               1 evento, 1.000.

    Mutação registrada: somar só a primeira subconta (`results[:1]`) deixa todos os motivos das
    demais zerados; trocar a ordem dos motivos em `NON_COPY_REASONS` muda a ordem do resultado;
    nos dois casos o teste cai."""
    results = [sub_pre_below_pending(), sub_cap(), sub_depth(), sub_excess()]
    fills = [("x", 100.0), ("y", 50.0), ("a", 70.0)]
    outside = outside_universe(fills, {"a", "b", "c"})
    counters = non_copy(results, outside)
    assert list(counters) == [
        "below_minimum",
        "cap_reached",
        "depth_exceeded",
        "outside_universe",
        "pre_window",
        "pending",
    ]
    assert tuple(counters) == NON_COPY_REASONS
    expected = {
        "below_minimum": (1, 5.0),
        "cap_reached": (2, 600.0),
        "depth_exceeded": (1, 600.0),
        "outside_universe": (2, 150.0),
        "pre_window": (1, 300.0),
        "pending": (1, 1_000.0),
    }
    for reason, (events, notional) in expected.items():
        assert counters[reason].events == events, reason
        assert counters[reason].notional == pytest.approx(notional), reason


@pytest.mark.unit
def test_each_subaccount_reports_its_own_reasons() -> None:
    """A soma de `non_copy` é a das subcontas: cada uma conta só o que lhe aconteceu (sem
    contaminar as outras), e os motivos que ela não teve ficam em zero."""
    only_cap = non_copy([sub_cap()], NonCopy(0, 0.0))
    assert (only_cap["cap_reached"].events, only_cap["cap_reached"].notional) == (1, 500.0)
    assert all(v == NonCopy(0, 0.0) for k, v in only_cap.items() if k != "cap_reached")
    only_depth = non_copy([sub_depth()], NonCopy(0, 0.0))
    assert only_depth["depth_exceeded"].notional == pytest.approx(600.0)
    assert only_depth["cap_reached"] == NonCopy(0, 0.0)


@pytest.mark.unit
def test_outside_universe_counts_fills_and_notional_of_instruments_not_in_the_universe() -> None:
    """RF-ANA-04 CA-04.1, design §3.8. Cada fill do líder, na janela, em instrumento fora do
    universo conta um e soma o notional dele. Universo {BTC, ETH}: `BTC` (500) e `ETH` (300) não
    contam; `xyz:GOLD` (HIP-3, 40), `PURR/USDC` (spot, 10) e `DOGE` (perpétuo fora, 25) contam: 3
    fills, 75. Sem fills, zero.

    Mutação registrada: contar os fills que estão no universo (`coin in universe`) dá 2 fills e
    800, e o teste cai."""
    fills = [
        ("BTC", 500.0),
        ("xyz:GOLD", 40.0),
        ("ETH", 300.0),
        ("PURR/USDC", 10.0),
        ("DOGE", 25.0),
    ]
    counted = outside_universe(fills, {"BTC", "ETH"})
    assert counted.events == 3 and counted.notional == pytest.approx(75.0)
    assert outside_universe([], {"BTC"}) == NonCopy(0, 0.0)


@pytest.mark.unit
def test_cap_excess_counts_executions_above_the_cap() -> None:
    """RF-SIM-02 CA-02.7, RF-SIM-04. Na subconta do excesso, a execução em 120 s termina com
    exposição 1.100 contra um teto de 1 x 900: 1 execução acima do teto, 200 dólares, 200 / 900 =
    0,2222 do patrimônio. A redução de `a` não foi enviada por falta de preço e foi contada. Uma
    subconta sem excesso soma zero.

    Mutação registrada: o laço deixar de registrar o excesso (`_record_excess` sem efeito) zera os
    três números e o teste cai."""
    result = sub_excess()
    assert result.counters.cap_reduction_without_price == 1
    excess = cap_excess([result])
    assert excess.executions == 1
    assert excess.max_usd == pytest.approx(200.0)
    assert excess.max_fraction == pytest.approx(200.0 / 900.0)
    assert cap_excess([sub_cap()]) == CapExcess(0, 0.0, 0.0)
    assert cap_excess([]) == CapExcess(0, 0.0, 0.0)


@pytest.mark.unit
def test_cap_excess_sums_executions_and_keeps_the_largest_of_each_measure() -> None:
    """Duas subcontas: a primeira com 2 execuções acima do teto, o maior excesso de 100 dólares e
    de 0,1 do patrimônio; a segunda com 3 execuções, 250 dólares e 0,05. Soma de execuções: 5.
    Maior em dólares: 250 (da segunda). Maior em fração: 0,1 (da primeira): os dois máximos são
    independentes.

    Mutação registrada: tomar o máximo das execuções no lugar da soma dá 3, e somar os excessos
    em dólares dá 350; nos dois casos o teste cai."""
    base = sub_cap()
    first = replace(base, counters=Counters(cap_excess_executions=2, max_cap_excess_usd=100.0,
                                            max_cap_excess_fraction=0.1))  # fmt: skip
    second = replace(base, counters=Counters(cap_excess_executions=3, max_cap_excess_usd=250.0,
                                             max_cap_excess_fraction=0.05))  # fmt: skip
    assert cap_excess([first, second]) == CapExcess(5, 250.0, 0.1)
