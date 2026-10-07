"""Testes de `copylab.clock`, a única leitura do relógio da máquina (design §3.1)."""

import time

import pytest

from copylab import clock


@pytest.mark.unit
def test_now_is_integer_milliseconds_of_the_wall_clock() -> None:
    before = time.time_ns() // 1_000_000
    stamp = clock.now()
    after = time.time_ns() // 1_000_000
    assert isinstance(stamp, int)
    assert before <= stamp <= after


@pytest.mark.unit
def test_monotonic_never_goes_back() -> None:
    first = clock.monotonic()
    second = clock.monotonic()
    assert second >= first


@pytest.mark.unit
def test_sleep_delegates_to_the_system(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("copylab.clock.time.sleep", slept.append)
    clock.sleep(1.5)
    assert slept == [1.5]
