"""Snapshots do leaderboard e dos tamanhos de lote (T-021; RF-ING-01, RF-ING-05 CA-05.2).

Os dois são coletados hoje, depois do corte da Rota A, porque a API não os devolve para uma
data passada (design §3.2, "O que fica fora do corte"). Cada execução grava, com o mesmo
instante de coleta:

- ``raw/leaderboard``: o corpo bruto, como chegou, com o SHA-256 dele. Nunca sobrescrito.
- ``leaderboard``: só ``address`` e ``account_value``. Os campos de desempenho
  (``windowPerformances``: PnL, ROI, volume) **não são copiados**, e por isso a seleção não
  tem como lê-los (RF-SEL-01 CA-01.3, na parte da tabela derivada).
- ``meta``: ``coin`` e ``sz_decimals`` dos perpétuos do primeiro dex. O lote de um ativo é
  ``10 ** -sz_decimals``.

O endereço é guardado em minúsculas: a API o devolve assim, e um sistema de arquivos que
não distingue maiúsculas (o do Windows) não pode receber duas grafias da mesma carteira.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Final

import polars as pl

from copylab.exceptions import DataError
from copylab.ingestion.provider import InfoProvider
from copylab.logging import get_logger
from copylab.storage import ParquetStore
from copylab.storage.tables import LEADERBOARD, META, RAW_LEADERBOARD, SCHEMAS
from copylab.timeutil import Ms, iso

__all__ = ["SnapshotResult", "ingest_snapshot", "parse_leaderboard", "parse_meta"]

log = get_logger(__name__)

_ADDRESS: Final = re.compile(r"0x[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    snapshot_ms: Ms
    sha256: str
    body_bytes: int
    wallets: int
    perps: int


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise DataError(f"{what} não é número: {value!r}")
    try:
        return float(value)
    except ValueError as exc:
        raise DataError(f"{what} não é número: {value!r}") from exc


def parse_leaderboard(body: bytes) -> pl.DataFrame:
    """Endereço e patrimônio de cada linha do leaderboard; nada mais.

    Raises:
        DataError: corpo fora do formato, endereço inválido ou repetido.
    """
    try:
        rows = json.loads(body)["leaderboardRows"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DataError(f"Leaderboard fora do formato: {exc}") from exc
    if not isinstance(rows, list):
        raise DataError("Leaderboard: leaderboardRows não é lista.")
    addresses: list[str] = []
    values: list[float] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DataError(f"Leaderboard: linha {index} não é objeto.")
        address = str(row.get("ethAddress", "")).lower()
        if _ADDRESS.fullmatch(address) is None:
            raise DataError(f"Leaderboard: endereço inválido na linha {index}: {address!r}.")
        addresses.append(address)
        values.append(_number(row.get("accountValue"), f"accountValue de {address}"))
    if len(set(addresses)) != len(addresses):
        raise DataError("Leaderboard: endereço repetido.")
    return pl.DataFrame(
        {"address": addresses, "account_value": values}, schema=SCHEMAS[LEADERBOARD]
    )


def parse_meta(payload: dict[str, Any]) -> pl.DataFrame:
    """``coin`` e ``sz_decimals`` de cada perpétuo do ``meta``, delistados inclusive.

    Raises:
        DataError: item sem nome, com casas decimais inválidas ou nome repetido.
    """
    coins: list[str] = []
    decimals: list[int] = []
    for index, item in enumerate(payload["universe"]):
        name = item.get("name") if isinstance(item, dict) else None
        sz = item.get("szDecimals") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            raise DataError(f"meta: item {index} sem nome.")
        if isinstance(sz, bool) or not isinstance(sz, int) or sz < 0:
            raise DataError(f"meta: szDecimals inválido em {name}: {sz!r}.")
        coins.append(name)
        decimals.append(sz)
    if len(set(coins)) != len(coins):
        raise DataError("meta: ativo repetido.")
    return pl.DataFrame({"coin": coins, "sz_decimals": decimals}, schema=SCHEMAS[META])


def ingest_snapshot(provider: InfoProvider, store: ParquetStore, now: Ms) -> SnapshotResult:
    """Grava o snapshot do leaderboard (bruto e derivado) e o dos lotes, no instante ``now``.

    O corpo bruto é gravado antes de ser interpretado: um formato novo não custa o dado.

    Raises:
        DataError: já existe snapshot nesse instante, ou a resposta está fora do formato.
    """
    body = provider.leaderboard()
    digest = hashlib.sha256(body).hexdigest()
    partition = (str(now),)
    raw = pl.DataFrame(
        {"snapshot_ms": [now], "sha256": [digest], "body": [body]}, schema=SCHEMAS[RAW_LEADERBOARD]
    )
    store.create(RAW_LEADERBOARD, partition, raw)
    board = parse_leaderboard(body)
    meta = parse_meta(provider.meta())
    store.create(LEADERBOARD, partition, board)
    store.create(META, partition, meta)
    result = SnapshotResult(now, digest, len(body), board.height, meta.height)
    log.info(
        "ingest.snapshot",
        snapshot_ms=now,
        at=iso(now),
        sha256=digest,
        body_mb=round(len(body) / 10**6, 2),
        wallets=board.height,
        perps=meta.height,
    )
    return result
