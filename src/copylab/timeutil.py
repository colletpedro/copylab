"""Único módulo que converte instante em calendário (RNF-07, design §3.1).

Todo timestamp cruza o sistema como ``Ms``: inteiro de milissegundos UTC desde a
época. A conversão para dia, hora, segundo ou texto acontece aqui e em nenhum outro
lugar, e é este o único módulo que importa ``datetime``
(``test_architecture_time_boundary``). Nenhuma função lê o relógio da máquina: isso é
de :mod:`copylab.clock`.

Janelas são semiabertas, ``[início, fim)``, em todo o sistema.
"""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Final, NewType

from copylab.exceptions import ConfigError

__all__ = [
    "MS_PER_DAY",
    "MS_PER_HOUR",
    "MS_PER_SECOND",
    "Ms",
    "day_start",
    "from_date",
    "hour_floor",
    "iso",
    "parse_utc_date",
    "second_of",
    "utc_day",
]

Ms = NewType("Ms", int)
"""Milissegundos UTC desde 1970-01-01T00:00:00Z."""

MS_PER_SECOND: Final = 1_000
MS_PER_HOUR: Final = 3_600 * MS_PER_SECOND
MS_PER_DAY: Final = 24 * MS_PER_HOUR

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_EPOCH_DATE: Final = _EPOCH.date()

#: Só ``AAAA-MM-DD``. ``date.fromisoformat`` aceita também ``20260901`` e
#: ``2026-W36-2``, e uma data pré-registrada não pode ter duas grafias.
_DATE_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}")


def utc_day(t: Ms) -> int:
    """Dias UTC inteiros desde a época, do dia que contém ``t``."""
    return t // MS_PER_DAY


def day_start(day: int) -> Ms:
    """Meia-noite UTC do dia ``day``, contado como em :func:`utc_day`."""
    return Ms(day * MS_PER_DAY)


def hour_floor(t: Ms) -> Ms:
    """Início da hora UTC que contém ``t``."""
    return Ms(t // MS_PER_HOUR * MS_PER_HOUR)


def second_of(t: Ms) -> int:
    """Segundos inteiros desde a época, do segundo que contém ``t``."""
    return t // MS_PER_SECOND


def iso(t: Ms) -> str:
    """Texto ISO 8601 em UTC, com milissegundos. Só para log e relatório."""
    moment = _EPOCH + timedelta(milliseconds=t)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{t % MS_PER_SECOND:03d}Z"


def parse_utc_date(text: str) -> Ms:
    """``"2026-09-01"`` vira a meia-noite UTC desse dia.

    Raises:
        ConfigError: se o texto não for exatamente ``AAAA-MM-DD`` ou não for uma data.
    """
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ConfigError(f"Data inválida: {text!r}. Use AAAA-MM-DD (UTC).")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ConfigError(f"Data inválida: {text!r}. {exc}.") from exc
    return from_date(parsed)


def from_date(d: date) -> Ms:
    """Meia-noite UTC da data ``d``, como o ``tomllib`` entrega datas.

    Raises:
        ConfigError: se ``d`` for um ``datetime``. Um instante com hora ou fuso no
            lugar de uma data seria convertido em silêncio para outra coisa.
    """
    if isinstance(d, datetime):
        raise ConfigError(f"Esperava uma data sem hora, recebi o instante {d!r}.")
    return day_start((d - _EPOCH_DATE).days)
