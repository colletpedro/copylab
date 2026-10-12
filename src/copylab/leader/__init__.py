"""Livro-razão do líder: posições, eventos, episódios e conferência de PnL (RF-ING-03, RF-ING-04).

Lógica pura (design §2.1): lê os fills como tabela, não importa ``storage``, rede, arquivo nem
relógio. As regras estão em ``ledger.py`` e no design §3.5.
"""

from copylab.leader.ledger import build_events, continuity_breaks, ignored_fills
from copylab.leader.model import (
    HIP3,
    PERP,
    AgeBucket,
    Break,
    BreakReport,
    Episode,
    Kind,
    LeaderEvent,
)

__all__ = [
    "HIP3",
    "PERP",
    "AgeBucket",
    "Break",
    "BreakReport",
    "Episode",
    "Kind",
    "LeaderEvent",
    "build_events",
    "continuity_breaks",
    "ignored_fills",
]
