"""Conferência de PnL por custo médio (design §3.5; RF-ING-04 CA-04.2).

Reconstrói o PnL realizado de um episódio dos preços e tamanhos dos fills dele, por custo
médio, e o compara com a soma dos ``closed_pnl``, que a corretora informa bruto de taxa
(RF-VER-01 CA-01.4). A diferença sai em bps do notional negociado no episódio.

Só episódios abertos a partir de zero, fechados e íntegros são conferidos: um que já estava
aberto no início da janela não tem custo de entrada conhecido, e um ``broken`` tem fill
faltando. Para esses a divergência é ``None``, e não zero.
"""

from collections.abc import Sequence

import polars as pl

from copylab.exceptions import DataError
from copylab.leader.ledger import Fill, usable_fills
from copylab.leader.model import Episode

__all__ = ["pnl_divergence_bps", "pnl_violations"]

#: Folga relativa de ponto flutuante, a da regra do zero em HIP-3 (ledger).
_REL = 1e-9
_BPS = 10_000.0


class _Index:
    """Os fills usáveis de cada ativo, em ordem, e onde cada ``seq`` está."""

    def __init__(self, fills: pl.DataFrame) -> None:
        self._by_coin: dict[str, list[Fill]] = {}
        self._position: dict[tuple[str, int], int] = {}
        for fill in usable_fills(fills):
            rows = self._by_coin.setdefault(fill.coin, [])
            self._position[(fill.coin, fill.seq)] = len(rows)
            rows.append(fill)

    def of(self, episode: Episode) -> list[Fill]:
        """Os fills do episódio, do primeiro ao último ``seq``, ambos incluídos."""
        try:
            first = self._position[(episode.coin, episode.first_seq)]
            last = self._position[(episode.coin, episode.last_seq)]
        except KeyError as exc:
            raise DataError(
                f"O episódio de {episode.coin} (seq {episode.first_seq} a {episode.last_seq}) "
                "não corresponde aos fills dados."
            ) from exc
        rows = self._by_coin[episode.coin][first : last + 1]
        if len(rows) != episode.n_fills:
            raise DataError(
                f"O episódio de {episode.coin} tem {episode.n_fills} fills, e os fills dados "
                f"trazem {len(rows)} entre o seq {episode.first_seq} e o {episode.last_seq}."
            )
        return rows


def _divergence(index: _Index, episode: Episode) -> float | None:
    if not episode.opened_from_flat or episode.closed is None or episode.broken:
        return None
    rows = index.of(episode)
    if any(fill.closed_pnl is None for fill in rows) or episode.traded_notional <= 0.0:
        return None
    side = episode.side
    magnitude = average = realized = reported = 0.0
    for position, fill in enumerate(rows):
        # Módulo da posição, no sentido do episódio, antes e depois do fill. Negativo é o
        # lado oposto: o fill que cruza o zero começa o episódio novo com o resto.
        before = side * fill.start
        after = side * (fill.start + fill.signed)
        change = max(after, 0.0) - max(before, 0.0)
        if change > 0.0:
            average = (magnitude * average + change * fill.px) / (magnitude + change)
            magnitude += change
        else:
            realized += -change * (fill.px - average) * side
            magnitude += change
        # O closed_pnl de um fill que cruza o zero é do episódio que fecha, e não deste.
        inherited = position == 0 and before < 0.0 and -before > _REL * fill.sz
        if not inherited:
            reported += fill.closed_pnl or 0.0
    return abs(realized - reported) / episode.traded_notional * _BPS


def pnl_divergence_bps(fills: pl.DataFrame, episode: Episode) -> float | None:
    """Diferença entre o PnL reconstruído e a soma dos ``closed_pnl`` do episódio, em bps do
    notional negociado nele. ``None`` se o episódio não é conferível.

    Raises:
        DataError: o episódio não corresponde aos fills dados.
    """
    return _divergence(_Index(fills), episode)


def pnl_violations(
    fills: pl.DataFrame, episodes: Sequence[Episode], tolerance_bps: float
) -> list[tuple[Episode, float]]:
    """Os episódios conferíveis cuja divergência passa de ``tolerance_bps``, com a
    divergência. Estritamente acima: a tolerância é um máximo (RF-ING-04 CA-04.2).

    A tolerância vem do arquivo de parâmetros, e quem chama a lê.
    """
    index = _Index(fills)
    found = []
    for episode in episodes:
        divergence = _divergence(index, episode)
        if divergence is not None and divergence > tolerance_bps:
            found.append((episode, divergence))
    return found
