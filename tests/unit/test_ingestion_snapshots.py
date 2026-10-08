"""Snapshots do leaderboard e dos lotes (T-021; RF-ING-01 CA-01.1, RF-ING-05 CA-05.2,
RF-SEL-01 CA-01.3 na parte da tabela derivada).

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez:

- ``ParquetStore.create`` sem a recusa (grava por cima): falhou
  ``test_leaderboard_snapshot_is_timestamped_hashed_and_never_overwritten``, porque o
  segundo snapshot no mesmo instante trocou o corpo gravado.
- ``parse_leaderboard`` copiando também ``windowPerformances``: falharam
  ``test_derived_leaderboard_has_only_address_and_account_value`` e o teste acima, que
  confere as linhas derivadas.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from copylab.exceptions import DataError
from copylab.ingestion.fake import FakeInfo
from copylab.ingestion.snapshots import ingest_snapshot, parse_leaderboard
from copylab.storage import ParquetRepository, ParquetStore
from copylab.timeutil import Ms

A = "0x" + "a" * 40
B = "0x" + "b" * 40
T1 = Ms(1_791_244_800_000)
T2 = Ms(T1 + 3_600_000)


def board(*rows: tuple[str, str]) -> bytes:
    return json.dumps(
        {
            "leaderboardRows": [
                {
                    "ethAddress": address,
                    "accountValue": value,
                    "displayName": None,
                    "prize": 0,
                    "windowPerformances": [["day", {"pnl": "1.0", "roi": "0.1", "vlm": "9"}]],
                }
                for address, value in rows
            ]
        }
    ).encode()


META: dict[str, Any] = {
    "universe": [
        {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
        {"name": "kPEPE", "szDecimals": 0, "maxLeverage": 10, "isDelisted": True},
    ]
}


@pytest.mark.unit
def test_leaderboard_snapshot_is_timestamped_hashed_and_never_overwritten(
    tmp_path: Path,
) -> None:
    store = ParquetStore(tmp_path)
    repo = ParquetRepository(store)
    first, second = board((A, "50000.5")), board((A, "60000"), (B, "31000"))

    r1 = ingest_snapshot(FakeInfo(leaderboard_body=first, meta_payload=META), store, T1)
    r2 = ingest_snapshot(FakeInfo(leaderboard_body=second, meta_payload=META), store, T2)

    assert repo.snapshots("raw/leaderboard") == [T1, T2]
    raw = repo.raw_leaderboard(T1).row(0, named=True)
    assert raw == {"snapshot_ms": T1, "sha256": hashlib.sha256(first).hexdigest(), "body": first}
    assert r1.sha256 == hashlib.sha256(first).hexdigest()
    assert r2.wallets == 2

    with pytest.raises(DataError, match="não é sobrescrita"):
        ingest_snapshot(FakeInfo(leaderboard_body=second, meta_payload=META), store, T1)
    assert repo.raw_leaderboard(T1).item(0, "body") == first
    assert repo.leaderboard(T1).rows() == [(A, 50_000.5)]


@pytest.mark.unit
def test_derived_leaderboard_has_only_address_and_account_value(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    ingest_snapshot(FakeInfo(leaderboard_body=board((A, "1")), meta_payload=META), store, T1)
    derived = ParquetRepository(store).leaderboard(T1)
    assert derived.columns == ["address", "account_value"]


@pytest.mark.unit
def test_lot_size_is_stored_with_collection_instant(tmp_path: Path) -> None:
    # O meta delistado também entra: um fill antigo de kPEPE ainda precisa do lote.
    store = ParquetStore(tmp_path)
    ingest_snapshot(FakeInfo(leaderboard_body=board((A, "1")), meta_payload=META), store, T1)
    repo = ParquetRepository(store)
    assert repo.snapshots("meta") == [T1]
    assert repo.meta(T1).rows() == [("BTC", 5), ("kPEPE", 0)]


@pytest.mark.unit
def test_addresses_are_stored_lowercase() -> None:
    mixed = "0x" + "AbCd" * 10
    assert parse_leaderboard(board((mixed, "1"))).item(0, "address") == mixed.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"[]", "fora do formato"),
        (board(("0x123", "1")), "endereço inválido"),
        (board((A, "muito")), "não é número"),
        (board((A, "1"), (A.upper().replace("0X", "0x"), "2")), "repetido"),
    ],
)
def test_leaderboard_out_of_format_fails(body: bytes, message: str) -> None:
    with pytest.raises(DataError, match=message):
        parse_leaderboard(body)
