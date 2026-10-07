"""Aritmética de intervalos semiabertos usada pelo armazenamento."""

import pytest

from copylab.exceptions import DataError
from copylab.storage import Span, intersect, normalize
from copylab.timeutil import Ms


def s(start: int, end: int) -> Span:
    return Span(Ms(start), Ms(end))


@pytest.mark.unit
def test_span_is_half_open_and_refuses_inverted_bounds() -> None:
    assert s(10, 20).contains(10)
    assert not s(10, 20).contains(20)
    assert s(5, 5).empty
    with pytest.raises(DataError, match="invertido"):
        s(20, 10)


@pytest.mark.unit
def test_normalize_sorts_merges_touching_and_drops_empty() -> None:
    # [30, 40) e [0, 10) ficam separados; [10, 15) toca [0, 10) e funde; [12, 12) some.
    assert normalize([s(30, 40), s(10, 15), s(0, 10), s(12, 12)]) == (s(0, 15), s(30, 40))
    assert normalize([]) == ()


@pytest.mark.unit
def test_intersect_keeps_only_common_instants() -> None:
    # [0, 100) com [10, 20) e [90, 120): sobram [10, 20) e [90, 100); [100, 100) é vazio.
    assert intersect([s(0, 100)], [s(10, 20), s(90, 120)]) == (s(10, 20), s(90, 100))
    assert intersect([s(0, 10)], [s(10, 20)]) == ()
    assert intersect([], [s(0, 1)]) == ()
