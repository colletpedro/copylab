"""Funding (T-024; RF-ING-05 CA-05.1).

Janela de horas cheias a partir de ``H0`` = 2026-07-01T00:00:00Z. Os registros vêm alguns
milissegundos depois da hora cheia, como a verificação mediu (0 a 127 ms).

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
``copylab.ingestion.funding``:

- Sem a conferência de horas faltantes (``missing = []``): falhou
  ``test_funding_record_is_floored_to_hour_and_missing_hour_fails`` (gravou 4 horas de 5).
- Associação pelo arredondamento para cima (hora seguinte): falharam esse e os dois testes
  de consulta em blocos, todos com horas deslocadas.
"""

from pathlib import Path
from typing import Any

import pytest

from copylab.exceptions import DataError
from copylab.ingestion.fake import FakeInfo
from copylab.ingestion.funding import funding_covered, ingest_funding
from copylab.storage import ParquetRepository, ParquetStore, Span
from copylab.timeutil import MS_PER_HOUR, Ms

H0 = 1_782_864_000_000
H = MS_PER_HOUR


def record(t: int, rate: str = "0.0000125", coin: str = "BTC") -> dict[str, Any]:
    return {"coin": coin, "fundingRate": rate, "premium": "-0.0003", "time": t}


@pytest.mark.unit
def test_funding_record_is_floored_to_hour_and_missing_hour_fails(tmp_path: Path) -> None:
    # Cinco horas. Registros em H0 + 0 ms, H0 + 1 h + 127 ms, H0 + 2 h + 3 ms, ... cada um
    # vai para a hora cheia que o contém: hour_ms = H0 + k h.
    offsets = [0, 127, 3, 64, 1]
    source = {"BTC": [record(H0 + k * H + o, rate=f"0.0000{k}") for k, o in enumerate(offsets)]}
    store = ParquetStore(tmp_path)
    span = Span(Ms(H0), Ms(H0 + 5 * H))

    result = ingest_funding(FakeInfo(funding=source), store, "BTC", span)
    stored = ParquetRepository(store).funding("BTC", Ms(H0), Ms(H0 + 5 * H))
    assert result.hours == 5
    assert stored.get_column("hour_ms").to_list() == [H0 + k * H for k in range(5)]
    assert stored.get_column("time_ms").to_list() == [H0 + k * H + o for k, o in enumerate(offsets)]
    assert stored.get_column("rate").to_list() == pytest.approx([0.0, 1e-5, 2e-5, 3e-5, 4e-5])
    assert funding_covered(store, "BTC", span)

    # Sem o registro da hora 3: falha explícita, nada gravado para o ETH.
    gap = {"ETH": [record(H0 + k * H + 5, coin="ETH") for k in (0, 1, 2, 4)]}
    with pytest.raises(DataError, match=r"1 hora.*sem registro"):
        ingest_funding(FakeInfo(funding=gap), store, "ETH", span)
    assert ParquetRepository(store).funding("ETH", Ms(H0), Ms(H0 + 5 * H)).height == 0


@pytest.mark.unit
def test_two_records_in_one_hour_fail(tmp_path: Path) -> None:
    source = {"BTC": [record(H0 + 5), record(H0 + 900_000), record(H0 + H + 5)]}
    with pytest.raises(DataError, match="dois registros"):
        ingest_funding(
            FakeInfo(funding=source), ParquetStore(tmp_path), "BTC", Span(Ms(H0), Ms(H0 + 2 * H))
        )


@pytest.mark.unit
def test_long_window_is_asked_in_blocks_of_500_hours(tmp_path: Path) -> None:
    # 600 horas: um bloco de 500 e um de 100. Cada bloco chega inteiro numa resposta, e a
    # última hora do bloco encerra o bloco sem pedido extra: 2 consultas.
    source = {"BTC": [record(H0 + k * H + 7) for k in range(600)]}
    fake = FakeInfo(funding=source)
    result = ingest_funding(fake, ParquetStore(tmp_path), "BTC", Span(Ms(H0), Ms(H0 + 600 * H)))
    assert result.hours == 600
    assert [(c[2], c[3]) for c in fake.calls] == [
        (H0, H0 + 500 * H),
        (H0 + 500 * H, H0 + 600 * H),
    ]


@pytest.mark.unit
def test_truncated_response_is_followed_until_empty(tmp_path: Path) -> None:
    # Servidor que devolve no máximo 2 registros: a ingestão pede de novo do registro
    # seguinte ao último. 3 horas: [h0, h1], depois [h2], que é a última hora: fim.
    class Truncating(FakeInfo):
        def funding_history(self, coin: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
            return super().funding_history(coin, start, end)[:2]

    fake = Truncating(funding={"BTC": [record(H0 + k * H + 1) for k in range(3)]})
    result = ingest_funding(fake, ParquetStore(tmp_path), "BTC", Span(Ms(H0), Ms(H0 + 3 * H)))
    assert result.hours == 3
    assert result.requests == 2


@pytest.mark.unit
def test_funding_window_must_be_whole_hours(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="hora cheia"):
        ingest_funding(FakeInfo(), ParquetStore(tmp_path), "BTC", Span(Ms(H0 + 1), Ms(H0 + H)))


@pytest.mark.unit
def test_funding_record_out_of_format_fails(tmp_path: Path) -> None:
    source = {"BTC": [{"coin": "BTC", "fundingRate": "x", "premium": "0", "time": H0}]}
    with pytest.raises(DataError, match="ilegível"):
        ingest_funding(
            FakeInfo(funding=source), ParquetStore(tmp_path), "BTC", Span(Ms(H0), Ms(H0 + H))
        )
