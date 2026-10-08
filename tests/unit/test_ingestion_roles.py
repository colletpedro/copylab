"""Tipo de conta (T-026): tabela ``roles`` gravada com o instante da coleta.

Prova de dente, feita à mão em 2026-10-07 e restaurada: ``ingest_roles`` gravando com
``store.write`` numa partição fixa, em vez de ``create`` por instante, fez falhar os dois
testes: nenhum snapshot ficou achável pelo instante da coleta.
"""

from pathlib import Path

import pytest

from copylab.ingestion.fake import FakeInfo
from copylab.ingestion.roles import ingest_roles
from copylab.storage import ParquetRepository, ParquetStore
from copylab.timeutil import Ms

A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40
T1 = Ms(1_791_244_800_000)
T2 = Ms(T1 + 60_000)


@pytest.mark.unit
def test_roles_are_stored_with_collection_instant(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    info = FakeInfo(roles={A: "user", B: "vault"})
    ingest_roles(info, store, [B, A], T1)
    ingest_roles(FakeInfo(roles={A: "subAccount"}), store, [A], T2)

    repo = ParquetRepository(store)
    assert repo.snapshots("roles") == [T1, T2]
    assert repo.roles(T1).rows() == [(A, "user"), (B, "vault")]
    assert repo.roles(T2).rows() == [(A, "subAccount")]


@pytest.mark.unit
def test_role_failure_does_not_abort_the_others(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    info = FakeInfo(roles={A: "user", C: "user"}, failing=frozenset({B}))
    report = ingest_roles(info, store, [A, B, C], T1)
    assert sorted(report.roles) == [A, C]
    assert list(report.failed) == [B]
    assert ParquetRepository(store).roles(T1).height == 2
