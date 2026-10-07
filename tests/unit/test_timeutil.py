"""Testes de `copylab.timeutil` (RNF-07, design §3.1).

Os valores esperados são contados à mão a partir da época, 1970-01-01:

- 2026-09-01 (corte da Rota A). De 1970 a 2025 são 56 anos, com 14 bissextos
  (1972, 1976, ..., 2024): 56 * 365 + 14 = 20.454 dias. Em 2026, janeiro a agosto
  somam 31 + 28 + 31 + 30 + 31 + 30 + 31 + 31 = 243. Dia 20.697.
  Em ms: 20.697 * 86.400.000 = 1.788.220.800.000.
- 2024-02-29. De 1970 a 2023 são 54 anos, com 13 bissextos (1972 a 2020):
  54 * 365 + 13 = 19.723. Mais 31 de janeiro e 28 de fevereiro: dia 19.782.
"""

from datetime import UTC, date, datetime

import pytest

from copylab.exceptions import ConfigError
from copylab.timeutil import (
    MS_PER_DAY,
    MS_PER_HOUR,
    Ms,
    day_start,
    from_date,
    hour_floor,
    iso,
    parse_utc_date,
    second_of,
    utc_day,
)

#: 2026-09-01T00:00:00Z, dia 20.697 (docstring do módulo).
CUTOFF_A = Ms(1_788_220_800_000)


@pytest.mark.unit
def test_constants_are_the_calendar_units() -> None:
    assert MS_PER_HOUR == 3_600_000
    assert MS_PER_DAY == 86_400_000


@pytest.mark.unit
def test_parse_utc_date_is_midnight_utc_of_that_day() -> None:
    assert parse_utc_date("2026-09-01") == CUTOFF_A
    assert parse_utc_date("1970-01-01") == 0
    # 19.782 * 86.400.000 = 1.709.164.800.000
    assert parse_utc_date("2024-02-29") == 1_709_164_800_000


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "2026-02-30",
        "2026-13-01",
        "20260901",
        "2026-9-1",
        " 2026-09-01",
        "2026-09-01Z",
        "2026-W36-2",
    ],
)
def test_parse_utc_date_rejects_anything_but_a_valid_yyyy_mm_dd(text: str) -> None:
    with pytest.raises(ConfigError, match="Data inválida"):
        parse_utc_date(text)


@pytest.mark.unit
def test_from_date_takes_the_date_that_toml_delivers() -> None:
    assert from_date(date(2026, 9, 1)) == CUTOFF_A
    assert from_date(date(1969, 12, 31)) == -MS_PER_DAY


@pytest.mark.unit
@pytest.mark.parametrize("value", [datetime(2026, 9, 1, 12, 0, tzinfo=UTC), "2026-09-01", 20_697])
def test_from_date_refuses_anything_but_a_date(value: object) -> None:
    """`datetime` é subclasse de `date`; aceitá-lo descartaria a hora em silêncio. Texto e
    número no lugar de uma data do TOML também são erro de configuração."""
    with pytest.raises(ConfigError, match="sem hora"):
        from_date(value)  # type: ignore[arg-type]  # o teste é justamente o tipo errado


@pytest.mark.unit
def test_utc_day_and_day_start_split_at_midnight() -> None:
    # A meia-noite pertence ao dia que começa nela; 1 ms antes, ao dia anterior.
    assert utc_day(CUTOFF_A) == 20_697
    assert utc_day(Ms(CUTOFF_A - 1)) == 20_696
    assert utc_day(Ms(CUTOFF_A + MS_PER_DAY - 1)) == 20_697
    assert day_start(20_697) == CUTOFF_A
    # Antes da época a divisão é para baixo, não para zero.
    assert utc_day(Ms(-1)) == -1
    assert day_start(-1) == -MS_PER_DAY


@pytest.mark.unit
def test_hour_floor_is_the_start_of_the_containing_hour() -> None:
    # 00:59:59.999 ainda é a hora 00; 01:00:00.000 já é a hora 01.
    assert hour_floor(Ms(CUTOFF_A + MS_PER_HOUR - 1)) == CUTOFF_A
    assert hour_floor(Ms(CUTOFF_A + MS_PER_HOUR)) == CUTOFF_A + MS_PER_HOUR
    # O funding chega de 0 a 127 ms depois da hora (RF-VER-05 CA-05.3) e cai nela.
    assert hour_floor(Ms(CUTOFF_A + 127)) == CUTOFF_A
    assert hour_floor(Ms(-1)) == -MS_PER_HOUR


@pytest.mark.unit
def test_second_of_is_the_containing_second() -> None:
    # 1.788.220.800.999 ms está no segundo 1.788.220.800.
    assert second_of(Ms(CUTOFF_A + 999)) == 1_788_220_800
    assert second_of(Ms(CUTOFF_A + 1_000)) == 1_788_220_801
    assert second_of(Ms(-1)) == -1


@pytest.mark.unit
def test_iso_is_utc_with_milliseconds() -> None:
    assert iso(Ms(CUTOFF_A + 123)) == "2026-09-01T00:00:00.123Z"
    assert iso(Ms(0)) == "1970-01-01T00:00:00.000Z"
    assert iso(Ms(-1)) == "1969-12-31T23:59:59.999Z"
