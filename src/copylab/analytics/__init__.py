"""Métricas, carteira, benchmark, grade e decomposição do custo de copiar (RF-ANA, Bloco E).

Lógica pura (design §2.1): não importa ``storage``, rede, arquivo nem relógio. Recebe o que o
simulador devolveu, como objetos, e devolve objetos. Veredito, janela efetiva, gate, relatórios e
gráfico são do Bloco G e ainda não existem.
"""

from copylab.analytics.metrics import (
    MAJORS,
    AssetBreakdown,
    AssetResult,
    CopiedEpisode,
    Drawdown,
    GroupResult,
    Metrics,
    asset_breakdown,
    asset_results,
    copied_episodes,
    daily_returns,
    hit_rate,
    max_drawdown,
    sharpe,
    subaccount_metrics,
    turnover,
)
from copylab.analytics.portfolio import (
    BENCHMARK_COIN,
    PortfolioResult,
    benchmark_buy_and_hold,
    portfolio,
    run_cohort,
)

__all__ = [
    "BENCHMARK_COIN",
    "MAJORS",
    "AssetBreakdown",
    "AssetResult",
    "CopiedEpisode",
    "Drawdown",
    "GroupResult",
    "Metrics",
    "PortfolioResult",
    "asset_breakdown",
    "asset_results",
    "benchmark_buy_and_hold",
    "copied_episodes",
    "daily_returns",
    "hit_rate",
    "max_drawdown",
    "portfolio",
    "run_cohort",
    "sharpe",
    "subaccount_metrics",
    "turnover",
]
