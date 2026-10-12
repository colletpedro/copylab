"""O cursor de tempo do laço (design §3.7).

O laço cria o :class:`Cursor` e é o único que o avança, e só para a frente. As entradas de
informação do simulador (fita do líder, preços, funding) recebem só um :class:`CursorView`,
que lê o instante e não tem como mudá-lo. É assim que RF-SIM-01 CA-01.3 vale por construção
e não por disciplina.
"""

from copylab.exceptions import SimulationError
from copylab.timeutil import Ms

__all__ = ["Cursor", "CursorView"]


class CursorView:
    """Leitura do instante do cursor e de se o laço terminou. Nenhum método avança nada."""

    def __init__(self, cursor: "Cursor") -> None:
        self._cursor = cursor

    @property
    def now(self) -> Ms:
        return self._cursor.now

    @property
    def closed(self) -> bool:
        """Verdadeiro depois de o laço terminar: só então o relatório pode olhar tudo."""
        return self._cursor.closed


class Cursor:
    def __init__(self, start: Ms) -> None:
        self._now = start
        self._closed = False

    @property
    def now(self) -> Ms:
        return self._now

    @property
    def closed(self) -> bool:
        return self._closed

    def advance(self, t: Ms) -> None:
        """Avança para ``t``.

        Raises:
            SimulationError: se ``t`` recua, ou se o laço já terminou.
        """
        if self._closed:
            raise SimulationError("O cursor já foi fechado.")
        if t < self._now:
            raise SimulationError(f"O cursor só avança: {self._now} -> {t}.")
        self._now = t

    def close(self) -> None:
        self._closed = True

    def view(self) -> CursorView:
        return CursorView(self)
