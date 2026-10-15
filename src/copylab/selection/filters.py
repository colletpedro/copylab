"""Filtros de elegibilidade F1 a F10 e o funil (T-063; RF-SEL-02, design 1.7 §3.6).

Cada filtro é função só dos fatos da carteira e dos parâmetros: nenhum limiar aparece aqui como
literal (RF-SEL-02 CA-02.2). Limiar é inclusivo (design §3.6). Como cada filtro olha só a
carteira, a ordem em que o funil os executa não muda o conjunto final (RF-SEL-02 CA-02.1).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from copylab.exceptions import DataError
from copylab.params import Params
from copylab.selection.facts import WalletFacts
from copylab.selection.reference import Reference
from copylab.timeutil import MS_PER_DAY

__all__ = [
    "ALL_FILTERS",
    "DEFAULT_ORDER",
    "REFERENCE_STAGE",
    "Funnel",
    "FunnelStage",
    "apply_filters",
    "run_funnel",
    "with_reference",
]

#: Ordem de execução: F1 por último, por ser o mais caro de consultar (RF-SEL-02 CA-02.1).
DEFAULT_ORDER: Final = ("F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F1")
ALL_FILTERS: Final = frozenset(DEFAULT_ORDER)
REFERENCE_STAGE: Final = "N*"

Test = Callable[[WalletFacts, str | None, Params], bool]


def _active_blocks(facts: WalletFacts, params: Params) -> int:
    """Blocos de ``f5_block_days`` dias, ``f5_blocks`` deles, que terminam em ``window_end``, com ao
    menos uma abertura. O bloco ``k`` é ``[fim - (n - k) d, fim - (n - k - 1) d)``."""
    f = params.filters
    size = f.f5_block_days * MS_PER_DAY
    active = 0
    for k in range(f.f5_blocks):
        low = facts.window_end - (f.f5_blocks - k) * size
        active += any(low <= t < low + size for t in facts.open_times)
    return active


def _f3(facts: WalletFacts, role: str | None, params: Params) -> bool:
    return (
        facts.coverage_ok
        and facts.n_fills <= params.ingestion.max_fills_per_wallet
        and facts.invalid_perp_fills == 0
        and facts.universe_breaks == 0
        and facts.unreconciled_episodes == 0
        and facts.max_pnl_divergence_bps <= params.reconciliation.pnl_tolerance_bps
    )


def _f6(facts: WalletFacts, role: str | None, params: Params) -> bool:
    median = facts.median_duration_ms
    f = params.filters
    return (
        median is not None and f.f6_min_median_duration_ms <= median <= f.f6_max_median_duration_ms
    )


def _share_at_least(share: float | None, pct: float) -> bool:
    return share is not None and share * 100 >= pct


_TESTS: Final[dict[str, Test]] = {
    "F1": lambda f, role, p: role == p.filters.f1_role,
    "F2": lambda f, role, p: f.account_value >= p.filters.f2_min_account_value_usd,
    "F3": _f3,
    "F4": lambda f, role, p: f.closed_episodes >= p.filters.f4_min_closed_episodes,
    "F5": lambda f, role, p: _active_blocks(f, p) >= p.filters.f5_min_active_blocks,
    "F6": _f6,
    "F7": lambda f, role, p: _share_at_least(
        f.taker_opening_share, p.filters.f7_min_taker_opening_pct
    ),
    "F8": lambda f, role, p: (
        f.median_open_perps is not None
        and f.median_open_perps <= p.filters.f8_max_median_open_perps
    ),
    "F9": lambda f, role, p: _share_at_least(
        f.universe_notional_share, p.filters.f9_min_universe_notional_pct
    ),
    "F10": lambda f, role, p: f.liquidated_fills <= p.filters.f10_max_liquidated_fills,
}


def apply_filters(
    facts: WalletFacts, role: str | None, params: Params, order: Sequence[str] = DEFAULT_ORDER
) -> tuple[str, ...]:
    """Todos os filtros que a carteira reprova, na ordem dada, e não só o primeiro.

    ``role = None`` deixa F1 de fora: o tipo de conta só é coletado para as que passaram nos
    outros filtros (design §3.6). Medida indefinida reprova o filtro que a usa.
    """
    return tuple(
        name
        for name in order
        if (name != "F1" or role is not None) and not _TESTS[name](facts, role, params)
    )


@dataclass(frozen=True, slots=True)
class FunnelStage:
    name: str
    entered: int
    removed: int


@dataclass(frozen=True, slots=True)
class Funnel:
    stages: tuple[FunnelStage, ...]
    survivors: tuple[str, ...]  # endereços, em ordem


def run_funnel(
    facts: Sequence[WalletFacts],
    params: Params,
    roles: Mapping[str, str] | None = None,
    order: Sequence[str] = DEFAULT_ORDER,
) -> Funnel:
    """Executa os filtros em ``order``; cada estágio diz quantas entraram e quantas removeu.

    Uma carteira é removida pelo primeiro estágio que ela reprova. ``roles`` traz o tipo de conta
    de quem chega a F1.

    Raises:
        DataError: ordem que repete ou omite filtro, ou carteira que chega a F1 sem tipo de conta.
    """
    if sorted(order) != sorted(ALL_FILTERS):
        raise DataError(f"A ordem dos filtros precisa ter F1 a F10, uma vez cada: {list(order)}.")
    alive = list(facts)
    stages: list[FunnelStage] = []
    for name in order:
        kept = []
        for wallet in alive:
            role = None
            if name == "F1":
                if roles is None or wallet.address not in roles:
                    raise DataError(f"A carteira {wallet.address} chega a F1 sem tipo de conta.")
                role = roles[wallet.address]
            if _TESTS[name](wallet, role, params):
                kept.append(wallet)
        stages.append(FunnelStage(name, len(alive), len(alive) - len(kept)))
        alive = kept
    return Funnel(tuple(stages), tuple(sorted(w.address for w in alive)))


def with_reference(funnel: Funnel, references: Mapping[str, Reference | None]) -> Funnel:
    """Acrescenta o estágio final ``N*``: sai quem não tem referência de exposição (RF-SEL-03
    CA-03.2). Carteira sem entrada em ``references`` também não tem.
    """
    kept = tuple(a for a in funnel.survivors if references.get(a) is not None)
    stage = FunnelStage(REFERENCE_STAGE, len(funnel.survivors), len(funnel.survivors) - len(kept))
    return Funnel((*funnel.stages, stage), kept)
