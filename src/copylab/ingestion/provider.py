"""Provedor da API de informação da Hyperliquid, somente leitura (design §3.3, ADR-0001).

Só ``POST /info`` e o ``GET`` do leaderboard. Nenhuma chave, nenhuma assinatura, nenhum
endpoint de ordem (RNF-09). O provedor fala ``httpx`` direto, sem SDK.

Cada requisição passa pelo :class:`~copylab.ingestion.budget.WeightBudget` antes de sair.
Limite excedido (HTTP 429), erro 5xx ou de transporte: espera e repete, com a espera
dobrando a cada tentativa até o máximo; esgotadas as tentativas, ``DataError``
(RF-ING-07 CA-07.3). Outro código HTTP, ou resposta fora do formato, é ``DataError`` na
hora: a API pode mudar, e o provedor valida o formato na borda e falha alto (design §7,
risco 7).

Os pesos são fatos do protocolo da corretora, com a fonte nos comentários; o limite por
minuto é de operação e vem de ``Settings``.
"""

import math
from collections.abc import Callable
from typing import Any, Final, Protocol

import httpx

from copylab.exceptions import DataError
from copylab.ingestion.budget import WeightBudget
from copylab.logging import get_logger
from copylab.timeutil import MS_PER_HOUR, Ms, iso

__all__ = [
    "FILLS_PAGE_MAX",
    "FUNDING_PAGE_MAX",
    "INFO_URL",
    "LEADERBOARD_URL",
    "HyperliquidInfo",
    "InfoProvider",
    "items_weight",
]

log = get_logger(__name__)

INFO_URL: Final = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL: Final = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
USER_AGENT: Final = "copylab-ingestion (read-only)"

#: Peso de uma requisição de informação (documentação da Hyperliquid, "Rate limits":
#: "info requests have weight 20" salvo as listadas lá).
INFO_WEIGHT: Final = 20
#: ``userRole`` pesa 60 (mesma página da documentação).
USER_ROLE_WEIGHT: Final = 60
#: ``userFillsByTime`` e ``fundingHistory`` somam 1 de peso a cada 20 itens devolvidos
#: (mesma página: "additional weight per 20 items returned").
ITEMS_PER_WEIGHT: Final = 20
#: Fills por resposta de ``userFillsByTime`` (documentação: "returns a maximum of 2000
#: fills"). Uma página cheia pesa 20 + 2000 / 20 = 120, a reserva de design §3.3.
FILLS_PAGE_MAX: Final = 2000
#: Registros por consulta de ``fundingHistory``. A documentação não dá o limite; a
#: ingestão pede no máximo 500 horas por consulta, e o registro é horário (RF-VER-05
#: CA-05.3), então nenhuma resposta passa disso e a reserva é exata.
FUNDING_PAGE_MAX: Final = 500
#: O leaderboard é um ``GET`` em outro servidor, sem peso documentado. Reserva-se o de uma
#: requisição de informação, por segurança.
LEADERBOARD_WEIGHT: Final = INFO_WEIGHT


def items_weight(n_items: int) -> int:
    """Peso de uma resposta com ``n_items`` itens, nas consultas que cobram por item."""
    return INFO_WEIGHT + math.ceil(n_items / ITEMS_PER_WEIGHT)


class InfoProvider(Protocol):
    """O que a ingestão pede à API. Janelas semiabertas ``[start, end)`` em ``Ms``."""

    def leaderboard(self) -> bytes: ...
    def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, Any]]: ...
    def user_role(self, address: str) -> str: ...
    def meta(self) -> dict[str, Any]: ...
    def funding_history(self, coin: str, start: Ms, end: Ms) -> list[dict[str, Any]]: ...


def _list_of_dicts(payload: object, what: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise DataError(f"{what} não devolveu lista de objetos: {str(payload)[:200]}")
    return payload


class HyperliquidInfo:
    """:class:`InfoProvider` sobre ``httpx``, com orçamento de peso e recuo."""

    def __init__(
        self,
        budget: WeightBudget,
        *,
        http: httpx.Client,
        sleep: Callable[[float], None],
        max_retries: int,
        backoff_initial_s: float,
        backoff_max_s: float,
    ) -> None:
        self._budget = budget
        self._http = http
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_initial_s = backoff_initial_s
        self._backoff_max_s = backoff_max_s
        self.requests = 0
        self.retries = 0
        self.rate_limited = 0

    @staticmethod
    def client(timeout_s: float) -> httpx.Client:
        """Cliente HTTP da ingestão: só leitura, com identificação."""
        return httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(15.0, timeout_s)),
            headers={"User-Agent": USER_AGENT},
        )

    def _send(
        self,
        what: str,
        request: Callable[[], httpx.Response],
        reserve: int,
        weight_of: Callable[[httpx.Response], int],
    ) -> httpx.Response:
        last_error = ""
        for attempt in range(self._max_retries + 1):
            if attempt:
                wait = min(self._backoff_max_s, self._backoff_initial_s * 2 ** (attempt - 1))
                self.retries += 1
                log.warning(
                    "ingestion.api.retry",
                    what=what,
                    attempt=attempt,
                    wait_s=wait,
                    reason=last_error,
                )
                self._sleep(wait)
            reservation = self._budget.acquire(reserve)
            self.requests += 1
            try:
                response = request()
            except httpx.TransportError as exc:
                last_error = f"transporte: {type(exc).__name__}"
                continue
            if response.status_code == 429:
                self.rate_limited += 1
                last_error = "limite excedido (HTTP 429)"
                continue
            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise DataError(f"{what}: HTTP {response.status_code}: {response.text[:200]}")
            self._budget.settle(reservation, weight_of(response))
            return response
        raise DataError(
            f"{what}: {self._max_retries + 1} tentativas esgotadas; a última falhou com "
            f"{last_error}. Rode o comando de novo mais tarde: a ingestão retoma de onde parou."
        )

    def _info(
        self, body: dict[str, Any], reserve: int, weight_of: Callable[[Any], int] | None = None
    ) -> Any:
        what = str(body["type"])
        parsed: list[Any] = []

        def weight(response: httpx.Response) -> int:
            try:
                parsed.append(response.json())
            except ValueError as exc:
                raise DataError(f"{what}: resposta não é JSON: {response.text[:200]}") from exc
            return reserve if weight_of is None else weight_of(parsed[0])

        self._send(what, lambda: self._http.post(INFO_URL, json=body), reserve, weight)
        return parsed[0]

    def leaderboard(self) -> bytes:
        """Corpo bruto do leaderboard, como veio."""
        response = self._send(
            "leaderboard",
            lambda: self._http.get(LEADERBOARD_URL),
            LEADERBOARD_WEIGHT,
            lambda _: LEADERBOARD_WEIGHT,
        )
        return response.content

    def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
        """Uma página de ``userFillsByTime``, não agregada (D18), de ``[start, end)``.

        O ``endTime`` da API é inclusivo: pede-se até ``end - 1``.
        """
        if end <= start:
            raise DataError(f"Janela vazia de fills: [{iso(start)}, {iso(end)}).")
        body = {
            "type": "userFillsByTime",
            "user": address,
            "startTime": start,
            "endTime": end - 1,
            "aggregateByTime": False,
        }
        payload = self._info(
            body,
            items_weight(FILLS_PAGE_MAX),
            lambda p: items_weight(len(p)) if isinstance(p, list) else INFO_WEIGHT,
        )
        page = _list_of_dicts(payload, f"userFillsByTime de {address}")
        if len(page) > FILLS_PAGE_MAX:
            raise DataError(
                f"userFillsByTime devolveu {len(page)} fills, mais que o máximo documentado "
                f"de {FILLS_PAGE_MAX}: a paginação deixaria de ser confiável."
            )
        return page

    def user_role(self, address: str) -> str:
        payload = self._info({"type": "userRole", "user": address}, USER_ROLE_WEIGHT)
        role = payload.get("role") if isinstance(payload, dict) else None
        if not isinstance(role, str) or not role:
            raise DataError(f"userRole de {address} sem campo role: {str(payload)[:200]}")
        return role

    def meta(self) -> dict[str, Any]:
        payload = self._info({"type": "meta"}, INFO_WEIGHT)
        if not isinstance(payload, dict) or not isinstance(payload.get("universe"), list):
            raise DataError(f"meta sem lista universe: {str(payload)[:200]}")
        return payload

    def funding_history(self, coin: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
        """Registros de funding de ``[start, end)``, que não pode passar de
        :data:`FUNDING_PAGE_MAX` horas."""
        if not 0 < end - start <= FUNDING_PAGE_MAX * MS_PER_HOUR:
            raise DataError(
                f"Consulta de funding de {coin} com {end - start} ms; o máximo é "
                f"{FUNDING_PAGE_MAX} horas."
            )
        body = {"type": "fundingHistory", "coin": coin, "startTime": start, "endTime": end - 1}
        payload = self._info(
            body,
            items_weight(FUNDING_PAGE_MAX),
            lambda p: items_weight(len(p)) if isinstance(p, list) else INFO_WEIGHT,
        )
        return _list_of_dicts(payload, f"fundingHistory de {coin}")
