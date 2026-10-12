"""Entradas do simulador presas ao cursor (T-041, design §3.7; RF-SIM-01 CA-01.3,
RF-SIM-03 CA-03.1).

Fixtures de papel: instantes e preços escritos à mão. Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez (cada uma está na
docstring do teste que a pega).
"""

import math

import pytest

from copylab.exceptions import DataError, LookaheadError, SimulationError
from copylab.leader import LeaderEvent
from copylab.sim.cursor import Cursor
from copylab.sim.funding import FundingTable
from copylab.sim.model import Level
from copylab.sim.prices import ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import Ms


def event(t: int, coin: str, position: float = 1.0, px: float = 100.0) -> LeaderEvent:
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


# ─── Cursor ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cursor_only_moves_forward_and_its_view_cannot_move_it() -> None:
    cursor = Cursor(Ms(1_000))
    view = cursor.view()
    cursor.advance(Ms(2_000))
    cursor.advance(Ms(2_000))  # parado no mesmo instante é permitido
    assert view.now == 2_000
    with pytest.raises(SimulationError, match="só avança"):
        cursor.advance(Ms(1_999))
    assert not hasattr(view, "advance")
    before = view.closed
    cursor.close()
    after = view.closed
    assert (before, after) == (False, True)
    with pytest.raises(SimulationError, match="fechado"):
        cursor.advance(Ms(3_000))


# ─── Fita do líder ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_reading_beyond_information_set_raises() -> None:
    """RF-SIM-01 CA-01.3. Eventos do líder em 1.000 e 2.000, atraso de 500 ms.
    Cursor em 1.400: só se pode ler até 1.400 - 500 = 900. Nenhum evento tem instante até 900,
    e pedir 901 levanta. Cursor em 1.500: o limite é 1.000, que devolve o primeiro evento;
    1.001 levanta. Preço e marcação além do cursor levantam; no cursor, não.

    Mutação registrada: ignorar o atraso em `BoundTape.until` (limite = cursor) deixa o
    primeiro caso ler até 1.400 sem erro, e o teste cai; trocar `t > self._cursor.now` por
    `t > self._cursor.now + 1_000` na fonte de preço faz o último trecho cair.
    """
    cursor = Cursor(Ms(1_400))
    tape = LeaderTape([event(2_000, "BTC"), event(1_000, "BTC")]).bind(cursor.view(), 500)
    assert len(tape.until(Ms(900))) == 0
    with pytest.raises(LookaheadError, match="só se pode ler até"):
        tape.until(Ms(901))
    cursor.advance(Ms(1_500))
    assert [e.t for e in tape.until(Ms(1_000))] == [1_000]
    with pytest.raises(LookaheadError):
        tape.until(Ms(1_001))

    bars = {"BTC": [ProxyBar(5, 99.0, 101.0, 100.0)]}
    prices = ProxySource(bars).bind(cursor.view())
    cursor.advance(Ms(5_000))
    assert prices.ladder("BTC", Ms(5_000), "buy") == (Level(101.0),)
    with pytest.raises(LookaheadError):
        prices.ladder("BTC", Ms(5_001), "buy")
    with pytest.raises(LookaheadError):
        prices.mark("BTC", Ms(5_001))


@pytest.mark.unit
def test_tape_gives_instants_and_events_in_order_and_hides_the_whole_tape_until_the_end() -> None:
    """`until` devolve os eventos em ordem de instante e, no empate, de ativo; `next_wake` só
    o instante do próximo evento depois de um instante dado, ou `None`. A fita solta não tem
    método de leitura, e a fita inteira só abre depois que o cursor fecha."""
    events = [event(3_000, "ETH"), event(1_000, "SOL"), event(1_000, "BTC"), event(2_000, "BTC")]
    cursor = Cursor(Ms(10_000))
    loose = LeaderTape(events)
    tape = loose.bind(cursor.view(), 0)
    assert [(e.t, e.coin) for e in tape.until(Ms(2_000))] == [
        (1_000, "BTC"),
        (1_000, "SOL"),
        (2_000, "BTC"),
    ]
    assert [e.coin for e in tape.until(Ms(10_000))[1:3]] == ["SOL", "BTC"]
    assert tape.until(Ms(2_000))[-1].t == 2_000
    assert (tape.next_wake(Ms(0)), tape.next_wake(Ms(1_000)), tape.next_wake(Ms(3_000))) == (
        1_000,
        2_000,
        None,
    )
    assert not hasattr(loose, "until")
    with pytest.raises(LookaheadError, match="depois que o laço termina"):
        tape.all_events()
    cursor.close()
    assert len(tape.all_events()) == 4


# ─── Funding ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_funding_read_beyond_cursor_raises() -> None:
    """Taxas das horas 3.600.000 e 7.200.000 de BTC. Cursor em 3.600.000: a primeira lê, a
    segunda levanta. Hora sem registro é `DataError`, e não zero.

    Mutação registrada: trocar `hour > self._cursor.now` por `hour > self._cursor.now +
    3_600_000` deixa a segunda hora ler sem erro, e o teste cai.
    """
    cursor = Cursor(Ms(3_600_000))
    funding = FundingTable({"BTC": {Ms(3_600_000): 0.0001, Ms(7_200_000): -0.0002}})
    bound = funding.bind(cursor.view())
    assert bound.rate("BTC", Ms(3_600_000)) == 0.0001
    with pytest.raises(LookaheadError):
        bound.rate("BTC", Ms(7_200_000))
    cursor.advance(Ms(7_200_000))
    assert bound.rate("BTC", Ms(7_200_000)) == -0.0002
    cursor.advance(Ms(10_800_000))
    with pytest.raises(DataError, match="Sem taxa"):
        bound.rate("BTC", Ms(10_800_000))
    assert not hasattr(funding, "rate")


# ─── Fonte da Rota A ─────────────────────────────────────────────────────────

# BTC com negócio nos segundos 100, 101 e 103; não há negócio no 102.
BARS = {
    "BTC": [
        ProxyBar(100, 98.0, 102.0, 99.0),
        ProxyBar(101, 97.0, 105.0, 104.0),
        ProxyBar(103, 90.0, 95.0, 92.0),
    ]
}


@pytest.mark.unit
def test_route_a_uses_worst_price_of_execution_second() -> None:
    """RF-SIM-03 CA-03.1. Executar em 101.500, no segundo 101: a compra sai ao máximo do segundo
    (105) e a venda ao mínimo (97), com um nível só e tamanho infinito. O slippage é do motor,
    não da fonte.

    Mutação registrada: trocar `high` e `low` (compra ao mínimo, venda ao máximo) faz o teste
    cair.
    """
    cursor = Cursor(Ms(101_500))
    prices = ProxySource(BARS).bind(cursor.view())
    (buy,) = prices.ladder("BTC", Ms(101_500), "buy")
    (sell,) = prices.ladder("BTC", Ms(101_500), "sell")
    assert (buy.price, sell.price) == (105.0, 97.0)
    assert math.isinf(buy.size)
    with pytest.raises(DataError, match="Sem negócio"):
        cursor.advance(Ms(102_500))
        prices.ladder("BTC", Ms(102_500), "buy")


@pytest.mark.unit
def test_available_from_gives_instants_only() -> None:
    """Segundo com negócio: o próprio instante. Segundo sem negócio (102): o início do primeiro
    segundo posterior com negócio, 103.000. Depois do último negócio, ou ativo sem série:
    `None`."""
    prices = ProxySource(BARS).bind(Cursor(Ms(0)).view())
    assert prices.available_from("BTC", Ms(101_999)) == 101_999
    assert prices.available_from("BTC", Ms(102_300)) == 103_000
    assert prices.available_from("BTC", Ms(99_000)) == 99_000 + 1_000  # primeiro negócio: 100
    assert prices.available_from("BTC", Ms(103_999)) == 103_999
    assert prices.available_from("BTC", Ms(104_000)) is None
    assert prices.available_from("ETH", Ms(100_000)) is None


@pytest.mark.unit
def test_mark_is_last_price_of_the_last_second_before_the_execution_second() -> None:
    """Marcação em 103.500 (segundo 103): o último preço do último segundo anterior com
    negócio, o 101, que é 104. Em 101.500, o do segundo 100: 99. Em 100.500 não há segundo
    anterior: `DataError`. Marcar não lê o segundo de `t`, e por isso não move o horizonte."""
    cursor = Cursor(Ms(103_500))
    prices = ProxySource(BARS).bind(cursor.view())
    assert prices.mark("BTC", Ms(103_500)) == 104.0
    assert prices.mark("BTC", Ms(101_500)) == 99.0
    with pytest.raises(DataError, match="antes de"):
        prices.mark("BTC", Ms(100_500))
    assert prices.horizon() < 0


@pytest.mark.unit
def test_horizon_is_the_start_of_the_most_advanced_second_read() -> None:
    """O horizonte é o início do segundo mais avançado cujo preço `ladder` leu: 101.000 depois
    de executar em 101.500, e 103.000 depois de executar em 103.200. Não recua."""
    cursor = Cursor(Ms(101_500))
    prices = ProxySource(BARS).bind(cursor.view())
    prices.ladder("BTC", Ms(101_500), "buy")
    assert prices.horizon() == 101_000
    cursor.advance(Ms(103_200))
    prices.ladder("BTC", Ms(103_200), "sell")
    prices.ladder("BTC", Ms(101_700), "sell")
    assert prices.horizon() == 103_000


@pytest.mark.unit
def test_proxy_bars_must_be_in_strict_order() -> None:
    with pytest.raises(DataError, match="ordem estrita"):
        ProxySource({"BTC": [ProxyBar(5, 1.0, 1.0, 1.0), ProxyBar(5, 1.0, 1.0, 1.0)]})
