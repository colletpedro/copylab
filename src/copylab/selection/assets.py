"""Ordenação dos ativos candidatos por notional das candidatas (primeira metade de T-061).

Função pura, adiantada para o Bloco B porque a ingestão precisa dela para saber de quais
ativos baixar o preço proxy (design §3.3, "Quais ativos recebem proxy"). O resto de T-061
(conferência do proxy e universo) fica para o Bloco F.

Entram só os perpétuos do primeiro dex (``kind == "perp"``), contados sobre os fills das
candidatas com cobertura ``ok``: quem passa esta tabela já filtrou as marcadas "frequência
incompatível", que têm histórico truncado (RF-SEL-08 CA-08.1). O notional de um fill é
``|sz| * px``; fill sem preço ou tamanho interpretável conta com notional zero
(RF-ING-02 CA-02.5).
"""

from dataclasses import dataclass

import polars as pl

from copylab.exceptions import DataError

__all__ = ["CandidateAsset", "fill_notional", "order_candidate_assets"]

_PERP = "perp"


@dataclass(frozen=True, slots=True)
class CandidateAsset:
    coin: str
    notional: float
    n_fills: int


def fill_notional() -> pl.Expr:
    """Notional de cada fill, com nulo valendo zero."""
    return (pl.col("sz").abs() * pl.col("px")).fill_null(0.0)


def order_candidate_assets(fills: pl.DataFrame) -> list[CandidateAsset]:
    """Perpétuos do primeiro dex em ordem decrescente de notional, com o nome como desempate.

    Raises:
        DataError: tabela sem as colunas ``coin``, ``kind``, ``px`` e ``sz``.
    """
    missing = {"coin", "kind", "px", "sz"} - set(fills.columns)
    if missing:
        raise DataError(f"Fills sem as colunas {sorted(missing)}.")
    totals = (
        fills.filter(pl.col("kind") == _PERP)
        .group_by("coin")
        .agg(fill_notional().sum().alias("notional"), pl.len().alias("n_fills"))
        .sort(["notional", "coin"], descending=[True, False])
    )
    return [CandidateAsset(c, float(n), int(k)) for c, n, k in totals.iter_rows()]
