"""Episódios de zero a zero (design §3.5; RF-ING-04 CA-04.1).

Construídos fill a fill, a partir da passada de :func:`copylab.leader.ledger.walk`, e não
evento a evento: um fill que cruza o zero fecha um episódio e abre outro no mesmo instante.
"""

from collections.abc import Mapping

import polars as pl

from copylab.leader.ledger import Fill, sign, walk
from copylab.leader.model import Episode
from copylab.timeutil import Ms

__all__ = ["build_episodes"]


class _Builder:
    """Um episódio em construção."""

    def __init__(self, fill: Fill, side: int, *, from_flat: bool, broken: bool) -> None:
        self.coin = fill.coin
        self.opened = fill.t
        self.first_seq = fill.seq
        self.last_seq = fill.seq
        self.side = side
        self.from_flat = from_flat
        self.broken = broken
        self.traded = 0.0
        self.opening = 0.0
        self.opening_taker = 0.0
        self.n_fills = 0

    def opening_part(self, fill: Fill, size: float) -> None:
        """Parte do fill que aumenta o módulo da posição."""
        notional = size * fill.px
        self.traded += notional
        self.opening += notional
        if fill.crossed:
            self.opening_taker += notional
        self._touch(fill)

    def closing_part(self, fill: Fill, size: float) -> None:
        """Parte do fill que reduz o módulo da posição."""
        self.traded += size * fill.px
        self._touch(fill)

    def _touch(self, fill: Fill) -> None:
        self.n_fills += 1
        self.last_seq = fill.seq

    def finish(self, closed: Ms | None, *, broken: bool = False) -> Episode:
        return Episode(
            coin=self.coin,
            opened=self.opened,
            closed=closed,
            side=self.side,
            opened_from_flat=self.from_flat,
            broken=self.broken or broken,
            traded_notional=self.traded,
            opening_notional=self.opening,
            opening_taker_notional=self.opening_taker,
            n_fills=self.n_fills,
            first_seq=self.first_seq,
            last_seq=self.last_seq,
        )


def build_episodes(fills: pl.DataFrame, lots: Mapping[str, float]) -> list[Episode]:
    """Episódios de zero a zero, construídos fill a fill (RF-ING-04 CA-04.1), em ordem de
    abertura.

    Um fill que cruza o zero fecha um episódio e abre outro no mesmo instante, com o
    tamanho dividido: a parte que fecha, igual ao módulo da posição antes, fica com o que
    fecha, e o resto, com o que abre. Os demais casos, em design §3.5.
    """
    episodes: list[Episode] = []
    for coin_steps in walk(fills, lots).values():
        current: _Builder | None = None
        for step in coin_steps:
            fill, before, after = step.fill, step.before, step.after
            if current is not None:
                if before == 0.0 or sign(before) != current.side:
                    # O declarado é zero ou do outro lado: o episódio acabou sem fill que o
                    # fechasse. Fecha onde se observa isso, sem interpolar o instante.
                    episodes.append(current.finish(fill.t, broken=True))
                    current = None
                elif step.broke:
                    current.broken = True
            if current is None and before != 0.0:
                # Posição já aberta: no início da janela, ou aberta sem que se visse.
                current = _Builder(fill, sign(before), from_flat=False, broken=step.broke)
            direction = sign(fill.signed)
            if before == 0.0 or sign(before) == direction:
                if current is None:
                    current = _Builder(fill, direction, from_flat=True, broken=False)
                current.opening_part(fill, fill.sz)
                continue
            assert current is not None  # before != 0: o episódio existe (acima)
            crossed = after != 0.0 and sign(after) != sign(before)
            closing = abs(before) if after == 0.0 or crossed else fill.sz
            current.closing_part(fill, closing)
            if after == 0.0 or crossed:
                episodes.append(current.finish(fill.t))
                current = None
            if crossed:
                current = _Builder(fill, sign(after), from_flat=True, broken=False)
                current.opening_part(fill, abs(after))
        if current is not None:
            episodes.append(current.finish(None))
    return sorted(episodes, key=lambda e: (e.opened, e.coin, e.first_seq))
