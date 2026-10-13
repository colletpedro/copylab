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
    "copied_episodes",
    "daily_returns",
    "hit_rate",
    "max_drawdown",
    "sharpe",
    "subaccount_metrics",
    "turnover",
]
