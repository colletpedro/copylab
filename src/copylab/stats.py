"""Mediana e percentis sem interpolação, simples e ponderados (design 1.7, §3.6).

Tudo em inteiros onde a regra é uma fração: o percentil ``p`` é um inteiro, em por cento, e as
comparações com o peso total são feitas multiplicando, e não dividindo, para que a fronteira
(95% exatos de 100 ms, por exemplo) caia do lado certo sem depender do arredondamento de
``0,95 * 100`` em ponto flutuante. Nenhuma função interpola: o resultado é sempre um dos
valores dados, salvo a mediana de uma quantidade par de valores sem peso, que é a média dos
dois centrais.
"""

from collections.abc import Iterable, Sequence

from copylab.exceptions import DataError

__all__ = ["median", "nearest_rank_pct", "weighted_percentile"]


def _check_pct(pct: int) -> None:
    if not 0 < pct <= 100:
        raise DataError(f"Percentil {pct} fora de (0, 100].")


def nearest_rank_pct(sorted_values: Sequence[float], pct: int) -> float:
    """O valor de posto ⌈pct·n/100⌉ (a partir de 1) entre ``n`` valores já em ordem.

    É o menor valor com ao menos ``pct``% dos valores nele ou abaixo dele.

    Raises:
        DataError: sem valores, ou ``pct`` fora de (0, 100].
    """
    _check_pct(pct)
    if not sorted_values:
        raise DataError("Percentil de uma lista vazia.")
    rank = max(1, -(-pct * len(sorted_values) // 100))
    return sorted_values[rank - 1]


def median(values: Sequence[float]) -> float:
    """Mediana usual: o valor central, ou a média dos dois centrais se ``n`` é par.

    Raises:
        DataError: sem valores.
    """
    if not values:
        raise DataError("Mediana de uma lista vazia.")
    ordered = sorted(values)
    middle, odd = divmod(len(ordered), 2)
    return ordered[middle] if odd else (ordered[middle - 1] + ordered[middle]) / 2


def weighted_percentile(pairs: Iterable[tuple[float, int]], pct: int) -> float | None:
    """O menor valor ``v`` tal que ``100 * (peso dos valores até v) >= pct * (peso total)``.

    Os pesos são inteiros (milissegundos). Peso zero não conta, e ``pct = 50`` é a mediana
    ponderada inferior. Devolve ``None`` se o peso total é zero.

    Raises:
        DataError: peso negativo, ou ``pct`` fora de (0, 100].
    """
    _check_pct(pct)
    ordered = sorted(pairs)
    if any(weight < 0 for _, weight in ordered):
        raise DataError("Peso negativo em percentil ponderado.")
    total = sum(weight for _, weight in ordered)
    if total == 0:
        return None
    seen = 0
    for value, weight in ordered:
        seen += weight
        if 100 * seen >= pct * total:
            return value
    raise AssertionError("inalcançável: o peso acumulado final é o total")  # pragma: no cover
