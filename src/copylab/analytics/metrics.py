"""Métricas de uma subconta e da carteira (RF-ANA-01; design §3.8, precisões do 1.6).

Retornos diários, Sharpe, drawdown, episódios copiados, taxa de acerto, giro e resultado por
ativo. Lógica pura sobre :class:`~copylab.sim.loop.SubaccountResult`: nada aqui lê dado, relógio
ou arquivo.

Métrica que pressupõe patrimônio positivo (Sharpe, drawdown) sai ``None`` quando algum ponto da
curva não é positivo, nunca ``NaN`` (RF-SIM-06 CA-06.4).
"""

import math
import statistics
from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass
from itertools import pairwise

from copylab.exceptions import DataError, SimulationError
from copylab.sim.account import Subaccount
from copylab.sim.loop import SubaccountResult
from copylab.sim.model import FundingPayment, Order
from copylab.timeutil import Ms, iso

__all__ = [
    "MAJORS",
    "AssetBreakdown",
    "AssetResult",
    "CopiedEpisode",
    "Drawdown",
    "GroupResult",
    "Metrics",
    "asset_breakdown",
    "asset_results",
    "build_metrics",
    "copied_episodes",
    "daily_returns",
    "hit_rate",
    "max_drawdown",
    "sharpe",
    "subaccount_metrics",
    "turnover",
]

#: Os três ativos do primeiro grupo da quebra de RF-ANA-01 CA-01.4 (BTC, ETH e SOL), que é de
#: onde a constante vem. É definição de relatório, e não parâmetro pré-registrado: a quebra é
#: informativa e não entra no veredito.
MAJORS = frozenset({"BTC", "ETH", "SOL"})

#: Desvio considerado zero, relativo ao maior retorno em módulo. Tolerância de ponto flutuante,
#: como a da conciliação, e não parâmetro do estudo: retornos matematicamente iguais, tirados de
#: uma curva em ``float``, diferem na última casa.
_ZERO_STD = 1e-12

Curve = Sequence[tuple[Ms, float]]


def _sign(x: float) -> int:
    return (x > 0.0) - (x < 0.0)


# ─── Retornos, Sharpe e drawdown ─────────────────────────────────────────────


def daily_returns(equity: Curve) -> list[float]:
    """Um retorno por par de pontos consecutivos da curva: ``E_k / E_{k-1} - 1``.

    Raises:
        DataError: se o patrimônio de um ponto que serve de base não é positivo.
    """
    returns: list[float] = []
    for (t0, e0), (_, e1) in pairwise(equity):
        if not e0 > 0.0:
            raise DataError(f"Retorno indefinido: o patrimônio {e0} em {iso(t0)} não é positivo.")
        returns.append(e1 / e0 - 1.0)
    return returns


def sharpe(returns: Sequence[float], periods_per_year: int) -> float | None:
    """``média / desvio-padrão amostral * √periods_per_year``, com taxa livre de risco zero
    (RF-ANA-01 CA-01.1). ``None`` com menos de dois retornos ou com desvio zero (CA-01.2)."""
    if len(returns) < 2:
        return None
    std = statistics.stdev(returns)
    if std <= _ZERO_STD * max(abs(r) for r in returns):
        return None
    return statistics.fmean(returns) / std * math.sqrt(periods_per_year)


@dataclass(frozen=True, slots=True)
class Drawdown:
    """A maior queda em relação ao máximo corrente, com as datas (RF-ANA-01 CA-01.3).

    Sem queda, ``depth`` é 0, as três datas são ``None`` e ``recovered`` é verdadeiro.
    """

    depth: float  # fração do pico, >= 0
    peak_t: Ms | None
    trough_t: Ms | None
    recovery_t: Ms | None  # primeiro ponto depois do fundo com patrimônio >= pico

    @property
    def recovered(self) -> bool:
        return self.depth == 0.0 or self.recovery_t is not None


def max_drawdown(equity: Curve) -> Drawdown:
    """Maior ``(pico - patrimônio) / pico``. O pico é o primeiro ponto em que o máximo corrente
    foi atingido, e o fundo é o primeiro da maior queda.

    Raises:
        DataError: curva vazia, ou máximo corrente que não é positivo.
    """
    if not equity:
        raise DataError("Drawdown de uma curva vazia.")
    peak_t, peak = equity[0]
    best = 0.0
    best_peak_t: Ms | None = None
    best_peak = 0.0
    best_index = -1
    for index, (t, e) in enumerate(equity):
        if e > peak:
            peak_t, peak = t, e
        if not peak > 0.0:
            raise DataError(f"O máximo corrente {peak} em {iso(t)} não é positivo.")
        depth = (peak - e) / peak
        if depth > best:
            best, best_peak_t, best_peak, best_index = depth, peak_t, peak, index
    if best_index < 0:
        return Drawdown(0.0, None, None, None)
    recovery = next((t for t, e in equity[best_index + 1 :] if e >= best_peak), None)
    return Drawdown(best, best_peak_t, equity[best_index][0], recovery)


# ─── Episódios copiados ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CopiedEpisode:
    """Episódio da própria subconta: a posição dela num ativo sai de zero e volta a zero."""

    coin: str
    side: int  # +1 ou -1
    opened: Ms  # instante de execução da ordem que abriu
    closed: Ms | None  # idem, da que fechou; ``None`` se segue aberto no fim da janela
    realized: float
    fees: float
    funding: float  # funding pago na posição, positivo quando o seguidor pagou

    @property
    def net(self) -> float:
        """Resultado líquido: realizado, menos taxas, menos funding pago."""
        return self.realized - self.fees - self.funding


@dataclass(slots=True)
class _Draft:
    coin: str
    side: int
    opened: Ms
    closed: Ms | None = None
    realized: float = 0.0
    fees: float = 0.0
    funding: float = 0.0


def _replay(orders: Sequence[Order]) -> list[_Draft]:
    """Refaz a contabilidade ordem a ordem (a mesma de :class:`Subaccount`) e fecha os rascunhos
    de episódio com PnL realizado e taxas."""
    account = Subaccount(0.0)
    open_drafts: dict[str, _Draft] = {}
    drafts: list[_Draft] = []
    for order in orders:
        coin = order.coin
        flat_before = account.size(coin) == 0.0
        realized = account.trade(coin, order.signed, order.price, order.fee)
        after = account.size(coin)
        if flat_before:
            draft = _Draft(coin, _sign(after), order.exec_t)
            open_drafts[coin] = draft
            drafts.append(draft)
        draft = open_drafts[coin]
        draft.realized += realized
        draft.fees += order.fee
        if after == 0.0:
            draft.closed = order.exec_t
            del open_drafts[coin]
    return drafts


def copied_episodes(
    orders: Sequence[Order], payments: Sequence[FundingPayment]
) -> tuple[CopiedEpisode, ...]:
    """Os episódios copiados de uma subconta, na ordem em que abriram.

    A inversão são duas ordens: um episódio que fecha e outro que abre no mesmo instante. O
    funding de uma hora ``H`` pertence ao episódio aberto em ``H`` com ``abertura < H <=
    fechamento``, porque o funding precede a execução no mesmo instante (design §4.2).

    Raises:
        SimulationError: se um pagamento de funding não cai em nenhum episódio (defeito do laço).
    """
    drafts = _replay(orders)
    by_coin: dict[str, list[_Draft]] = {}
    for draft in drafts:
        by_coin.setdefault(draft.coin, []).append(draft)
    cursor = dict.fromkeys(by_coin, 0)
    for payment in payments:
        episodes = by_coin.get(payment.coin, [])
        index = cursor.get(payment.coin, 0)
        while index < len(episodes):
            closed = episodes[index].closed
            if closed is not None and closed < payment.t:
                index += 1
            else:
                break
        cursor[payment.coin] = index
        if index == len(episodes) or not episodes[index].opened < payment.t:
            raise SimulationError(
                f"O funding de {payment.coin} em {iso(payment.t)} não cai em nenhum episódio."
            )
        episodes[index].funding += payment.amount
    return tuple(
        CopiedEpisode(d.coin, d.side, d.opened, d.closed, d.realized, d.fees, d.funding)
        for d in drafts
    )


def hit_rate(episodes: Iterable[CopiedEpisode]) -> float | None:
    """Fração dos episódios fechados com resultado líquido estritamente positivo. Os abertos
    no fim da janela ficam de fora. ``None`` sem episódio fechado."""
    closed = [e for e in episodes if e.closed is not None]
    if not closed:
        return None
    return sum(e.net > 0.0 for e in closed) / len(closed)


def turnover(notional: float, equity: Curve) -> float | None:
    """Notional executado dividido pela média dos patrimônios da curva. ``None`` se a média não
    é positiva."""
    mean = statistics.fmean(e for _, e in equity)
    return notional / mean if mean > 0.0 else None


# ─── Métricas de uma subconta ou da carteira ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class Metrics:
    """RF-ANA-01: retorno líquido, Sharpe, drawdown, episódios, acerto, taxas, funding, giro e
    alavancagem máxima observada."""

    capital: float
    final_equity: float
    net_return: float
    sharpe: float | None
    drawdown: Drawdown | None
    closed_episodes: int
    open_episodes: int
    hit_rate: float | None
    fees: float
    funding: float
    turnover: float | None
    max_leverage: float
    max_leverage_at: Ms | None
    frozen: bool


def build_metrics(
    *,
    capital: float,
    curve: Curve,
    episodes: Sequence[CopiedEpisode],
    notional: float,
    fees: float,
    funding: float,
    max_leverage: float,
    max_leverage_at: Ms | None,
    frozen: bool,
    periods_per_year: int,
) -> Metrics:
    """Monta as métricas de uma curva e dos episódios dela. Compartilhada pela subconta e pela
    carteira."""
    final = curve[-1][1]
    positive = all(e > 0.0 for _, e in curve)
    return Metrics(
        capital=capital,
        final_equity=final,
        net_return=final / capital - 1.0,
        sharpe=sharpe(daily_returns(curve), periods_per_year) if positive else None,
        drawdown=max_drawdown(curve) if positive else None,
        closed_episodes=sum(e.closed is not None for e in episodes),
        open_episodes=sum(e.closed is None for e in episodes),
        hit_rate=hit_rate(episodes),
        fees=fees,
        funding=funding,
        turnover=turnover(notional, curve),
        max_leverage=max_leverage,
        max_leverage_at=max_leverage_at,
        frozen=frozen,
    )


def subaccount_metrics(result: SubaccountResult, periods_per_year: int) -> Metrics:
    """As métricas de RF-ANA-01 de uma subconta."""
    return build_metrics(
        capital=result.equity_curve[0][1],
        curve=result.equity_curve,
        episodes=copied_episodes(result.orders, result.payments),
        notional=sum(o.notional for o in result.orders),
        fees=result.fees,
        funding=result.funding_paid,
        max_leverage=result.max_leverage,
        max_leverage_at=result.max_leverage_at,
        frozen=result.frozen,
        periods_per_year=periods_per_year,
    )


# ─── Resultado por ativo e por grupo ─────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AssetResult:
    """O resultado líquido de um ativo: realizado e não realizado, menos taxas e funding pago."""

    coin: str
    realized: float
    unrealized: float
    fees: float
    funding: float
    orders: int
    notional: float

    @property
    def net(self) -> float:
        return self.realized + self.unrealized - self.fees - self.funding


@dataclass(frozen=True, slots=True)
class GroupResult:
    """A soma de um grupo de ativos (RF-ANA-01 CA-01.4)."""

    coins: tuple[str, ...]
    realized: float
    unrealized: float
    fees: float
    funding: float

    @property
    def net(self) -> float:
        return self.realized + self.unrealized - self.fees - self.funding


@dataclass(frozen=True, slots=True)
class AssetBreakdown:
    """O resultado por ativo e nos dois grupos. Informativo: não entra no veredito."""

    by_asset: tuple[AssetResult, ...]
    majors: GroupResult
    others: GroupResult


def asset_results(results: Iterable[SubaccountResult]) -> dict[str, AssetResult]:
    """O resultado por ativo, somado nas subcontas, em ordem alfabética.

    O PnL realizado refaz a contabilidade da lista de ordens; o não realizado usa a posição e a
    marcação finais; taxas e funding vêm das ordens e dos pagamentos.
    """
    rows: dict[str, list[float]] = {}  # realizado, não realizado, taxas, funding, ordens, notional

    def row(coin: str) -> list[float]:
        return rows.setdefault(coin, [0.0] * 6)

    for result in results:
        account = Subaccount(0.0)
        for order in result.orders:
            r = row(order.coin)
            r[0] += account.trade(order.coin, order.signed, order.price, order.fee)
            r[2] += order.fee
            r[4] += 1
            r[5] += order.notional
        for payment in result.payments:
            row(payment.coin)[3] += payment.amount
        for coin, (size, avg) in result.final_positions.items():
            row(coin)[1] += size * (result.final_marks[coin] - avg)
    return {
        coin: AssetResult(coin, r[0], r[1], r[2], r[3], int(r[4]), r[5])
        for coin, r in sorted(rows.items())
    }


def _group(coins: Iterable[str], table: dict[str, AssetResult]) -> GroupResult:
    names = tuple(sorted(coins))
    rows = [table[c] for c in names]
    return GroupResult(
        names,
        sum(r.realized for r in rows),
        sum(r.unrealized for r in rows),
        sum(r.fees for r in rows),
        sum(r.funding for r in rows),
    )


def asset_breakdown(
    results: Sequence[SubaccountResult], universe: Set[str], majors: Set[str] = MAJORS
) -> AssetBreakdown:
    """O resultado por ativo e nos dois grupos de RF-ANA-01 CA-01.4: ``majors`` de um lado, os
    demais ativos do universo do outro. Ativo do universo sem atividade entra com zero."""
    table = asset_results(results)
    for coin in universe:
        table.setdefault(coin, AssetResult(coin, 0.0, 0.0, 0.0, 0.0, 0, 0.0))
    table = dict(sorted(table.items()))
    return AssetBreakdown(
        by_asset=tuple(table.values()),
        majors=_group((c for c in table if c in majors), table),
        others=_group((c for c in table if c not in majors), table),
    )
