"""Provedor falso da API e arquivo falso da Binance, para a suíte default rodar offline
(RNF-06).

Imita o que a ingestão usa do comportamento da corretora, como a verificação de dados o
mediu (``docs/verificacao-de-dados.md``): ``userFillsByTime`` devolve no máximo
``page_size`` fills, em ordem crescente de instante, com ``startTime`` e ``endTime``
inclusivos; ``fundingHistory`` devolve os registros do intervalo, com os dois extremos
inclusivos. Cada chamada fica registrada em ``calls``, para os testes conferirem o que foi
pedido, e carteiras em ``failing`` levantam ``DataError``, como uma falha de rede esgotada.

``FakeArchive`` serve zips em memória por símbolo e dia; o que não está lá é HTTP 404.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copylab.exceptions import DataError
from copylab.ingestion.provider import FILLS_PAGE_MAX
from copylab.timeutil import Ms

__all__ = ["FakeArchive", "FakeInfo"]


@dataclass
class FakeInfo:
    """:class:`~copylab.ingestion.provider.InfoProvider` em memória."""

    fills: Mapping[str, Sequence[dict[str, Any]]] = field(default_factory=dict)
    roles: Mapping[str, str] = field(default_factory=dict)
    meta_payload: dict[str, Any] = field(default_factory=lambda: {"universe": []})
    leaderboard_body: bytes = b'{"leaderboardRows": []}'
    funding: Mapping[str, Sequence[dict[str, Any]]] = field(default_factory=dict)
    page_size: int = FILLS_PAGE_MAX
    failing: frozenset[str] = frozenset()
    calls: list[tuple[str, str, int, int]] = field(default_factory=list)

    def leaderboard(self) -> bytes:
        self.calls.append(("leaderboard", "", 0, 0))
        return self.leaderboard_body

    def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
        self.calls.append(("user_fills", address, start, end))
        if address in self.failing:
            raise DataError(f"falha simulada em {address}")
        last = end - 1  # o endTime da API é inclusivo
        ordered = sorted(self.fills.get(address, ()), key=lambda f: int(f["time"]))
        return [dict(f) for f in ordered if start <= int(f["time"]) <= last][: self.page_size]

    def user_role(self, address: str) -> str:
        self.calls.append(("user_role", address, 0, 0))
        if address in self.failing:
            raise DataError(f"falha simulada em {address}")
        return self.roles.get(address, "missing")

    def meta(self) -> dict[str, Any]:
        self.calls.append(("meta", "", 0, 0))
        return self.meta_payload

    def funding_history(self, coin: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
        self.calls.append(("funding_history", coin, start, end))
        return [dict(r) for r in self.funding.get(coin, ()) if start <= int(r["time"]) < end]


@dataclass
class FakeArchive:
    """:class:`~copylab.ingestion.proxy.DailyArchive` em memória.

    ``files[(símbolo, dia)]`` é o zip; ausente é 404. Com ``wrong_sum``, o ``.CHECKSUM``
    publicado não confere. ``downloads`` e ``sums`` registram o que foi pedido.
    """

    files: Mapping[tuple[str, int], bytes] = field(default_factory=dict)
    wrong_sum: bool = False
    downloads: list[tuple[str, int, Path]] = field(default_factory=list)
    sums: list[tuple[str, int]] = field(default_factory=list)

    def checksum(self, symbol: str, day: int) -> str | None:
        self.sums.append((symbol, day))
        data = self.files.get((symbol, day))
        if data is None:
            return None
        return "0" * 64 if self.wrong_sum else hashlib.sha256(data).hexdigest()

    def download(self, symbol: str, day: int, dest: Path) -> bool:
        self.downloads.append((symbol, day, dest))
        data = self.files.get((symbol, day))
        if data is None:
            return False
        dest.write_bytes(data)
        return True
