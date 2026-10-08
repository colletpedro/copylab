"""Orçamento de peso e provedor da API (T-020; RF-ING-07 CA-07.1 e CA-07.3).

O relógio é falso: ``FakeClock.sleep`` adianta ``FakeClock.now``. As respostas HTTP vêm de
``httpx.MockTransport``, sem rede.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez:

- ``WeightBudget._used`` expirando reservas com 59 s (``WINDOW_S - 1``): falhou
  ``test_rate_budget_never_exceeds_limit``, com 1.022 de peso numa janela de 60 s.
- ``WeightBudget.acquire`` sem esperar (a condição do laço trocada por ``True``): falharam
  o mesmo, com 6.041, e ``test_rate_budget_waits_exactly_until_the_oldest_reservation_expires``.
- ``HyperliquidInfo._send`` tratando 429 como erro definitivo (``raise`` no lugar de
  ``continue``): falharam ``test_rate_limited_response_backs_off_then_fails_explicitly``
  e ``test_rate_limited_response_is_retried_until_it_succeeds``.
- O recuo sem dobrar (``2 ** 0``): falharam esses dois e ``test_backoff_is_capped``.

Uma falha encontrada no caminho, antes do commit: sem a folga de 0,05 s na espera, o
relógio falso parava um nada antes da expiração da reserva mais antiga, e o laço girava com
esperas de zero para sempre.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from copylab.exceptions import ConfigError, DataError
from copylab.ingestion.budget import WeightBudget
from copylab.ingestion.provider import INFO_URL, HyperliquidInfo, items_weight
from copylab.timeutil import Ms


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds


def provider(
    handler: Callable[[httpx.Request], httpx.Response],
    clock: FakeClock,
    *,
    limit: int = 1_000,
    retries: int = 3,
) -> tuple[HyperliquidInfo, WeightBudget]:
    budget = WeightBudget(limit, clock, clock.sleep)
    info = HyperliquidInfo(
        budget,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=clock.sleep,
        max_retries=retries,
        backoff_initial_s=2.0,
        backoff_max_s=60.0,
    )
    return info, budget


def fill(t: int) -> dict[str, Any]:
    return {"time": t, "coin": "BTC"}


# ─── Orçamento ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rate_budget_never_exceeds_limit() -> None:
    # 300 requisições com reservas de 120 (página cheia) acertadas para pesos entre 21 e
    # 120, com 0,7 s de trabalho entre elas. Para toda janela de 60 s que começa numa
    # reserva, a soma dos pesos finais das reservas dentro dela fica <= 1.000.
    clock = FakeClock()
    budget = WeightBudget(1_000, clock, clock.sleep)
    log: list[tuple[float, int]] = []
    for i in range(300):
        reservation = budget.acquire(120)
        actual = 21 + (i * 37) % 100
        budget.settle(reservation, actual)
        log.append((reservation.at, actual))
        clock.now += 0.7

    for start, _ in log:
        in_window = sum(w for t, w in log if start <= t < start + 60.0)
        assert in_window <= 1_000
    assert budget.peak <= 1_000
    assert budget.waited_s > 0  # o limite apertou de fato
    assert budget.total == sum(w for _, w in log)


@pytest.mark.unit
def test_rate_budget_waits_exactly_until_the_oldest_reservation_expires() -> None:
    # Limite 240: duas páginas de 120 em t = 1.000 e t = 1.010 enchem a janela. A terceira
    # só cabe quando a primeira sai, em 1.000 + 60 = 1.060, mais a folga de 0,05 s: espera
    # 50,05 s a partir de 1.010.
    clock = FakeClock()
    budget = WeightBudget(240, clock, clock.sleep)
    budget.acquire(120)
    clock.now = 1_010.0
    budget.acquire(120)
    third = budget.acquire(120)
    assert clock.sleeps == [pytest.approx(50.05)]
    assert third.at == pytest.approx(1_060.05)


@pytest.mark.unit
def test_rate_budget_refuses_weight_above_limit() -> None:
    clock = FakeClock()
    with pytest.raises(ConfigError, match="maior que o limite"):
        WeightBudget(100, clock, clock.sleep).acquire(120)


# ─── Provedor: limite excedido e recuo ───────────────────────────────────────


@pytest.mark.unit
def test_rate_limited_response_backs_off_then_fails_explicitly() -> None:
    # Sempre 429. Com 3 tentativas extras e recuo inicial de 2 s, as esperas são 2, 4 e 8 s;
    # na quarta resposta 429 a ingestão desiste com DataError, e não em silêncio.
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(429), clock, retries=3)
    with pytest.raises(DataError, match=r"tentativas esgotadas.*429"):
        info.user_role("0xabc")
    assert clock.sleeps == [2.0, 4.0, 8.0]
    assert info.requests == 4
    assert info.rate_limited == 4


@pytest.mark.unit
def test_rate_limited_response_is_retried_until_it_succeeds() -> None:
    answers = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json=[])])
    clock = FakeClock()
    info, _ = provider(lambda _: next(answers), clock, retries=3)
    assert info.user_fills("0xabc", Ms(0), Ms(10)) == []
    assert clock.sleeps == [2.0, 4.0]


@pytest.mark.unit
def test_backoff_is_capped() -> None:
    clock = FakeClock()
    budget = WeightBudget(1_000, clock, clock.sleep)
    info = HyperliquidInfo(
        budget,
        http=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
        sleep=clock.sleep,
        max_retries=6,
        backoff_initial_s=2.0,
        backoff_max_s=20.0,
    )
    with pytest.raises(DataError):
        info.meta()
    assert clock.sleeps == [2.0, 4.0, 8.0, 16.0, 20.0, 20.0]


@pytest.mark.unit
def test_transport_error_is_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("caiu", request=request)
        return httpx.Response(200, json={"role": "user"})

    clock = FakeClock()
    info, _ = provider(handler, clock)
    assert info.user_role("0xabc") == "user"
    assert calls["n"] == 2


@pytest.mark.unit
def test_client_error_fails_at_once_without_retry() -> None:
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(422, text="bad"), clock)
    with pytest.raises(DataError, match="HTTP 422"):
        info.meta()
    assert info.requests == 1
    assert clock.sleeps == []


# ─── Provedor: formato das consultas ─────────────────────────────────────────


@pytest.mark.unit
def test_fills_query_is_not_aggregated_with_inclusive_end_and_settles_real_weight() -> None:
    # 45 fills pesam 20 + ceil(45 / 20) = 23; a reserva de 120 é trocada por 23.
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == INFO_URL
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=[fill(5) for _ in range(45)])

    clock = FakeClock()
    info, budget = provider(handler, clock)
    page = info.user_fills("0xabc", Ms(1_000), Ms(2_000))
    assert len(page) == 45
    assert seen == [
        {
            "type": "userFillsByTime",
            "user": "0xabc",
            "startTime": 1_000,
            "endTime": 1_999,
            "aggregateByTime": False,
        }
    ]
    assert items_weight(45) == 23
    assert budget.total == 23


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload", [{"error": "x"}, [1, 2], "texto"], ids=["objeto", "lista-de-numeros", "texto"]
)
def test_fills_response_out_of_format_fails(payload: object) -> None:
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(200, json=payload), clock)
    with pytest.raises(DataError, match="não devolveu lista"):
        info.user_fills("0xabc", Ms(0), Ms(10))


@pytest.mark.unit
def test_non_json_response_fails() -> None:
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(200, text="<html>"), clock)
    with pytest.raises(DataError, match="não é JSON"):
        info.meta()


@pytest.mark.unit
def test_user_role_and_meta_are_validated() -> None:
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(200, json={"x": 1}), clock)
    with pytest.raises(DataError, match="sem campo role"):
        info.user_role("0xabc")
    with pytest.raises(DataError, match="universe"):
        info.meta()


@pytest.mark.unit
def test_funding_query_is_limited_to_500_hours() -> None:
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(200, json=[]), clock)
    assert info.funding_history("BTC", Ms(0), Ms(500 * 3_600_000)) == []
    with pytest.raises(DataError, match="500 horas"):
        info.funding_history("BTC", Ms(0), Ms(500 * 3_600_000 + 1))


@pytest.mark.unit
def test_leaderboard_returns_raw_body() -> None:
    clock = FakeClock()
    info, _ = provider(lambda _: httpx.Response(200, content=b'{"leaderboardRows":[]}'), clock)
    assert info.leaderboard() == b'{"leaderboardRows":[]}'
