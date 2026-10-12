"""A janela semiaberta compartilhada por seleção e simulador."""

import pytest

from copylab.exceptions import ConfigError
from copylab.timeutil import Ms
from copylab.windows import Window


@pytest.mark.unit
def test_window_is_half_open_and_refuses_empty_or_inverted() -> None:
    window = Window(Ms(1_000), Ms(2_000))
    assert window.contains(Ms(1_000))
    assert window.contains(Ms(1_999))
    assert not window.contains(Ms(2_000))  # o fim não pertence à janela
    assert not window.contains(Ms(999))
    for start, end in ((2_000, 2_000), (3_000, 2_000)):
        with pytest.raises(ConfigError, match="vazia ou invertida"):
            Window(Ms(start), Ms(end))
