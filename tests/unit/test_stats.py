"""Mediana e percentis sem interpolação (design 1.7, §3.6), com fixtures de papel.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em `copylab.stats`:

- posto sem o teto (`max(1, pct * n // 100)`, que arredonda para baixo):
  `test_nearest_rank_is_ceiling_of_pct_n_over_100` caiu (p95 de 21 valores devolveu o 19º).
- `>=` trocado por `>` na comparação do peso:
  `test_weighted_percentile_is_inclusive_at_the_boundary` caiu (95 de 100 ms exatos passou para
  o valor seguinte).
- comparação em ponto flutuante (`seen >= pct * 0.01 * total`):
  `test_weighted_percentile_uses_integer_arithmetic` caiu (57 de 60 ms, 95%, passou para o
  valor seguinte, porque 0,95 · 60 sai 57,00000000000001 em `float`).
- mediana par sem a média dos dois centrais:
  `test_median_is_central_value_or_mean_of_the_two_central` caiu.
"""

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.stats import median, nearest_rank_pct, weighted_percentile
from copylab.timeutil import MS_PER_DAY, Ms, second_of, second_of_expr, utc_day, utc_day_expr


@pytest.mark.unit
def test_nearest_rank_is_ceiling_of_pct_n_over_100() -> None:
    # Valores 1..n. Posto = ceil(95 n / 100).
    #   n = 20: 95·20/100 = 19            -> posto 19 -> 19
    #   n = 21: 95·21/100 = 19,95 -> 20   -> posto 20 -> 20
    #   n = 1 : 0,95 -> 1                 -> posto 1  -> 1
    assert nearest_rank_pct(list(range(1, 21)), 95) == 19
    assert nearest_rank_pct(list(range(1, 22)), 95) == 20
    assert nearest_rank_pct([7.0], 95) == 7.0
    # p100 é o máximo.
    assert nearest_rank_pct([1.0, 2.0, 3.0], 100) == 3.0


@pytest.mark.unit
def test_nearest_rank_rejects_empty_and_bad_pct() -> None:
    with pytest.raises(DataError):
        nearest_rank_pct([], 95)
    for bad in (0, 101, -5):
        with pytest.raises(DataError):
            nearest_rank_pct([1.0], bad)


@pytest.mark.unit
def test_median_is_central_value_or_mean_of_the_two_central() -> None:
    # Ímpar: 3, 1, 2 -> ordenado 1, 2, 3 -> 2. Par: 4, 1, 3, 2 -> 1, 2, 3, 4 -> (2 + 3) / 2.
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 3.0, 2.0]) == pytest.approx(2.5)
    with pytest.raises(DataError):
        median([])


@pytest.mark.unit
def test_weighted_percentile_is_inclusive_at_the_boundary() -> None:
    # Pesos em ms: valor 1 pesa 95, valor 2 pesa 5; total 100.
    #   p95: o menor v com 100·peso(<= v) >= 95·100. Em v = 1: 100·95 = 9.500 >= 9.500. Vale 1.
    #   p96: em v = 1: 9.500 < 9.600; em v = 2: 10.000 >= 9.600. Vale 2.
    pairs = [(2.0, 5), (1.0, 95)]
    assert weighted_percentile(pairs, 95) == 1.0
    assert weighted_percentile(pairs, 96) == 2.0


@pytest.mark.unit
def test_weighted_percentile_uses_integer_arithmetic() -> None:
    # Valor 1 pesa 57 ms e valor 2 pesa 3 ms; total 60. p95: 95% de 60 ms são 57 ms exatos, então
    # 100·57 = 5.700 >= 95·60 = 5.700 e o valor é 1. Em ponto flutuante, 0,01 · 95 · 60 =
    # 57,00000000000001 > 57, e a fronteira cairia do lado errado.
    assert weighted_percentile([(1.0, 57), (2.0, 3)], 95) == 1.0
    # p50 de pesos 1 e 1: 100·1 = 100 >= 50·2 = 100, então o menor (a mediana inferior).
    assert weighted_percentile([(1.0, 1), (2.0, 1)], 50) == 1.0
    # Três valores de peso 1: p67 exige 100·seen >= 67·3 = 201, e só o terceiro (300) serve.
    assert weighted_percentile([(1.0, 1), (2.0, 1), (3.0, 1)], 67) == 3.0
    assert weighted_percentile([(1.0, 1), (2.0, 1), (3.0, 1)], 66) == 2.0


@pytest.mark.unit
def test_weighted_percentile_ignores_zero_weight_and_rejects_bad_input() -> None:
    assert weighted_percentile([(9.0, 0), (1.0, 4)], 95) == 1.0
    assert weighted_percentile([(9.0, 0)], 50) is None
    assert weighted_percentile([], 50) is None
    with pytest.raises(DataError):
        weighted_percentile([(1.0, -1)], 50)
    with pytest.raises(DataError):
        weighted_percentile([(1.0, 1)], 0)


@pytest.mark.unit
def test_column_expressions_agree_with_the_scalar_functions() -> None:
    # 2026-09-01T00:00:00Z é o dia 20.697 (test_timeutil). Um ms antes é o dia anterior.
    times = [Ms(20_697 * MS_PER_DAY), Ms(20_697 * MS_PER_DAY - 1), Ms(1_234_567), Ms(0)]
    frame = pl.DataFrame({"t": times}, schema={"t": pl.Int64})
    out = frame.select(utc_day_expr("t").alias("day"), second_of_expr("t").alias("second"))
    assert out.get_column("day").to_list() == [utc_day(t) for t in times]
    assert out.get_column("second").to_list() == [second_of(t) for t in times]
