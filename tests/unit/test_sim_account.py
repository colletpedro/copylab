"""Contabilidade da subconta e identidade de conciliação (T-040, design §5).

Fixtures de papel (RNF-03): a conta de cada valor esperado está no comentário do teste. Nenhum
dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.sim.account` (cada uma está na docstring do teste que a pega).
"""

import pytest

from copylab.exceptions import SimulationError
from copylab.sim.account import Subaccount, reconcile
from copylab.sim.model import FundingPayment, Order, Side
from copylab.timeutil import Ms


def order(coin: str, side: Side, size: float, price: float, fee: float = 0.0) -> Order:
    return Order(Ms(0), Ms(0), Ms(0), coin, side, size, size, price, fee, "target_increase")


def trade(account: Subaccount, orders: list[Order], placed: Order) -> float:
    orders.append(placed)
    return account.trade(placed.coin, placed.signed, placed.price, placed.fee)


@pytest.mark.unit
def test_equity_is_cash_plus_unrealized_at_mark() -> None:
    """RF-SIM-06 CA-06.1. Capital 1.000. Compra de 2 a 100: o saldo não muda (abrir não realiza
    nada). Marcação 110: não realizado 2 x (110 - 100) = 20, patrimônio 1.020.
    Venda de 3 a 50 em outro ativo: tamanho -3, custo 50. Marcação 40: 3 x ... = -3 x (40 - 50)
    = +30. Patrimônio total 1.000 + 20 + 30 = 1.050."""
    account = Subaccount(1_000.0)
    account.trade("BTC", 2.0, 100.0, 0.0)
    assert account.equity({"BTC": 110.0}) == pytest.approx(1_020.0)
    account.trade("ETH", -3.0, 50.0, 0.0)
    assert account.equity({"BTC": 110.0, "ETH": 40.0}) == pytest.approx(1_050.0)
    assert account.gross_exposure({"BTC": 110.0, "ETH": 40.0}) == pytest.approx(2 * 110 + 3 * 40)
    assert account.open_coins() == ["BTC", "ETH"]


@pytest.mark.unit
def test_average_cost_and_realization_when_reducing_and_closing() -> None:
    """Compra de 2 a 100 e de 2 a 110: custo médio (2 x 100 + 2 x 110) / 4 = 105, nada realizado.
    Venda de 1 a 125: realiza 1 x (125 - 105) = 20, resta 3. Venda de 3 a 100 (fecha): realiza
    3 x (100 - 105) = -15; saldo 1.000 + 20 - 15 = 1.005, posição zero e custo zerado.
    Vendido: venda de 3 a 50; compra de 1 a 45 realiza 1 x (45 - 50) x (-1) = 5; compra de 2 a 60
    realiza 2 x (60 - 50) x (-1) = -20.

    Mutação registrada: tirar o sinal da posição de `realized` (vendido ganharia com a alta)
    faz o trecho vendido cair.
    """
    account = Subaccount(1_000.0)
    account.trade("BTC", 2.0, 100.0, 0.0)
    account.trade("BTC", 2.0, 110.0, 0.0)
    assert account.size("BTC") == 4.0
    assert account.avg_cost("BTC") == pytest.approx(105.0)
    assert account.realized == 0.0
    assert account.trade("BTC", -1.0, 125.0, 0.0) == pytest.approx(20.0)
    assert account.trade("BTC", -3.0, 100.0, 0.0) == pytest.approx(-15.0)
    assert (account.size("BTC"), account.avg_cost("BTC")) == (0.0, 0.0)
    assert account.cash == pytest.approx(1_005.0)
    account.trade("ETH", -3.0, 50.0, 0.0)
    assert account.trade("ETH", 1.0, 45.0, 0.0) == pytest.approx(5.0)
    assert account.trade("ETH", 2.0, 60.0, 0.0) == pytest.approx(-20.0)
    assert account.size("ETH") == 0.0


@pytest.mark.unit
def test_crossing_zero_is_two_orders_and_one_execution_cannot_cross() -> None:
    """Design §5: cruzar o zero são duas ordens. Comprado de 4 a 100: uma venda de 10 a 110
    numa execução só é recusada. Em duas: a primeira fecha 4 e realiza 4 x (110 - 100) = 40; a
    segunda abre vendido de 6 a 110, sem realizar nada, com custo 110."""
    account = Subaccount(1_000.0)
    account.trade("BTC", 4.0, 100.0, 0.0)
    with pytest.raises(SimulationError, match="cruza o zero"):
        account.trade("BTC", -10.0, 110.0, 0.0)
    assert account.trade("BTC", -4.0, 110.0, 0.0) == pytest.approx(40.0)
    assert account.trade("BTC", -6.0, 110.0, 0.0) == 0.0
    assert account.size("BTC") == -6.0
    assert account.avg_cost("BTC") == pytest.approx(110.0)


@pytest.mark.unit
def test_taker_fee_is_debited_and_counted() -> None:
    """RF-SIM-04 CA-04.1, no nível da conta. Compra de 2 a 100 com taxa 0,5: o saldo cai 0,5 e
    o contador de taxas sobe 0,5, sem realizar nada. Venda de 2 a 110 com taxa 0,55 realiza 20:
    saldo 1.000 - 0,5 + 20 - 0,55 = 1.018,95, taxas 1,05."""
    account = Subaccount(1_000.0)
    account.trade("BTC", 2.0, 100.0, 0.5)
    assert (account.cash, account.fees, account.realized) == (999.5, 0.5, 0.0)
    account.trade("BTC", -2.0, 110.0, 0.55)
    assert account.cash == pytest.approx(1_018.95)
    assert account.fees == pytest.approx(1.05)


@pytest.mark.unit
def test_funding_payment_sign_and_amount() -> None:
    """RF-SIM-05 CA-05.1. Pagamento = tamanho com sinal x marcação x taxa, debitado quando
    positivo (taxa positiva: o comprado paga).
      comprado de 2, marcação 100, taxa 0,0001: 2 x 100 x 0,0001 = +0,02, debita.
      vendido de 2, taxa 0,0001: -2 x 100 x 0,0001 = -0,02, credita.
      vendido de 2, taxa negativa -0,0001: -2 x 100 x -0,0001 = +0,02, debita (o vendido paga).
    O contador de funding pago acumula com sinal: 0,02 - 0,02 + 0,02 = 0,02."""
    account = Subaccount(1_000.0)
    account.trade("BTC", 2.0, 100.0, 0.0)
    account.trade("ETH", -2.0, 100.0, 0.0)
    assert account.pay_funding("BTC", 100.0, 0.0001) == pytest.approx(0.02)
    assert account.pay_funding("ETH", 100.0, 0.0001) == pytest.approx(-0.02)
    assert account.pay_funding("ETH", 100.0, -0.0001) == pytest.approx(0.02)
    assert account.funding_paid == pytest.approx(0.02)
    assert account.cash == pytest.approx(1_000.0 - 0.02)


@pytest.mark.unit
def test_no_position_no_funding() -> None:
    """RF-SIM-05 CA-05.2: sem posição, o pagamento é zero, qualquer que seja a taxa."""
    account = Subaccount(1_000.0)
    assert account.pay_funding("BTC", 100.0, 0.5) == 0.0
    assert (account.cash, account.funding_paid) == (1_000.0, 0.0)


@pytest.mark.unit
def test_reconciliation_identity_closes() -> None:
    """RF-SIM-06 CA-06.2. Capital 1.000, taxa de 0,1% do notional.
      compra de 2 a 100 (taxa 0,2); compra de 2 a 110 (taxa 0,22): custo médio 105;
      venda de 1 a 125 (taxa 0,125): realiza 20; funding pago 0,03.
      vendido: venda de 3 de ETH a 50 (taxa 0,15) e funding recebido -0,01.
      inversão de LINK: compra de 4 a 10 (0,04), venda de 4 a 12 (0,048) realiza 8, venda de 6
      a 12 (0,072) abre vendido.
    Fim, com marcação BTC 120, ETH 40, LINK 11:
      realizado = 20 + 8 = 28.
      não realizado = BTC 3 x (120 - 105) = 45, ETH -3 x (40 - 50) = 30, LINK -6 x (11 - 12) = 6,
        total 81.
      taxas = 0,2 + 0,22 + 0,125 + 0,15 + 0,04 + 0,048 + 0,072 = 0,855. Funding = 0,03 - 0,01 =
        0,02.
      lado direito = 28 + 81 - 0,855 - 0,02 = 108,125. Patrimônio final = 1.108,125.
    As parcelas saem só das listas de ordens e de pagamentos.

    Mutação registrada: não debitar a taxa do saldo (`cash += realized`), ou não debitar o
    funding, ou realizar com o custo médio errado, deixa a identidade aberta, e o teste cai.
    """
    account = Subaccount(1_000.0)
    orders: list[Order] = []
    payments: list[FundingPayment] = []
    trade(account, orders, order("BTC", "buy", 2.0, 100.0, 0.2))
    trade(account, orders, order("BTC", "buy", 2.0, 110.0, 0.22))
    trade(account, orders, order("BTC", "sell", 1.0, 125.0, 0.125))
    amount = account.pay_funding("BTC", 120.0, 0.03 / (3 * 120.0))
    payments.append(FundingPayment(Ms(1), "BTC", 3.0, 120.0, 0.03 / (3 * 120.0), amount))
    trade(account, orders, order("ETH", "sell", 3.0, 50.0, 0.15))
    amount = account.pay_funding("ETH", 40.0, 0.01 / (3 * 40.0))
    payments.append(FundingPayment(Ms(2), "ETH", -3.0, 40.0, 0.01 / (3 * 40.0), amount))
    trade(account, orders, order("LINK", "buy", 4.0, 10.0, 0.04))
    trade(account, orders, order("LINK", "sell", 4.0, 12.0, 0.048))
    trade(account, orders, order("LINK", "sell", 6.0, 12.0, 0.072))
    marks = {"BTC": 120.0, "ETH": 40.0, "LINK": 11.0}

    final = account.equity(marks)
    rec = reconcile(1_000.0, final, orders, payments, marks)
    assert rec.realized == pytest.approx(28.0)
    assert rec.unrealized == pytest.approx(81.0)
    assert rec.fees == pytest.approx(0.855)
    assert rec.funding == pytest.approx(0.02)
    assert rec.rhs == pytest.approx(108.125)
    assert final == pytest.approx(1_108.125)
    assert rec.ok
    assert abs(rec.residual) < 1e-9


@pytest.mark.unit
def test_reconciliation_detects_an_order_missing_from_the_list() -> None:
    """O conferente tem dente do outro lado: uma ordem executada que não está na lista abre a
    identidade. Compra de 2 a 100 (na lista) e de 1 a 100 com taxa 0,5 (fora da lista),
    marcação 110. Saldo: 1.000 - 0,5; patrimônio 999,5 + 3 x 10 = 1.029,5, esquerdo 29,5.
    Pela lista: 2 x 10 = 20 de não realizado, sem taxa; direito 20. Resíduo 9,5."""
    account = Subaccount(1_000.0)
    orders: list[Order] = []
    trade(account, orders, order("BTC", "buy", 2.0, 100.0))
    account.trade("BTC", 1.0, 100.0, 0.5)  # a ordem sumiu da lista
    rec = reconcile(1_000.0, account.equity({"BTC": 110.0}), orders, [], {"BTC": 110.0})
    assert rec.residual == pytest.approx(9.5)
    assert not rec.ok


@pytest.mark.unit
def test_reconciliation_holds_with_open_short_and_negative_equity() -> None:
    """A identidade vale também com posição vendida aberta e com patrimônio negativo (subconta
    congelada, design §5). Capital 100, vendida de 10 a 50 (taxa 1). Marcação 70: não realizado
    10 x ... = -10 x (70 - 50) = -200; patrimônio 100 - 1 - 200 = -101.
    Lado direito: 0 + (-200) - 1 - 0 = -201; lado esquerdo: -101 - 100 = -201."""
    account = Subaccount(100.0)
    orders: list[Order] = []
    trade(account, orders, order("BTC", "sell", 10.0, 50.0, 1.0))
    final = account.equity({"BTC": 70.0})
    assert final == pytest.approx(-101.0)
    rec = reconcile(100.0, final, orders, [], {"BTC": 70.0})
    assert rec.rhs == pytest.approx(-201.0)
    assert rec.ok
