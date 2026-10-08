"""Ordenação dos ativos candidatos por notional (primeira metade de T-061), com fixture de
papel.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
``copylab.selection.assets``:

- Sem o filtro de perpétuos: falhou ``test_candidate_assets_are_perps_by_notional``
  (o HIP-3 de maior notional entrou em primeiro).
- Ordem crescente: falhou o mesmo.
- Sem ``fill_null``: falhou ``test_fill_without_price_counts_zero_notional``.
"""

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.selection.assets import CandidateAsset, fill_notional, order_candidate_assets

SCHEMA = {"coin": pl.String, "kind": pl.String, "px": pl.Float64, "sz": pl.Float64}


def fills(*rows: tuple[str, str, float | None, float | None]) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=SCHEMA, orient="row")


@pytest.mark.unit
def test_candidate_assets_are_perps_by_notional() -> None:
    # ETH: 2 x 1.000 + 1 x 3.000 = 5.000 em 2 fills. BTC: 0,5 x 10.000 = 5.000 em 1 fill
    # (empata com ETH; o nome desempata: BTC antes). SOL: 10 x 150 = 1.500.
    # xyz:TSLA (HIP-3, 1 x 9.000) e @107 (spot) não entram.
    table = fills(
        ("ETH", "perp", 1_000.0, 2.0),
        ("BTC", "perp", 10_000.0, 0.5),
        ("xyz:TSLA", "hip3", 9_000.0, 1.0),
        ("SOL", "perp", 150.0, 10.0),
        ("ETH", "perp", 3_000.0, 1.0),
        ("@107", "spot", 50.0, 1_000.0),
    )
    assert order_candidate_assets(table) == [
        CandidateAsset("BTC", 5_000.0, 1),
        CandidateAsset("ETH", 5_000.0, 2),
        CandidateAsset("SOL", 1_500.0, 1),
    ]


@pytest.mark.unit
def test_fill_without_price_counts_zero_notional() -> None:
    # O segundo fill de BTC não tem preço: conta zero, e o ativo continua com 2 fills.
    table = fills(("BTC", "perp", 100.0, 1.0), ("BTC", "perp", None, 1.0))
    assert table.select(fill_notional()).to_series().to_list() == [100.0, 0.0]
    assert order_candidate_assets(table) == [CandidateAsset("BTC", 100.0, 2)]
    only_null = fills(("ETH", "perp", None, 2.0))
    assert order_candidate_assets(only_null) == [CandidateAsset("ETH", 0.0, 1)]


@pytest.mark.unit
def test_candidate_assets_need_the_fill_columns() -> None:
    with pytest.raises(DataError, match="colunas"):
        order_candidate_assets(pl.DataFrame({"coin": ["BTC"]}))
