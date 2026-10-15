"""Fatos por carteira (T-063; design 1.7 §3.6, "Fatos por carteira").

:func:`wallet_facts` lê os fills da carteira na janela uma vez e calcula tudo o que os filtros F2
a F10 pedem. Não recebe ``Params``: guarda o dado, e cada filtro (``filters.py``) aplica o
limiar. Medida indefinida (sem episódio fechado, sem notional, sem tempo em posição) é ``None``.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass

import polars as pl

from copylab.leader import (
    PERP,
    build_episodes,
    build_events,
    continuity_breaks,
    ignored_fills,
    pnl_violations,
)
from copylab.ports import BoundedRepository
from copylab.selection.assets import fill_notional
from copylab.selection.universe import has_ok_coverage
from copylab.stats import median, weighted_percentile
from copylab.timeutil import Ms
from copylab.windows import Window

__all__ = ["WalletFacts", "lots_from_meta", "wallet_facts"]

#: A "mediana" de F8: o tipo da estatística, e não um número do estudo (design 1.8).
_MEDIAN_PCT = 50


def lots_from_meta(meta: pl.DataFrame) -> dict[str, float]:
    """Tamanho de lote de cada perpétuo do primeiro dex: ``10^-sz_decimals`` (RF-ING-05 CA-05.2)."""
    return {
        str(coin): 10.0 ** -int(decimals)
        for coin, decimals in meta.select("coin", "sz_decimals").rows()
    }


@dataclass(frozen=True, slots=True)
class WalletFacts:
    address: str
    window_end: Ms
    account_value: float  # F2
    coverage_ok: bool  # F3
    n_fills: int  # F3
    invalid_perp_fills: int  # F3: fill de perpétuo do primeiro dex sem campo interpretável
    universe_breaks: int  # F3: quebras de continuidade em ativo do universo
    unreconciled_episodes: int  # F3: episódio do universo sem divergência de PnL calculável
    max_pnl_divergence_bps: float  # F3: maior divergência entre os que conciliam (0 se nenhum)
    closed_episodes: int  # F4
    open_times: tuple[Ms, ...]  # F5: abertura a partir de zero, no universo, fechado ou não
    median_duration_ms: float | None  # F6
    taker_opening_share: float | None  # F7
    median_open_perps: float | None  # F8
    universe_notional_share: float | None  # F9
    liquidated_fills: int  # F10


def _median_open_perps(
    fills: pl.DataFrame, lots: Mapping[str, float], window: Window
) -> float | None:
    """Mediana ponderada pelo tempo do número de perpétuos com posição, só com ao menos um aberto.

    Um ativo cujo primeiro evento tem posição anterior fora de zero está aberto desde o início
    da janela (design 1.7, "F8 em detalhe").
    """
    events = build_events(fills, lots)
    is_open: dict[str, bool] = {}
    for event in events:
        is_open.setdefault(event.coin, event.prev_position != 0.0)
    count = sum(is_open.values())
    weights: dict[float, int] = {}
    previous: int = window.start
    for event in events:
        if count > 0 and event.t > previous:
            weights[float(count)] = weights.get(float(count), 0) + (event.t - previous)
        count += (event.position != 0.0) - is_open[event.coin]
        is_open[event.coin] = event.position != 0.0
        previous = max(previous, event.t)
    if count > 0 and window.end > previous:
        weights[float(count)] = weights.get(float(count), 0) + (window.end - previous)
    return weighted_percentile(weights.items(), _MEDIAN_PCT)


def wallet_facts(
    repo: BoundedRepository,
    address: str,
    window: Window,
    universe: Set[str],
    lots: Mapping[str, float],
    account_value: float,
) -> WalletFacts:
    """Calcula uma vez os fatos de ``address`` na janela de seleção.

    Raises:
        LookaheadError: a janela passa do corte do repositório.
        DataError: fills sem as colunas do livro-razão, ou perpétuo do primeiro dex sem lote.
    """
    fills = repo.fills(address, window.start, window.end)
    perps = fills.filter(pl.col("kind") == PERP)
    episodes = [e for e in build_episodes(fills, lots) if e.coin in universe]
    flat = [e for e in episodes if e.opened_from_flat]
    closed = [e for e in flat if e.closed is not None]
    # `pnl_violations` com tolerância -1 devolve todo episódio conferível com a divergência dele
    # (que nunca é negativa): o que falta na resposta não concilia (divergência `None`).
    reconciled = pnl_violations(fills, closed, -1.0)
    opening = sum(e.opening_notional for e in flat)
    all_notional = float(fills.select(fill_notional()).to_series().sum())
    in_universe = float(
        fills.filter(pl.col("coin").is_in(list(universe))).select(fill_notional()).to_series().sum()
    )
    return WalletFacts(
        address=address,
        window_end=window.end,
        account_value=account_value,
        coverage_ok=has_ok_coverage(repo, address, window),
        n_fills=fills.height,
        invalid_perp_fills=ignored_fills(perps),
        universe_breaks=sum(b.coin in universe for b in continuity_breaks(fills, lots)),
        unreconciled_episodes=len(closed) - len(reconciled),
        max_pnl_divergence_bps=max((d for _, d in reconciled), default=0.0),
        closed_episodes=len(closed),
        open_times=tuple(sorted(e.opened for e in flat)),
        median_duration_ms=median([e.closed - e.opened for e in closed if e.closed is not None])
        if closed
        else None,
        taker_opening_share=(sum(e.opening_taker_notional for e in flat) / opening)
        if opening > 0.0
        else None,
        median_open_perps=_median_open_perps(fills, lots, window),
        universe_notional_share=in_universe / all_notional if all_notional > 0.0 else None,
        liquidated_fills=fills.filter(
            pl.col("liquidated_user").str.to_lowercase() == address.lower()
        ).height,
    )
