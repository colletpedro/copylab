"""Cópia ideal e variante só compras (T-045, ADR-0002 e ADR-0003, RF-SIM-02 CA-02.6).

Fixtures de papel, como em `test_sim_engine.py`: preços escritos à mão, a conta no comentário.
Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.sim.mirror` (cada uma está na docstring do teste que a pega).
"""

from collections.abc import Sequence

import pytest

from copylab.leader import LeaderEvent
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.prices import ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import Ms
from copylab.windows import Window

SECONDS = 400


def ev(t: int, coin: str, position: float, px: float) -> LeaderEvent:
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


def run(
    events: Sequence[LeaderEvent],
    prices: dict[str, list[float]],
    *,
    peak: float,
    constrained: bool,
    long_only: bool = False,
) -> SubaccountResult:
    """Subconta de capital 1.000 sobre N* = 1.000, sem atraso, taxa, slippage nem funding. O preço
    de
    cada ativo em cada segundo é o dado (barra com mínimo = máximo = último)."""
    bars = {c: [ProxyBar(s, p, p, p) for s, p in enumerate(series)] for c, series in prices.items()}
    return run_subaccount(
        LeaderTape(events),
        1_000.0,
        frozenset(prices),
        ProxySource(bars),
        FundingTable({}),
        dict.fromkeys(prices, 0.01),
        1_000.0,
        Window(Ms(0), Ms(SECONDS * 1_000)),
        Frictions(0, {}, 0.0, False, constrained),
        Mirror(peak, 1.0, 10.0, long_only),
    )


@pytest.mark.unit
def test_ideal_copy_reproduces_leader_pnl_at_follower_scale() -> None:
    """ADR-0003. Com atraso zero, sem custo, sem funding e sem restrição de tamanho, numa série em
    que o
    preço observado é o do líder, o PnL do seguidor é o do líder na escala do seguidor, que é `pico
    x
    patrimônio / N*` no momento em que o episódio abre. Pico 0,8, N* = 1.000, capital 1.000. O
    preço do
    ativo é 100 até o segundo 59, 110 de 60 a 119, 120 de 120 a 179 e 100 depois, e o líder opera
    exatamente nesses preços.
    Episódio 1: o líder abre +10 a 100 em 10 s (razão 10 x 100 / 1.000 = 1) e fecha a 110 em 60 s.
    Escala
      k1 = 0,8 x 1.000 / 1.000 = 0,8: o seguidor compra 0,8 x 1 x 1.000 / 100 = 8 e vende a 110:
      PnL 8 x
      10 = 80 = 0,8 x (10 x 10 = 100 do líder). Patrimônio 1.080.
    Episódio 2: o líder abre -5 a 120 em 120 s (razão -0,6) e recompra a 100 em 180 s: PnL do líder
    5 x 20
      = 100. Escala k2 = 0,8 x 1.080 / 1.000 = 0,864: o seguidor vende 0,8 x 0,6 x 1.080 / 120 =
      4,32 e
      recompra: PnL 4,32 x 20 = 86,4 = 0,864 x 100. Patrimônio final 1.080 + 86,4 = 1.166,4.

    Mutação registrada: dimensionar com o capital inicial no lugar do patrimônio atual (`p0` por
    `self.account.capital` nos alvos) deixa o segundo episódio com escala 0,8, PnL 80 e patrimônio
    1.160, e
    o teste cai.
    """
    price = [100.0] * 60 + [110.0] * 60 + [120.0] * 60 + [100.0] * (SECONDS - 180)
    events = [
        ev(10_000, "a", 10.0, 100.0),
        ev(60_000, "a", 0.0, 110.0),
        ev(120_000, "a", -5.0, 120.0),
        ev(180_000, "a", 0.0, 100.0),
    ]
    result = run(events, {"a": price}, peak=0.8, constrained=False)
    buy1, sell1, sell2, buy2 = result.orders
    assert [buy1.executed, sell1.executed] == pytest.approx([8.0, 8.0])
    assert [sell2.executed, buy2.executed] == pytest.approx([4.32, 4.32])
    first = sell1.executed * sell1.price - buy1.executed * buy1.price
    second = sell2.executed * sell2.price - buy2.executed * buy2.price
    assert first == pytest.approx(0.8 * 100.0)
    assert second == pytest.approx(0.864 * 100.0)
    assert result.final_equity == pytest.approx(1_166.4)
    assert result.reconciliation.ok


@pytest.mark.unit
def test_long_only_variant_equals_engine_with_shorts_dropped() -> None:
    """RF-SIM-02 CA-02.6, ADR-0002. `a` com razão +0,3 e `b` com razão -0,3 (g = 0,6, f = 1, teto
    folgado).
    Cópia completa: compra 3 de `a` e vende 3 de `b`. Só compras: o alvo de `b` (-300) vira zero e
    o resto
    é idêntico: as mesmas ordens de `a`, nenhuma de `b`. Com preços parados, o patrimônio não muda
    e as
    ordens de `a` são iguais nas duas rodadas."""
    prices = {"a": [100.0] * SECONDS, "b": [100.0] * SECONDS}
    events = [ev(10_000, "a", 3.0, 100.0), ev(20_000, "b", -3.0, 100.0)]
    full = run(events, prices, peak=1.0, constrained=True)
    only = run(events, prices, peak=1.0, constrained=True, long_only=True)
    assert [(o.coin, o.side, round(o.executed, 6)) for o in full.orders] == [
        ("a", "buy", 3.0),
        ("b", "sell", 3.0),
    ]
    assert [o for o in only.orders] == [o for o in full.orders if o.coin == "a"]
    assert "b" not in only.final_positions


@pytest.mark.unit
def test_long_only_keeps_longs_at_full_copy_size_when_cap_was_active() -> None:
    """RF-SIM-02 CA-02.6: o fator do teto é calculado com todos os ativos, e só depois o alvo
    negativo
    é zerado. O líder está vendido em `b` (razão -0,6) e depois comprado em `a` (razão +0,6): no
    segundo
    evento g = 0,6 + 0,6 = 1,2, f = 1 / 1,2, e o alvo de `a` é 0,6 x 1.000 / 1,2 = 500 (5 de
    tamanho), nas
    duas rodadas. Se a variante cortasse a posição vendida antes do fator (g = 0,6, f = 1),
    compraria 6 de
    `a`, mais que na cópia completa. O primeiro evento: a cópia completa vende 6 de `b`, e a só
    compras não faz nada.

    Mutação registrada: cortar a razão negativa antes do fator (`max(r, 0)` em `ratios`, quando
    `long_only`) faz a variante comprar 6 de `a`, e o teste cai.
    """
    prices = {"a": [100.0] * SECONDS, "b": [100.0] * SECONDS}
    events = [ev(10_000, "b", -6.0, 100.0), ev(20_000, "a", 6.0, 100.0)]
    full = run(events, prices, peak=1.0, constrained=True)
    only = run(events, prices, peak=1.0, constrained=True, long_only=True)
    full_a = [o for o in full.orders if o.coin == "a" and o.reason == "target_increase"]
    assert [round(o.executed, 6) for o in full_a] == [5.0]
    assert [(o.coin, round(o.executed, 6)) for o in only.orders] == [("a", 5.0)]
    assert full.orders[0].coin == "b" and round(full.orders[0].executed, 6) == 6.0
