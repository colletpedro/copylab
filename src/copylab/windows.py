"""A janela semiaberta ``[start, end)``, em milissegundos UTC (design §2.1, §3.7).

Só o par de instantes: nenhuma conversão de calendário mora aqui (isso é de
:mod:`copylab.timeutil`). Seleção e simulador a compartilham.
"""

from dataclasses import dataclass

from copylab.exceptions import ConfigError
from copylab.timeutil import Ms

__all__ = ["Window"]


@dataclass(frozen=True, slots=True)
class Window:
    """Intervalo ``[start, end)``: o instante ``end`` não pertence à janela."""

    start: Ms
    end: Ms

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ConfigError(f"Janela vazia ou invertida: [{self.start}, {self.end}).")

    def contains(self, t: Ms) -> bool:
        return self.start <= t < self.end
