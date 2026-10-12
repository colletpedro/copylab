"""Espelhamento: os passos 1 a 11 de design §4.3 (RF-SIM-02, ADR-0002, ADR-0008).

O :class:`Engine` guarda a visão do líder e executa um evento por vez, no instante efetivo
``tau``. Ele não decide quando acordar nem lê o cursor: recebe o evento, o instante nominal e
``tau``, e usa a fonte de preço já presa ao cursor. Tudo o que é dinheiro passa pela
:class:`~copylab.sim.account.Subaccount`.

Os números do dimensionamento (``P0``, posições dos demais ativos) são marcados com ``mark``
em ``tau``. A cotação de um lado é o preço do primeiro nível da escada, com o slippage já
aplicado contra o seguidor; o preço pago é o médio dos níveis percorridos.
"""

import math
from collections.abc import Mapping, Set
from dataclasses import dataclass, field

from copylab.exceptions import DataError
from copylab.leader import LeaderEvent
from copylab.sim.account import Subaccount
from copylab.sim.model import Level, Order, Side
from copylab.sim.prices import PriceSource
from copylab.timeutil import Ms

__all__ = [
    "REASONS",
    "Counters",
    "Engine",
    "Frictions",
    "Mirror",
]

_BPS = 1e4
#: Folga relativa de ponto flutuante nas comparações de tamanho e de exposição.
_EPS = 1e-12

BELOW_MINIMUM = "below_minimum"
CAP_REACHED = "cap_reached"
DEPTH_EXCEEDED = "depth_exceeded"
PRE_WINDOW = "pre_window"
PENDING = "pending"
#: Os cinco motivos de não cópia que saem do laço (RF-ANA-04 CA-04.1); o sexto, "fora do
#: universo", sai da tabela de fills.
REASONS = (BELOW_MINIMUM, CAP_REACHED, DEPTH_EXCEEDED, PRE_WINDOW, PENDING)


@dataclass(frozen=True, slots=True)
class Frictions:
    """O que o cenário liga: atraso, slippage por ativo, taxa, funding e restrições de tamanho
    (lote, ordem mínima e teto)."""

    delay_ms: int
    slippage_bps: Mapping[str, float]
    fee_bps: float
    funding: bool
    size_constraints: bool


@dataclass(frozen=True, slots=True)
class Mirror:
    """A regra de espelhamento (ADR-0002): ``peak`` e ``cap`` multiplicam o patrimônio,
    ``min_notional`` é a ordem mínima, e ``long_only`` zera os alvos negativos."""

    peak: float
    cap: float
    min_notional: float
    long_only: bool


@dataclass(slots=True)
class Counters:
    """Contadores de não cópia e de eventos de exceção, acumulados pelo motor."""

    not_copied_events: dict[str, int] = field(default_factory=lambda: dict.fromkeys(REASONS, 0))
    not_copied_notional: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(REASONS, 0.0)
    )
    unobserved_changes: int = 0
    cap_reduction_below_minimum: int = 0
    cap_reduction_without_price: int = 0
    cap_excess_executions: int = 0
    max_cap_excess_usd: float = 0.0
    max_cap_excess_fraction: float = 0.0
    events_executed: int = 0

    def not_copied(self, reason: str, notional: float) -> None:
        self.not_copied_events[reason] += 1
        self.not_copied_notional[reason] += notional


def _sign(x: float) -> int:
    return (x > 0.0) - (x < 0.0)


@dataclass(slots=True)
class _Ladder:
    tau: Ms
    quote: float
    levels: list[list[float]]  # [preço, tamanho restante]


@dataclass(slots=True)
class _Cuts:
    """O que cortou a ordem do evento, para o motivo de não cópia."""

    cap: bool = False
    minimum: bool = False
    depth: bool = False


class Engine:
    """O espelhamento de uma subconta."""

    def __init__(
        self,
        *,
        account: Subaccount,
        prices: PriceSource,
        lots: Mapping[str, float],
        reference: float,
        universe: Set[str],
        frictions: Frictions,
        mirror: Mirror,
    ) -> None:
        self.account = account
        self.orders: list[Order] = []
        self.counters = Counters()
        self.frozen = False
        self._prices = prices
        self._lots = lots
        self._reference = reference
        self._universe = universe
        self._frictions = frictions
        self._mirror = mirror
        self._fee_rate = frictions.fee_bps / _BPS
        self._view: dict[str, tuple[float, float]] = {}
        self._tracked: set[str] = set()
        self._ladders: dict[tuple[str, Side], _Ladder] = {}

    # ─── Marcação ────────────────────────────────────────────────────────────

    def marks(self, t: Ms, extra: str | None = None) -> dict[str, float]:
        """Marcação dos ativos com posição, e de ``extra`` se dado."""
        coins = set(self.account.open_coins())
        if extra is not None:
            coins.add(extra)
        return {coin: self._prices.mark(coin, t) for coin in sorted(coins)}

    # ─── Escada ──────────────────────────────────────────────────────────────

    def _ladder(self, coin: str, tau: Ms, side: Side) -> _Ladder:
        """A escada do par (ativo, lado) em ``tau``, com o consumo das ordens anteriores do
        mesmo instante. O slippage entra no preço de cada nível, contra o seguidor."""
        held = self._ladders.get((coin, side))
        if held is not None and held.tau == tau:
            return held
        slip = self._frictions.slippage_bps.get(coin, 0.0) / _BPS
        factor = 1.0 + slip if side == "buy" else 1.0 - slip
        levels: tuple[Level, ...] = self._prices.ladder(coin, tau, side)
        fresh = _Ladder(tau, levels[0].price * factor, [[v.price * factor, v.size] for v in levels])
        self._ladders[(coin, side)] = fresh
        return fresh

    @staticmethod
    def _walk(levels: list[list[float]], size: float) -> tuple[float, float, list[float]]:
        """Percorre os níveis até ``size``: tamanho executado, preço médio e o que cada nível
        perdeu. Sem efeito: quem quer consumir o aplica."""
        left = size
        cost = 0.0
        taken: list[float] = []
        for price, available in levels:
            take = min(left, available)
            taken.append(take)
            cost += take * price
            left -= take
            if left <= 0.0:
                break
        executed = size - max(left, 0.0)
        return executed, (cost / executed if executed > 0.0 else levels[0][0]), taken

    # ─── Lote ────────────────────────────────────────────────────────────────

    def _lot(self, coin: str) -> float:
        lot = self._lots.get(coin)
        if lot is None or not lot > 0.0:
            raise DataError(f"Sem tamanho de lote positivo para {coin}.")
        return lot

    def _floor_lot(self, coin: str, size: float) -> float:
        lot = self._lot(coin)
        return math.floor(size / lot + 1e-9) * lot

    # ─── Execução de uma ordem ───────────────────────────────────────────────

    def _send(
        self, event: LeaderEvent, nominal: Ms, tau: Ms, coin: str, side: Side, size: float,
        reason: str, cuts: _Cuts | None,
    ) -> float:  # fmt: skip
        """Executa ``size`` percorrendo a escada. Devolve o tamanho executado, com sinal."""
        ladder = self._ladder(coin, tau, side)
        executed, price, taken = self._walk(ladder.levels, size)
        if executed <= 0.0:
            if cuts is not None:
                cuts.depth = True
            return 0.0
        for level, amount in zip(ladder.levels, taken, strict=False):
            level[1] -= amount
        if executed < size * (1 - _EPS) and cuts is not None:
            cuts.depth = True
        fee = self._fee_rate * executed * price
        signed = executed if side == "buy" else -executed
        self.account.trade(coin, signed, price, fee)
        self.orders.append(
            Order(event.t, nominal, tau, coin, side, size, executed, price, fee, reason)
        )
        return signed

    # ─── O evento ────────────────────────────────────────────────────────────

    def process(self, event: LeaderEvent, nominal: Ms, tau: Ms) -> None:
        """Executa o evento em ``tau`` (§4.3). Eventos de ativo fora do universo não entram."""
        coin = event.coin
        if coin not in self._universe:
            return
        counters = self.counters
        # 1. Visão do líder: este evento e os já processados.
        if event.unobserved:
            counters.unobserved_changes += 1
        if event.touched_zero:
            self._tracked.add(coin)
        self._view[coin] = (event.position, event.px)
        counters.events_executed += 1

        # 2. Patrimônio.
        marks = self.marks(tau)
        p0 = self.account.equity(marks)
        if p0 <= 0.0:
            self.frozen = True
            return
        mirror = self._mirror
        constrained = self._frictions.size_constraints

        # 3 a 5. Razões, fator do teto e alvos.
        ratios = {
            j: self._view[j][0] * self._view[j][1] / self._reference for j in sorted(self._tracked)
        }
        g = mirror.peak * sum(abs(r) for r in ratios.values())
        f = min(1.0, mirror.cap / g) if constrained and g > 0.0 else 1.0
        targets = {j: mirror.peak * f * r * p0 for j, r in ratios.items()}
        if mirror.long_only:
            targets = {j: max(t, 0.0) for j, t in targets.items()}
        target_c = targets.get(coin, 0.0)
        wanted_c = mirror.peak * ratios.get(coin, 0.0) * p0  # com f = 1, para a não cópia
        if mirror.long_only:
            wanted_c = max(wanted_c, 0.0)
        cuts = _Cuts(cap=f < 1.0 - _EPS)

        # 6. Reduções exigidas pelo teto, nos demais ativos.
        if constrained:
            self._cap_reductions(event, nominal, tau, marks, p0, targets, target_c)

        # 7 a 10. A ordem em c.
        executed_c = self._order_in_c(event, nominal, tau, target_c, cuts)

        # Não cópia (RF-ANA-04).
        if coin not in self._tracked:
            counters.not_copied(PRE_WINDOW, event.notional)
        else:
            self._account_non_copy(event, tau, executed_c, wanted_c, cuts)
        self._record_excess(tau)

    def _cap_reductions(
        self, event: LeaderEvent, nominal: Ms, tau: Ms, marks: Mapping[str, float], p0: float,
        targets: Mapping[str, float], target_c: float,
    ) -> None:  # fmt: skip
        coin = event.coin
        cap_usd = self._mirror.cap * p0
        values = {j: self.account.size(j) * marks[j] for j in marks if j != coin}
        projected = sum(abs(v) for v in values.values()) + abs(target_c)
        excess = projected - cap_usd
        if excess <= _EPS * max(1.0, cap_usd):
            return
        spare: dict[str, float] = {}
        for j in sorted(values):
            target = targets.get(j, 0.0)
            kept = abs(target) if _sign(target) == _sign(values[j]) else 0.0
            if abs(values[j]) > kept:
                spare[j] = abs(values[j]) - kept
        total = sum(spare.values())
        if total <= 0.0:
            return
        for j, room in spare.items():
            dollars = room * min(excess, total) / total
            self._reduce(event, nominal, tau, j, values[j], dollars)

    def _reduce(
        self, event: LeaderEvent, nominal: Ms, tau: Ms, coin: str, value: float, dollars: float
    ) -> None:
        """Uma redução exigida pelo teto, em ``coin``, de ``dollars`` à cotação."""
        if self._prices.available_from(coin, tau) != tau:
            self.counters.cap_reduction_without_price += 1
            return
        side: Side = "buy" if value < 0.0 else "sell"
        quote = self._ladder(coin, tau, side).quote
        held = abs(self.account.size(coin))
        size = dollars / quote
        closing = size >= held * (1 - _EPS)
        size = held if closing else self._floor_lot(coin, size)
        if size <= 0.0 or (not closing and size * quote < self._mirror.min_notional):
            self.counters.cap_reduction_below_minimum += 1
            return
        self._send(event, nominal, tau, coin, side, size, "cap_reduction", None)

    def _order_in_c(
        self, event: LeaderEvent, nominal: Ms, tau: Ms, target: float, cuts: _Cuts
    ) -> float:
        """Passos 7 a 10 em ``event.coin``. Devolve o tamanho executado, com sinal."""
        coin = event.coin
        size_c = self.account.size(coin)
        value = size_c * self._prices.mark(coin, tau) if size_c != 0.0 else 0.0
        if abs(target - value) <= _EPS * max(1.0, abs(target), abs(value)):
            return 0.0
        side: Side = "buy" if target > value else "sell"
        direction = 1 if side == "buy" else -1
        quote = self._ladder(coin, tau, side).quote
        delta = target / quote - size_c
        if _sign(delta) != direction:
            return 0.0
        want = abs(delta)
        reducing = min(want, abs(size_c)) if _sign(size_c) == -direction else 0.0
        increasing = want - reducing
        constrained = self._frictions.size_constraints
        executed = 0.0

        if reducing > 0.0:
            held = abs(size_c)
            closing = reducing >= held * (1 - _EPS)
            size = (
                held if closing else (self._floor_lot(coin, reducing) if constrained else reducing)
            )
            if constrained and not closing and size * quote < self._mirror.min_notional:
                cuts.minimum = True
            elif size > 0.0:
                executed += self._send(event, nominal, tau, coin, side, size, "target_reduce", cuts)

        if increasing > 0.0:
            executed += self._increase(event, nominal, tau, side, quote, increasing, cuts)
        return executed

    def _increase(
        self, event: LeaderEvent, nominal: Ms, tau: Ms, side: Side, quote: float, want: float,
        cuts: _Cuts,
    ) -> float:  # fmt: skip
        coin = event.coin
        size = want
        if self._frictions.size_constraints:
            lot = self._lot(coin)
            requested = self._floor_lot(coin, want)
            if requested <= 0.0:
                if want * quote < self._mirror.min_notional:
                    cuts.minimum = True
                return 0.0
            lots_allowed = self._max_lots(coin, tau, side, round(requested / lot))
            size = lots_allowed * lot
            if size < requested - lot / 2:
                cuts.cap = True
            if size <= 0.0:
                return 0.0
            if size * quote < self._mirror.min_notional:
                cuts.minimum = True
                return 0.0
        return self._send(event, nominal, tau, coin, side, size, "target_increase", cuts)

    def _max_lots(self, coin: str, tau: Ms, side: Side, requested_lots: int) -> int:
        """O maior número de lotes, até o pedido, cuja execução deixa a subconta dentro do
        teto (§4.3 passo 8), com a posição inteira em ``coin`` ao preço médio da ordem e a taxa
        descontada. Bisseção sobre uma condição que só piora com o tamanho."""
        account = self.account
        lot = self._lot(coin)
        marks = self.marks(tau)
        others = [j for j in marks if j != coin]
        unreal_others = sum(account.size(j) * (marks[j] - account.avg_cost(j)) for j in others)
        abs_others = sum(abs(account.size(j)) * marks[j] for j in others)
        size_c, avg_c = account.size(coin), account.avg_cost(coin)
        direction = 1 if side == "buy" else -1
        levels = self._ladder(coin, tau, side).levels

        def feasible(count: int) -> bool:
            executed, price, _ = (
                self._walk(levels, count * lot) if count else (0.0, levels[0][0], [])
            )
            equity = (
                account.cash + unreal_others + size_c * (price - avg_c)
                - self._fee_rate * executed * price
            )  # fmt: skip
            exposure = abs_others + abs(size_c + direction * executed) * price
            limit = self._mirror.cap * equity
            return equity > 0.0 and exposure <= limit + _EPS * max(1.0, abs(limit))

        low, high = 0, requested_lots
        if not feasible(0):
            return 0
        while low < high:
            mid = (low + high + 1) // 2
            if feasible(mid):
                low = mid
            else:
                high = mid - 1
        return low

    # ─── Contabilidade do evento ─────────────────────────────────────────────

    def _account_non_copy(
        self, event: LeaderEvent, tau: Ms, executed: float, wanted_target: float, cuts: _Cuts
    ) -> None:
        """Fração não copiada: ``1 - executado / pedido``, com o pedido sem teto, mínimo, lote
        nem profundidade (design §3.8). O motivo é a primeira restrição que cortou."""
        coin = event.coin
        size_c = self.account.size(coin) - executed  # tamanho antes das ordens do evento
        value = size_c * self._prices.mark(coin, tau) if size_c != 0.0 else 0.0
        if abs(wanted_target - value) <= _EPS * max(1.0, abs(wanted_target), abs(value)):
            return
        side: Side = "buy" if wanted_target > value else "sell"
        quote = self._ladder(coin, tau, side).quote
        wanted = wanted_target / quote - size_c
        if wanted == 0.0:
            return
        fraction = min(1.0, max(0.0, 1.0 - executed / wanted))
        if fraction <= 1e-9:
            return
        reason = (
            CAP_REACHED if cuts.cap else BELOW_MINIMUM if cuts.minimum
            else DEPTH_EXCEEDED if cuts.depth else None
        )  # fmt: skip
        if reason is not None:
            self.counters.not_copied(reason, event.notional * fraction)

    def _record_excess(self, tau: Ms) -> None:
        """Conta a execução que terminou com exposição acima de ``teto * patrimônio``."""
        marks = self.marks(tau)
        equity = self.account.equity(marks)
        limit = self._mirror.cap * equity
        gross = self.account.gross_exposure(marks)
        if gross > limit * (1 + 1e-9) + 1e-12:
            c = self.counters
            c.cap_excess_executions += 1
            over = gross - limit
            c.max_cap_excess_usd = max(c.max_cap_excess_usd, over)
            if equity > 0.0:
                c.max_cap_excess_fraction = max(c.max_cap_excess_fraction, over / equity)
