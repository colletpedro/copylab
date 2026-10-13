"""Métricas de RF-ANA-01 (T-050, design §3.8 e as precisões do 1.6).

Fixtures de papel (RNF-03): curvas e preços escritos à mão, com a conta do valor esperado na
docstring. Nenhum dado real. As subcontas vêm do simulador do Bloco D, com atraso, custo e funding
desligados onde o teste não os mede, para que o resultado seja calculável no papel.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.analytics.metrics` (cada uma está na docstring do teste que a pega).
"""

import math
from collections.abc import Mapping, Sequence

import pytest

from copylab.analytics.metrics import (
    asset_breakdown,
    copied_episodes,
    daily_returns,
    max_drawdown,
    sharpe,
    subaccount_metrics,
)
from copylab.exceptions import DataError
from copylab.leader import LeaderEvent
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.prices import ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms
from copylab.windows import Window

DAY = MS_PER_DAY


def curve(*values: float) -> list[tuple[Ms, float]]:
    """Curva de patrimônio com um ponto por dia: o ponto ``i`` está em ``i`` dias."""
    return [(Ms(i * DAY), v) for i, v in enumerate(values)]


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


def dense(prices: Sequence[float]) -> list[ProxyBar]:
    """Uma barra por segundo, com mínimo = máximo = último = o preço dado."""
    return [ProxyBar(s, p, p, p) for s, p in enumerate(prices)]


def sparse(points: Mapping[int, float]) -> list[ProxyBar]:
    """Barras só nos segundos dados; a marcação usa a última barra anterior."""
    return [ProxyBar(s, p, p, p) for s, p in sorted(points.items())]


def run(
    events: Sequence[LeaderEvent],
    bars: Mapping[str, Sequence[ProxyBar]],
    *,
    end: int,
    peak: float = 1.0,
    fee_bps: float = 0.0,
    rates: Mapping[str, Mapping[Ms, float]] | None = None,
) -> SubaccountResult:
    """Subconta de capital 1.000 sobre N* = 1.000, sem atraso, sem slippage e sem restrição de
    tamanho (o alvo sai exato, sem lote nem mínimo nem teto)."""
    return run_subaccount(
        LeaderTape(events),
        1_000.0,
        frozenset(bars),
        ProxySource(bars),
        FundingTable(rates or {}),
        dict.fromkeys(bars, 0.01),
        1_000.0,
        Window(Ms(0), Ms(end)),
        Frictions(0, {}, fee_bps, rates is not None, False),
        Mirror(peak, 1.0, 10.0, False),
    )


# ─── Retornos e Sharpe ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_daily_returns_are_one_per_consecutive_pair_of_curve_points() -> None:
    """Curva 100, 110, 99: retornos 110/100 - 1 = 0,1 e 99/110 - 1 = -0,1. Um retorno por par de
    pontos consecutivos."""
    assert daily_returns(curve(100.0, 110.0, 99.0)) == pytest.approx([0.1, -0.1])
    assert daily_returns(curve(100.0)) == []


@pytest.mark.unit
def test_daily_returns_refuse_a_nonpositive_base() -> None:
    """Retorno sobre patrimônio zero ou negativo é indefinido: erro explícito, nunca `inf`."""
    with pytest.raises(DataError, match="não é positivo"):
        daily_returns(curve(100.0, 0.0, 50.0))


@pytest.mark.unit
def test_sharpe_uses_sqrt_365_and_zero_risk_free() -> None:
    """RF-ANA-01 CA-01.1. Retornos 0,02; 0; 0,04; 0,02: média 0,02, desvios 0, -0,02, +0,02, 0,
    soma dos quadrados 0,0008, variância amostral 0,0008 / 3 (n - 1 = 3). Razão diária ao quadrado
    = 0,02² / (0,0008 / 3) = 0,0004 x 3 / 0,0008 = 1,5; anualizada, 1,5 x 365 = 547,5. Sharpe =
    √547,5. Com desvio populacional daria √(2 x 365), e sem a anualização, √1,5.

    Mutação registrada: trocar `statistics.stdev` por `statistics.pstdev` (desvio populacional)
    dá √730 e o teste cai; trocar `math.sqrt(periods_per_year)` por `periods_per_year` dá 446 e
    o teste cai."""
    returns = [0.02, 0.0, 0.04, 0.02]
    assert sharpe(returns, 365) == pytest.approx(math.sqrt(547.5))
    assert sharpe(returns, 252) == pytest.approx(math.sqrt(1.5 * 252))


@pytest.mark.unit
def test_sharpe_undefined_when_std_is_zero() -> None:
    """RF-ANA-01 CA-01.2. Retornos todos iguais têm desvio zero: indefinido (`None`), nunca
    `inf` nem `NaN`. Vale também para retornos que só são iguais no papel: a curva 100 x 1,1^i
    rende 10% por dia, e em `float` os cinco retornos diferem na última casa (desvio de 1,6e-16,
    não zero). Menos de dois retornos também não têm desvio.

    Mutação registrada: comparar o desvio com `== 0.0` no lugar da tolerância relativa faz o
    caso da curva de 10% por dia devolver um Sharpe astronômico, e o teste cai."""
    assert sharpe([0.0, 0.0, 0.0], 365) is None
    assert sharpe([0.01, 0.01, 0.01, 0.01], 365) is None
    compounding = daily_returns(curve(*[100.0 * 1.1**i for i in range(6)]))
    assert len(set(compounding)) > 1  # diferem na última casa, e o desvio de `float` não é zero
    assert sharpe(compounding, 365) is None
    assert sharpe([0.01], 365) is None
    assert sharpe([], 365) is None
    assert sharpe([0.01, 0.02], 365) is not None


@pytest.mark.unit
def test_subaccount_sharpe_comes_from_one_return_per_utc_day() -> None:
    """Subconta de capital 1.000 que compra 10 de `a` a 100 (razão 10 x 100 / 1.000 = 1, alvo 1.000)
    e segura por 4 dias UTC. Patrimônio = 1.000 + 10 x (preço - 100). Preços da última barra de
    cada dia: 102 (dia 1), 102 (dia 2, sem barra nova), 106,08 (dia 3) e 108,2016 (dia 4). Curva:
    1.000; 1.020; 1.020; 1.060,8; 1.082,016. Retornos 0,02; 0; 0,04; 0,02 (a conta do teste do
    Sharpe), então Sharpe = √547,5 e retorno líquido 82,016 / 1.000 = 0,082016."""
    bars = {"a": sparse({0: 100.0, 10: 100.0, 40_000: 102.0, 190_000: 106.08, 300_000: 108.2016})}
    result = run([ev(10_000, "a", 10.0)], bars, end=4 * DAY)
    assert [v for _, v in result.equity_curve] == pytest.approx(
        [1_000.0, 1_020.0, 1_020.0, 1_060.8, 1_082.016]
    )
    metrics = subaccount_metrics(result, 365)
    assert metrics.sharpe == pytest.approx(math.sqrt(547.5))
    assert metrics.net_return == pytest.approx(0.082016)
    assert metrics.drawdown is not None and metrics.drawdown.depth == 0.0
    assert metrics.open_episodes == 1 and metrics.closed_episodes == 0 and metrics.hit_rate is None


# ─── Drawdown ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_max_drawdown_uses_running_peak_with_dates() -> None:
    """RF-ANA-01 CA-01.3. Curva 100, 120, 90, 110, 130, 104 (dias 0 a 5). Máximo corrente: 100,
    120, 120, 120, 130, 130. Quedas: 0, 0, (120 - 90) / 120 = 0,25, (120 - 110) / 120 = 0,0833, 0,
    (130 - 104) / 130 = 0,2. A maior é 0,25: pico no dia 1 (120), fundo no dia 2 (90) e recuperação
    no dia 4, o primeiro ponto depois do fundo com patrimônio >= 120 (130). A queda final de 0,2 é
    menor e fica sem recuperar, sem entrar na conta.

    Mutação registrada: medir a queda em relação ao máximo global (130) e não ao corrente dá
    (130 - 90) / 130 = 0,3077 e o teste cai."""
    drawdown = max_drawdown(curve(100.0, 120.0, 90.0, 110.0, 130.0, 104.0))
    assert drawdown.depth == pytest.approx(0.25)
    assert (drawdown.peak_t, drawdown.trough_t, drawdown.recovery_t) == (DAY, 2 * DAY, 4 * DAY)
    assert drawdown.recovered


@pytest.mark.unit
def test_max_drawdown_never_recovered() -> None:
    """Curva 100, 110, 99, 100, 105: pico 110 no dia 1, fundo 99 no dia 2, queda 11 / 110 = 0,1.
    Nenhum ponto seguinte chega a 110 (o maior é 105): sem recuperação, indicado como não
    recuperado.

    Mutação registrada: recuperar contra o início da curva (100) no lugar do pico (110): o ponto do
    dia 3 já bastaria, e o teste cai."""
    drawdown = max_drawdown(curve(100.0, 110.0, 99.0, 100.0, 105.0))
    assert drawdown.depth == pytest.approx(0.1)
    assert (drawdown.peak_t, drawdown.trough_t) == (DAY, 2 * DAY)
    assert drawdown.recovery_t is None and not drawdown.recovered


@pytest.mark.unit
def test_max_drawdown_without_a_fall_and_with_ties() -> None:
    """Curva que só sobe ou fica parada: profundidade 0, nenhuma data, `recovered` verdadeiro.
    Empates: na curva 100, 120, 120, 90 o pico é o dia 1, o primeiro em que 120 foi atingido, e
    um valor igual depois não o desloca. Na curva 100, 90, 100, 90 as duas quedas valem 0,1 e
    vale a primeira (fundo no dia 1, recuperação no dia 2).

    Mutação registrada: `depth >= best` no lugar de `depth > best` escolhe a última queda do
    empate; `e >= peak` no lugar de `e > peak` desloca o pico para o valor igual que vem depois.
    Nos dois casos o teste cai."""
    flat = max_drawdown(curve(100.0, 100.0, 105.0))
    assert flat.depth == 0.0 and flat.recovered
    assert (flat.peak_t, flat.trough_t, flat.recovery_t) == (None, None, None)
    assert max_drawdown(curve(100.0, 120.0, 120.0, 90.0)).peak_t == DAY
    tie = max_drawdown(curve(100.0, 90.0, 100.0, 90.0))
    assert (tie.peak_t, tie.trough_t, tie.recovery_t) == (0, DAY, 2 * DAY)


@pytest.mark.unit
def test_max_drawdown_refuses_an_empty_curve_or_nonpositive_peak() -> None:
    with pytest.raises(DataError, match="vazia"):
        max_drawdown([])
    with pytest.raises(DataError, match="não é positivo"):
        max_drawdown(curve(0.0, -1.0))


# ─── Episódios copiados, taxa de acerto e giro ───────────────────────────────


@pytest.mark.unit
def test_episodes_hit_rate_and_turnover() -> None:
    """Pico 0,8, N* = 1.000, capital 1.000, sem custo. Preço de `a`: 100 até o segundo 59, 110 de
    60 a 119, 120 de 120 a 179, 100 de 180 a 259 e 90 depois. O líder abre +10 a 100 em 10 s
    (razão 1) e fecha em 60 s; abre -5 a 120 em 120 s (razão -0,6) e fecha em 180 s; abre +10 a 100
    em 200 s e fecha em 260 s; abre +10 a 90 em 300 s (razão 0,9) e não fecha.
      Ep. 1: compra 0,8 x 1.000 / 100 = 8 a 100, vende a 110: realizado 80. Patrimônio 1.080.
      Ep. 2: vende 0,8 x 0,6 x 1.080 / 120 = 4,32 a 120, recompra a 100: realizado 86,4. 1.166,4.
      Ep. 3: compra 0,8 x 1.166,4 / 100 = 9,3312 a 100, vende a 90: realizado -93,312. 1.073,088.
      Ep. 4: compra 0,8 x 0,9 x 1.073,088 = 772,62336 de notional a 90 e segue aberto.
    Fechados 3, abertos 1; acertos 2 de 3 (80 e 86,4 contra -93,312), então taxa 2/3: o aberto fica
    de fora. Notional executado: 800 + 880 + 518,4 + 432 + 933,12 + 839,808 + 772,62336 =
    5.175,95136. A curva tem dois pontos (1.000 e 1.073,088), média 1.036,544, e o giro é
    5.175,95136 / 1.036,544.

    Mutação registrada: contar o episódio aberto na taxa de acerto (denominador 4) dá 2/4 e o teste
    cai; dividir o giro pelo capital inicial (1.000) no lugar da média da curva também."""
    prices = [100.0] * 60 + [110.0] * 60 + [120.0] * 60 + [100.0] * 80 + [90.0] * 140
    events = [
        ev(10_000, "a", 10.0, 100.0),
        ev(60_000, "a", 0.0, 110.0),
        ev(120_000, "a", -5.0, 120.0),
        ev(180_000, "a", 0.0, 100.0),
        ev(200_000, "a", 10.0, 100.0),
        ev(260_000, "a", 0.0, 90.0),
        ev(300_000, "a", 10.0, 90.0),
    ]
    result = run(events, {"a": dense(prices)}, end=400_000, peak=0.8)
    episodes = copied_episodes(result.orders, result.payments)
    assert [(e.side, e.opened, e.closed) for e in episodes] == [
        (1, 10_000, 60_000),
        (-1, 120_000, 180_000),
        (1, 200_000, 260_000),
        (1, 300_000, None),
    ]
    assert [e.net for e in episodes[:3]] == pytest.approx([80.0, 86.4, -93.312])
    metrics = subaccount_metrics(result, 365)
    assert (metrics.closed_episodes, metrics.open_episodes) == (3, 1)
    assert metrics.hit_rate == pytest.approx(2 / 3)
    assert result.final_equity == pytest.approx(1_073.088)
    assert metrics.turnover == pytest.approx(5_175.95136 / 1_036.544)
    assert metrics.sharpe is None  # um único retorno: não há desvio amostral


@pytest.mark.unit
def test_funding_belongs_to_the_episode_open_at_the_hour() -> None:
    """Design 1.6: o funding de uma hora H pertence ao episódio com abertura < H <= fechamento. O
    líder compra 5 a 100 em 10 s (alvo 500) e inverte para -5 em 3 h (alvo -500: são duas ordens,
    vender 5 para fechar e vender 5 para abrir). Preço sempre 100. Taxas de funding: 0,0001 em 1 h,
    2 h e 3 h, e 0,0002 em 4 h. A janela termina em 5 h.
      Ep. 1 (compra, de 10 s a 3 h): paga 5 x 100 x 0,0001 = 0,05 em 1 h, 2 h e 3 h. O pagamento de
      3 h vem antes da execução (§4.2), então ainda é da posição comprada: 0,15 no total.
      Ep. 2 (venda, de 3 h em diante): o patrimônio em 3 h, já com o funding pago, é 1.000 - 0,15 =
      999,85, então o alvo é -0,5 x 999,85 = -499,925 e a venda que abre é de 4,99925. Em 4 h:
      -4,99925 x 100 x 0,0002 = -0,099985 (recebe). Segue aberto.
    O episódio 1 fecha com líquido 0 - 0 - 0,15 = -0,15: nenhum acerto em 1 fechado.

    Mutação registrada: atribuir o pagamento de 3 h ao episódio que abre nesse instante (trocar
    `closed < payment.t` por `closed <= payment.t` no avanço do cursor) levanta `SimulationError`
    (o pagamento não cai em nenhum episódio) e o teste cai."""
    hour = MS_PER_HOUR
    rates = {"a": {Ms(1 * hour): 0.0001, Ms(2 * hour): 0.0001, Ms(3 * hour): 0.0001}}
    rates["a"][Ms(4 * hour)] = 0.0002
    bars = {"a": sparse({0: 100.0, 10: 100.0, 10_800: 100.0})}
    events = [ev(10_000, "a", 5.0), ev(3 * hour, "a", -5.0)]
    result = run(events, bars, end=5 * hour, rates=rates)
    first, second = copied_episodes(result.orders, result.payments)
    assert (first.opened, first.closed) == (10_000, 3 * hour)
    assert first.funding == pytest.approx(0.15)
    assert (second.opened, second.closed) == (3 * hour, None)
    assert second.funding == pytest.approx(-0.099985)
    metrics = subaccount_metrics(result, 365)
    assert (metrics.closed_episodes, metrics.open_episodes) == (1, 1)
    assert metrics.hit_rate == 0.0
    assert metrics.funding == pytest.approx(0.050015)  # 0,15 - 0,099985 pagos no total


@pytest.mark.unit
def test_an_episode_with_zero_net_result_is_not_a_hit() -> None:
    """Preço parado em 100 e sem custo: o episódio abre e fecha com resultado líquido exatamente
    zero. "Positivo" é estritamente maior que zero, então a taxa de acerto é 0 de 1.

    Mutação registrada: contar `net >= 0.0` como acerto dá 1,0 e o teste cai."""
    result = run(
        [ev(10_000, "a", 5.0), ev(20_000, "a", 0.0)], {"a": dense([100.0] * 60)}, end=60_000
    )
    assert subaccount_metrics(result, 365).hit_rate == 0.0


# ─── Subconta congelada ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_frozen_subaccount_has_missing_sharpe_and_drawdown_not_nan() -> None:
    """RF-SIM-06 CA-06.4. O líder vende 10 a 100 em 10 s (alvo -1.000, tamanho 10). Último preço de
    cada dia: 110 no dia 1 e 120 no dia 2, e 250 a partir do segundo 200.000. Patrimônio = 1.000 -
    10 x (preço - 100): 900 na meia-noite 1, 800 na 2 e, no evento seguinte, em 250.000 s, o
    marcado é 1.000 - 10 x 150 = -500: a subconta congela ali e a curva termina em -500.
    A curva 1.000; 900; 800; -500 tem três retornos (-0,1; -0,111; -1,625) e, com desvio, daria um
    Sharpe numérico. Mas Sharpe e drawdown pressupõem patrimônio positivo: saem `None`, e não
    `NaN`. O retorno líquido segue definido, -500 / 1.000 - 1 = -1,5. A venda deixa 1 episódio
    aberto, e o giro é 1.000 / média(1.000, 900, 800, -500) = 1.000 / 550.

    Mutação registrada: calcular o Sharpe sem o teste de curva positiva (`if positive else None`)
    devolve um número e o teste cai; o mesmo vale para o drawdown, que daria 1,5."""
    bars = {"a": sparse({0: 100.0, 10: 100.0, 40_000: 110.0, 100_000: 120.0, 200_000: 250.0})}
    bars["a"].append(ProxyBar(250_000, 250.0, 250.0, 250.0))
    events = [ev(10_000, "a", -10.0), ev(250_000_000, "a", -12.0)]
    result = run(events, bars, end=4 * DAY)
    assert result.frozen and result.frozen_at == 250_000_000
    assert [v for _, v in result.equity_curve] == pytest.approx([1_000.0, 900.0, 800.0, -500.0])
    metrics = subaccount_metrics(result, 365)
    assert metrics.frozen
    assert metrics.sharpe is None and metrics.drawdown is None
    assert metrics.net_return == pytest.approx(-1.5)
    assert metrics.open_episodes == 1 and metrics.hit_rate is None
    assert metrics.turnover == pytest.approx(1_000.0 / 550.0)


# ─── Resultado por ativo e por grupo ─────────────────────────────────────────


@pytest.mark.unit
def test_result_breaks_down_by_asset_and_two_groups() -> None:
    """RF-ANA-01 CA-01.4. Taxa de 10 bps, N* = 1.000, capital 1.000, pico 1. `BTC` vale 100 até o
    segundo 59 e 110 depois; `DOGE` vale 50 até o 99 e 45 depois.
      BTC: o líder abre 5 a 100 em 10 s (razão 0,5, alvo 500, compra 5, taxa 0,001 x 500 = 0,5) e
      fecha em 60 s: vende 5 a 110, realizado 50, taxa 0,001 x 550 = 0,55. Líquido 50 - 1,05 =
      48,95.
      DOGE: o líder vende 4 a 50 em 20 s (razão -0,2). Patrimônio nesse instante: 1.000 - 0,5 =
      999,5, alvo -0,2 x 999,5 = -199,9, tamanho 3,998 vendido a 50, taxa 0,1999. Fica aberto; o
      preço final é 45: não realizado 3,998 x (50 - 45) = 19,99. Líquido 19,99 - 0,1999 = 19,7901.
    Grupos: BTC e ETH (sem atividade, zero) de um lado: 48,95; DOGE e LIT (zero) do outro: 19,7901.
    A soma dos ativos é o resultado da subconta: 48,95 + 19,7901 = 68,7401 = 1.068,7401 - 1.000.

    Mutação registrada: esquecer o não realizado de DOGE (`row(coin)[1] += ...`) deixa o grupo dos
    demais em -0,1999 e o teste cai; não somar as taxas das ordens também."""
    bars = {
        "BTC": dense([100.0] * 60 + [110.0] * 340),
        "DOGE": dense([50.0] * 100 + [45.0] * 300),
    }
    events = [ev(10_000, "BTC", 5.0), ev(20_000, "DOGE", -4.0, 50.0), ev(60_000, "BTC", 0.0, 110.0)]
    result = run(events, bars, end=400_000, fee_bps=10.0)
    assert result.final_equity == pytest.approx(1_068.7401)
    breakdown = asset_breakdown([result], {"BTC", "ETH", "DOGE", "LIT"})
    assert [a.coin for a in breakdown.by_asset] == ["BTC", "DOGE", "ETH", "LIT"]
    btc, doge, eth, lit = breakdown.by_asset
    assert (btc.realized, btc.unrealized, btc.fees) == pytest.approx((50.0, 0.0, 1.05))
    assert btc.net == pytest.approx(48.95)
    assert (doge.realized, doge.unrealized, doge.fees) == pytest.approx((0.0, 19.99, 0.1999))
    assert doge.net == pytest.approx(19.7901)
    assert btc.orders == 2 and btc.notional == pytest.approx(1_050.0)
    assert eth.net == lit.net == 0.0 and eth.orders == 0
    assert breakdown.majors.coins == ("BTC", "ETH")
    assert breakdown.majors.net == pytest.approx(48.95)
    assert breakdown.others.coins == ("DOGE", "LIT")
    assert breakdown.others.net == pytest.approx(19.7901)
    assert sum(a.net for a in breakdown.by_asset) == pytest.approx(result.final_equity - 1_000.0)


@pytest.mark.unit
def test_asset_breakdown_sums_over_subaccounts() -> None:
    """Duas subcontas idênticas (mesmo líder e mesmo preço) somam o dobro por ativo: a mesma
    compra de 5 de `BTC` a 100, que vale 110 no fim, é +50 de não realizado em cada uma. Preço
    parado até o segundo 59, 110 depois; o líder abre 5 em 10 s e não fecha."""
    bars = {"BTC": dense([100.0] * 60 + [110.0] * 340)}
    one = run([ev(10_000, "BTC", 5.0)], bars, end=400_000)
    breakdown = asset_breakdown([one, one], {"BTC"})
    assert breakdown.by_asset[0].unrealized == pytest.approx(100.0)
    assert breakdown.majors.net == pytest.approx(100.0)
    assert breakdown.others.coins == ()
