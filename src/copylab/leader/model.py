"""Tipos do livro-razão do líder (design §3.5).

Objetos imutáveis e sem lógica. O que eles significam, e as regras que os produzem,
está em ``ledger.py``.
"""

from dataclasses import dataclass
from typing import Final, Literal

from copylab.timeutil import Ms

__all__ = [
    "HIP3",
    "PERP",
    "AgeBucket",
    "Break",
    "BreakReport",
    "Episode",
    "Kind",
    "LeaderEvent",
]

Kind = Literal["perp", "hip3"]
"""Perpétuo do primeiro dex ou HIP-3. Os mesmos valores que a ingestão grava em ``kind``;
``copylab.leader`` não importa ``ingestion``, e um teste confere que os dois coincidem."""

PERP: Final[Kind] = "perp"
HIP3: Final[Kind] = "hip3"


@dataclass(frozen=True, slots=True)
class LeaderEvent:
    """Todos os fills de um líder num ativo e num milissegundo: uma decisão do seguidor."""

    t: Ms
    coin: str
    kind: Kind
    prev_position: float  # posição declarada antes do primeiro fill do evento
    position: float  # posição depois do último fill do evento, com sinal
    touched_zero: bool  # a posição partiu de zero, chegou a zero ou cruzou o zero
    px: float  # preço do último fill do evento
    notional: float  # soma de |sz| * px dos fills do evento
    unobserved: bool  # a posição anterior declarada não era a que se tinha
    n_fills: int


@dataclass(frozen=True, slots=True)
class Episode:
    """Intervalo em que a posição do líder num ativo sai de zero e volta a zero."""

    coin: str
    opened: Ms
    closed: Ms | None
    side: int  # +1 ou -1
    opened_from_flat: bool  # falso quando a posição já existia no início da janela
    broken: bool  # uma mudança não observada entrou no episódio ou o criou
    traded_notional: float
    opening_notional: float  # fills que aumentam o módulo da posição
    opening_taker_notional: float  # idem, só com crossed = true
    n_fills: int
    first_seq: int  # seq do primeiro e do último fill do episódio
    last_seq: int


@dataclass(frozen=True, slots=True)
class Break:
    """Um par de fills consecutivos de um ativo que não encadeia a posição."""

    t: Ms  # instante do fill que revela a quebra, o segundo do par
    prev_t: Ms  # instante do fill anterior do ativo
    coin: str
    kind: Kind
    expected: float  # posição que se tinha: a do fim do fill anterior
    declared: float  # start_position do fill que revela


@dataclass(frozen=True, slots=True)
class AgeBucket:
    """Quebras cuja idade, ``collected_at - t``, cai em ``[age_from_ms, age_to_ms)``."""

    age_from_ms: int
    age_to_ms: int | None  # None: sem limite superior
    breaks: int
    with_twap: int  # as que têm fill de TWAP do mesmo ativo na vizinhança


@dataclass(frozen=True, slots=True)
class BreakReport:
    total: int
    with_twap: int
    by_age: tuple[AgeBucket, ...]
