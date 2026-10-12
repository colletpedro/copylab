"""Livro-razão do líder: posições, eventos e quebras de continuidade
(design §3.5; RF-ING-03 CA-03.1).

Os fills de uma carteira entram como a tabela ``fills``. Tudo sai de uma única passada,
fill a fill, ativo por ativo (:func:`walk`), de modo que posição, evento, episódio
(``episodes.py``) e quebra nunca discordem entre si.

**A posição declarada é a verdade.** A posição depois de um fill é o ``start_position``
dele mais o ``sz`` com o sinal do lado. Se o ``start_position`` não é o que se tinha (o
fim do fill anterior do mesmo ativo), além da tolerância, houve mudança não observada
(RF-SIM-02 CA-02.8): ela é incorporada naquele fill e contada, e nada é interpolado nem
remendado (ADR-0001).

**Tolerância e zero.** No primeiro dex, o lote vem do ``meta``: a continuidade tolera um
lote, e posição com módulo abaixo de meio lote é zero. Em HIP-3 o lote não é conhecido: a
continuidade tolera 10⁻⁹ vezes o maior entre a posição que se tinha e o tamanho do fill (o erro
de ponto flutuante cresce com a posição acumulada), e a posição é zero quando o módulo dela
é menor que 10⁻⁹ vezes o tamanho do fill.

Lógica pura: não importa ``storage``, rede, arquivo nem relógio, e não lê dado real.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

import polars as pl

from copylab.exceptions import DataError
from copylab.leader.model import HIP3, PERP, Break, Kind, LeaderEvent
from copylab.timeutil import Ms

__all__ = [
    "Fill",
    "Step",
    "build_events",
    "continuity_breaks",
    "ignored_fills",
    "sign",
    "usable_fills",
    "walk",
]

#: Folga relativa de ponto flutuante, a mesma da regra do zero em HIP-3 e a que a verificação
#: de dados usou para a continuidade do primeiro dex (``scripts/verify``).
_REL: Final = 1e-9

#: Colunas da tabela ``fills`` de que o livro-razão precisa.
_COLUMNS: Final = (
    "seq",
    "time_ms",
    "coin",
    "kind",
    "px",
    "sz",
    "side",
    "start_position",
    "crossed",
    "closed_pnl",
)
#: Sem estes campos o fill não tem posição nem notional interpretável.
_REQUIRED: Final = ("px", "sz", "side", "start_position")


@dataclass(frozen=True, slots=True)
class Fill:
    """Um fill de perpétuo com os campos de que a posição precisa."""

    seq: int
    t: Ms
    coin: str
    kind: Kind
    px: float
    sz: float
    signed: float  # sz com o sinal do lado: B positivo, A negativo
    start: float  # start_position declarado
    crossed: bool | None
    closed_pnl: float | None


@dataclass(frozen=True, slots=True)
class Step:
    """Um fill e a posição antes e depois dele, já com a regra do zero aplicada."""

    fill: Fill
    before: float  # declarada, 0,0 exato se for zero pela regra
    after: float  # declarada mais o fill, idem
    expected: float | None  # a que se tinha; None no primeiro fill do ativo
    broke: bool  # o declarado não é o que se tinha, além da tolerância

    @property
    def touched_zero(self) -> bool:
        """A posição partiu de zero, chegou a zero ou cruzou o zero neste fill."""
        return self.before == 0.0 or self.after == 0.0 or self.before * self.after < 0.0


def sign(value: float) -> int:
    """-1, 0 ou +1."""
    return (value > 0.0) - (value < 0.0)


def _check_columns(fills: pl.DataFrame) -> None:
    missing = [c for c in _COLUMNS if c not in fills.columns]
    if missing:
        raise DataError(f"A tabela de fills não tem as colunas {missing}.")


def _is_perp_kind(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(pl.col("kind").is_in([PERP, HIP3]))


def ignored_fills(fills: pl.DataFrame) -> int:
    """Quantos fills de perpétuo ficam de fora por não ter preço, tamanho, lado ou posição
    interpretável (design §3.5, "Abrangência"). Spot, tokens de resultado e outros não são
    perpétuos e não entram na conta."""
    _check_columns(fills)
    missing = pl.any_horizontal([pl.col(c).is_null() for c in _REQUIRED])
    bad_side = ~pl.col("side").is_in(["A", "B"]).fill_null(value=False)
    return _is_perp_kind(fills).filter(missing | bad_side).height


def usable_fills(fills: pl.DataFrame) -> list[Fill]:
    """Os fills de perpétuo com os quatro campos, em ordem de ``time_ms`` e ``seq``."""
    _check_columns(fills)
    frame = _is_perp_kind(fills.select(_COLUMNS)).sort("time_ms", "seq")
    out: list[Fill] = []
    for row in frame.iter_rows(named=True):
        side = row["side"]
        if any(row[c] is None for c in _REQUIRED) or side not in ("A", "B"):
            continue
        size = float(row["sz"])
        out.append(
            Fill(
                seq=int(row["seq"]),
                t=Ms(int(row["time_ms"])),
                coin=str(row["coin"]),
                kind=PERP if row["kind"] == PERP else HIP3,
                px=float(row["px"]),
                sz=size,
                signed=size if side == "B" else -size,
                start=float(row["start_position"]),
                crossed=row["crossed"],
                closed_pnl=None if row["closed_pnl"] is None else float(row["closed_pnl"]),
            )
        )
    return out


def _lot(coin: str, lots: Mapping[str, float]) -> float:
    lot = lots.get(coin)
    if lot is None or not lot > 0.0:
        raise DataError(f"Perpétuo {coin} sem tamanho de lote positivo em `lots`.")
    return lot


def _is_zero(position: float, fill: Fill, lot: float | None) -> bool:
    if lot is not None:
        return abs(position) < lot / 2
    return abs(position) < _REL * fill.sz


def walk(fills: pl.DataFrame, lots: Mapping[str, float]) -> dict[str, list[Step]]:
    """A passada fill a fill, por ativo, na ordem dos fills (``time_ms`` e ``seq``).

    Raises:
        DataError: tabela sem as colunas, ou perpétuo do primeiro dex sem lote.
    """
    steps: dict[str, list[Step]] = {}
    tracked: dict[str, float] = {}
    for fill in usable_fills(fills):
        lot = _lot(fill.coin, lots) if fill.kind == PERP else None
        before = 0.0 if _is_zero(fill.start, fill, lot) else fill.start
        after = fill.start + fill.signed
        after = 0.0 if _is_zero(after, fill, lot) else after
        expected = tracked.get(fill.coin)
        broke = False
        if expected is not None:
            gap = abs(fill.start - expected)
            limit = lot * (1 + _REL) if lot is not None else _REL * max(abs(expected), fill.sz)
            broke = gap > limit
        steps.setdefault(fill.coin, []).append(Step(fill, before, after, expected, broke))
        tracked[fill.coin] = after
    return steps


# ─── Quebras de continuidade ─────────────────────────────────────────────────


def continuity_breaks(fills: pl.DataFrame, lots: Mapping[str, float]) -> list[Break]:
    """Os pares de fills consecutivos de um ativo em que o declarado não encadeia a posição
    (RF-ING-03 CA-03.1), em ordem de instante e, no empate, de ativo.

    Quem decide o que a quebra faz com a carteira é a seleção: em HIP-3 ela só é contada.
    """
    breaks = []
    for coin_steps in walk(fills, lots).values():
        for previous, step in pairwise(coin_steps):
            if step.broke and step.expected is not None:
                fill = step.fill
                breaks.append(
                    Break(
                        t=fill.t,
                        prev_t=previous.fill.t,
                        coin=fill.coin,
                        kind=fill.kind,
                        expected=step.expected,
                        declared=fill.start,
                    )
                )
    return sorted(breaks, key=lambda b: (b.t, b.coin))


# ─── Eventos ─────────────────────────────────────────────────────────────────


def build_events(fills: pl.DataFrame, lots: Mapping[str, float]) -> list[LeaderEvent]:
    """Um evento por ativo e milissegundo, em ordem de instante e, no empate, de ativo.

    Os fills de um mesmo milissegundo viram um só, com a posição final: uma ordem dividida
    em 256 fills é uma decisão do seguidor (design §3.5).
    """
    events: list[LeaderEvent] = []
    for coin_steps in walk(fills, lots).values():
        group: list[Step] = []
        for step in coin_steps:
            if group and step.fill.t != group[0].fill.t:
                events.append(_event(group))
                group = []
            group.append(step)
        events.append(_event(group))  # um ativo em `walk` tem ao menos um fill
    return sorted(events, key=lambda e: (e.t, e.coin))


def _event(group: list[Step]) -> LeaderEvent:
    first, last = group[0], group[-1]
    return LeaderEvent(
        t=first.fill.t,
        coin=first.fill.coin,
        kind=first.fill.kind,
        prev_position=first.before,
        position=last.after,
        touched_zero=any(s.touched_zero for s in group),
        px=last.fill.px,
        notional=sum(s.fill.sz * s.fill.px for s in group),
        unobserved=any(s.broke for s in group),
        n_fills=len(group),
    )
