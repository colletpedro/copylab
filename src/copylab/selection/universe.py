"""Ativos candidatos e universo por regra (T-061; RF-SEL-08, design 1.7 §3.6).

:func:`candidate_assets` lê, pelo ``BoundedRepository``, os fills das carteiras do pool com
cobertura ``ok`` e junta, por perpétuo do primeiro dex: notional, número de fills, a condição
(i) e a conferência do proxy. :func:`form_universe` aplica as cinco condições na ordem e guarda,
para cada ativo, a primeira que o excluiu. O universo é função só das candidatas, dos custos
medidos e dos parâmetros: quando o pool cresce, é refeito do zero (RF-SEL-07 CA-07.2).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import polars as pl

from copylab.costs import CostEntry
from copylab.exceptions import DataError
from copylab.leader import PERP
from copylab.params import Params
from copylab.ports import BoundedRepository
from copylab.selection.assets import fill_notional
from copylab.selection.proxycheck import ProxyCheck, check_proxy
from copylab.timeutil import MS_PER_DAY, MS_PER_SECOND, Ms, utc_day
from copylab.windows import Window

__all__ = [
    "STATUS_OK",
    "AssetDecision",
    "AssetFacts",
    "Candidates",
    "Condition",
    "Universe",
    "candidate_assets",
    "form_universe",
    "has_ok_coverage",
]

#: O status de cobertura que conta. Mesmo valor de ``copylab.ingestion.fills.STATUS_OK``, que
#: a seleção não importa; um teste confere que os dois coincidem.
STATUS_OK: Final = "ok"

Condition = Literal["i", "ii", "iii", "iv", "v"]

_FILL_COLUMNS: Final = ("coin", "kind", "time_ms", "px", "sz")


def has_ok_coverage(repo: BoundedRepository, address: str, window: Window) -> bool:
    """A última linha de cobertura cuja janela é exatamente ``window`` tem status ``ok``."""
    rows = repo.coverage(address, window.start, window.end).filter(
        (pl.col("start_ms") == window.start) & (pl.col("end_ms") == window.end)
    )
    return rows.height > 0 and rows.item(-1, "status") == STATUS_OK


@dataclass(frozen=True, slots=True)
class AssetFacts:
    """O que se sabe de um perpétuo do primeiro dex nas candidatas."""

    coin: str
    notional: float
    n_fills: int
    has_proxy: bool  # condição (i): proxy gravado em todos os dias UTC da janela
    proxy: ProxyCheck | None  # só para quem cumpre (i)


@dataclass(frozen=True, slots=True)
class Candidates:
    """Os ativos das candidatas, por notional decrescente e, no empate, pelo nome."""

    wallets: int  # carteiras do pool com cobertura ok
    assets: tuple[AssetFacts, ...]
    total_notional: float  # todos os fills, em qualquer instrumento
    perp_notional: float  # só perpétuos do primeiro dex


@dataclass(frozen=True, slots=True)
class AssetDecision:
    asset: AssetFacts
    excluded_by: Condition | None  # a primeira condição que falhou; None: entrou


@dataclass(frozen=True, slots=True)
class Universe:
    """O universo e, para cada ativo considerado, a condição que o excluiu (CA-08.3)."""

    decisions: tuple[AssetDecision, ...]
    total_notional: float
    perp_notional: float

    @property
    def coins(self) -> frozenset[str]:
        return frozenset(d.asset.coin for d in self.decisions if d.excluded_by is None)

    @property
    def notional(self) -> float:
        return sum(d.asset.notional for d in self.decisions if d.excluded_by is None)

    @property
    def coverage_of_all(self) -> float | None:
        """Fração do notional de todos os fills das candidatas que o universo cobre."""
        return None if self.total_notional <= 0 else self.notional / self.total_notional

    @property
    def coverage_of_perps(self) -> float | None:
        """Idem, sobre o dos perpétuos do primeiro dex."""
        return None if self.perp_notional <= 0 else self.notional / self.perp_notional


def _window_days(window: Window) -> range:
    return range(utc_day(window.start), utc_day(Ms(window.end - 1)) + 1)


def _has_every_day(proxy: pl.DataFrame, window: Window) -> bool:
    present = set(
        proxy.select((pl.col("second") * MS_PER_SECOND // MS_PER_DAY).unique()).to_series()
    )
    return set(_window_days(window)) <= present


def candidate_assets(
    repo: BoundedRepository, pool: Sequence[str], window: Window, params: Params
) -> Candidates:
    """Os ativos das carteiras do pool com cobertura ``ok`` (RF-SEL-08 CA-08.1).

    Carteira "frequência incompatível", "falha" ou sem cobertura da janela não entra na soma:
    o histórico dela é parcial.

    Raises:
        LookaheadError: a janela passa do corte do repositório.
        DataError: tabela de fills sem as colunas de que a conta precisa.
    """
    per_coin: list[pl.DataFrame] = []
    perp_fills: list[pl.DataFrame] = []
    total = 0.0
    perp_total = 0.0
    wallets = 0
    for address in pool:
        if not has_ok_coverage(repo, address, window):
            continue
        wallets += 1
        fills = repo.fills(address, window.start, window.end)
        missing = set(_FILL_COLUMNS) - set(fills.columns)
        if missing:
            raise DataError(f"Fills de {address} sem as colunas {sorted(missing)}.")
        fills = fills.select(_FILL_COLUMNS)
        notional = fills.select(fill_notional().alias("notional"))
        total += float(notional.get_column("notional").sum())
        perps = fills.filter(pl.col("kind") == PERP)
        perp_total += float(perps.select(fill_notional()).to_series().sum())
        per_coin.append(
            perps.group_by("coin").agg(fill_notional().sum().alias("notional"), pl.len().alias("n"))
        )
        perp_fills.append(perps.select("coin", "time_ms", "px"))

    if not per_coin:
        return Candidates(wallets, (), 0.0, 0.0)
    totals = (
        pl.concat(per_coin)
        .group_by("coin")
        .agg(pl.col("notional").sum(), pl.col("n").sum())
        .sort(["notional", "coin"], descending=[True, False])
    )
    all_fills = pl.concat(perp_fills)
    universe = params.universe
    assets: list[AssetFacts] = []
    for coin, notional_sum, n_fills in totals.iter_rows():
        proxy = repo.proxy(coin, window.start, window.end)
        has_proxy = proxy.height > 0 and _has_every_day(proxy, window)
        check = None
        if has_proxy:
            check = check_proxy(
                coin,
                all_fills.filter(pl.col("coin") == coin),
                proxy,
                deviation_percentile_pct=universe.proxy_deviation_percentile_pct,
                max_deviation_p95_bps=universe.proxy_max_deviation_p95_bps,
                max_level_bps=universe.proxy_max_level_bps,
            )
        assets.append(AssetFacts(coin, float(notional_sum), int(n_fills), has_proxy, check))
    return Candidates(wallets, tuple(assets), total, perp_total)


def form_universe(
    candidates: Candidates, costs: Mapping[str, CostEntry], params: Params
) -> Universe:
    """Aplica as cinco condições de RF-SEL-08 CA-08.1, na ordem (i) a (v).

    (ii) toma os ``max_assets`` de maior notional entre os que cumprem (i). (iii) pede
    ``min_candidate_fills`` fills. (iv) é a conferência do proxy. (v) é ter meio-spread medido,
    isto é, entrada em ``costs``. Cada ativo guarda a primeira condição que o excluiu.
    """
    ordered = sorted(candidates.assets, key=lambda a: (-a.notional, a.coin))
    meeting_i = [a.coin for a in ordered if a.has_proxy]
    top = set(meeting_i[: params.universe.max_assets])
    decisions: list[AssetDecision] = []
    for asset in ordered:
        failed: Condition | None
        if not asset.has_proxy:
            failed = "i"
        elif asset.coin not in top:
            failed = "ii"
        elif asset.n_fills < params.universe.min_candidate_fills:
            failed = "iii"
        elif asset.proxy is None or not asset.proxy.valid:
            failed = "iv"
        elif asset.coin not in costs:
            failed = "v"
        else:
            failed = None
        decisions.append(AssetDecision(asset, failed))
    return Universe(tuple(decisions), candidates.total_notional, candidates.perp_notional)
