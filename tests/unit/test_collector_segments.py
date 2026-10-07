"""Segmentos brutos do coletor (design §3.4, `copylab.storage.segments`).

Prova de dente de `test_restart_neither_duplicates_nor_corrupts_segments`, feita à mão
em 2026-10-07 e restaurada, uma mutação por vez:

- `_members` tolerante devolvendo também o membro truncado (sem `if not decoder.eof`):
  `recover` passou a manter o lixo, e a leitura estrita do segmento recuperado levantou
  `DataError`. O teste falhou.
- `recover` sem `os.truncate`: o segmento fechado ficou com o bloco cortado no fim, e a
  leitura estrita levantou `DataError`. O teste falhou.
- `open_writer` com `"ab"` no lugar de `"xb"` e o instante de abertura fixo: o segundo
  processo acrescentou ao segmento do primeiro, e a contagem de segmentos falhou.
"""

import gzip
import threading
from pathlib import Path

import pytest

from copylab.exceptions import ConfigError, DataError
from copylab.storage.segments import Record, SegmentStore
from copylab.timeutil import Ms

HOUR = Ms(1_791_259_200_000)  # 2026-10-06T04:00:00Z, uma hora cheia


def rec(recv: int, conn: int, raw: bytes) -> Record:
    return Record(Ms(recv), Ms(conn), raw)


@pytest.mark.unit
def test_closed_segment_roundtrips_records_and_is_gzip(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    writer = store.open_writer("BTC", "bbo", HOUR, Ms(HOUR + 5))
    records = [rec(HOUR + 10, HOUR + 5, b'{"a":1}'), rec(HOUR + 11, HOUR + 5, b"com\nquebra")]
    for r in records:
        writer.append(r)
    writer.flush()
    writer.append(rec(HOUR + 12, HOUR + 5, b""))
    ref = writer.close()

    assert ref.closed
    assert ref.path.name == f"{HOUR}.{HOUR + 5}.jsonl.gz"
    assert ref.path.read_bytes()[:2] == b"\x1f\x8b"
    assert list(store.read(ref)) == [*records, rec(HOUR + 12, HOUR + 5, b"")]
    # Dois blocos, um por descarga: o arquivo é uma concatenação de membros gzip.
    assert gzip.decompress(ref.path.read_bytes()).count(b"\n") == 4  # 3 registros + 1 no texto
    assert store.segments() == [ref]


@pytest.mark.unit
def test_open_segment_is_listed_only_on_request_and_read_up_to_last_flush(
    tmp_path: Path,
) -> None:
    store = SegmentStore(tmp_path)
    writer = store.open_writer("ETH", "book", HOUR, HOUR)
    writer.append(rec(HOUR + 1, HOUR, b"x"))
    writer.flush()
    writer.append(rec(HOUR + 2, HOUR, b"pendente"))  # não descarregado

    assert store.segments() == []
    (opened,) = store.segments(include_open=True)
    assert not opened.closed
    assert [r.raw for r in store.read(opened)] == [b"x"]
    writer.close()


@pytest.mark.unit
def test_restart_neither_duplicates_nor_corrupts_segments(tmp_path: Path) -> None:
    """RF-COL-04 CA-04.1. O primeiro processo cai no meio de uma escrita.

    Processo 1: grava a e b, descarrega; grava c, que não chega a ser descarregado; o
    disco fica com meio bloco gzip no fim (a queda foi durante a escrita dele).
    Reinício: `recover` fecha o segmento até o último bloco íntegro (a e b). Processo 2:
    grava d num segmento novo da mesma hora. Leitura: a, b, d, uma vez cada, e c perdido,
    que é o máximo que uma queda custa (o que não foi descarregado).
    """
    store = SegmentStore(tmp_path)
    first = store.open_writer("SOL", "trades", HOUR, Ms(HOUR + 1))
    first.append(rec(HOUR + 10, HOUR + 1, b"a"))
    first.append(rec(HOUR + 11, HOUR + 1, b"b"))
    first.flush()
    first.append(rec(HOUR + 12, HOUR + 1, b"c"))
    with first.ref.path.open("ab") as handle:  # a queda: meio bloco gzip no fim do arquivo
        handle.write(gzip.compress(rec(HOUR + 12, HOUR + 1, b"c").encode(), mtime=0)[:15])

    (recovered,) = store.recover()
    second = store.open_writer("SOL", "trades", HOUR, Ms(HOUR + 20))
    second.append(rec(HOUR + 21, HOUR + 20, b"d"))
    second.close()

    segments = store.segments()
    assert [s.opened_ms for s in segments] == [HOUR + 1, HOUR + 20]
    assert [r.raw for s in segments for r in store.read(s)] == [b"a", b"b", b"d"]
    assert store.segments(include_open=True) == segments
    assert recovered == segments[0]


@pytest.mark.unit
def test_recover_drops_an_open_segment_with_no_whole_block(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    writer = store.open_writer("BTC", "bbo", HOUR, HOUR)
    writer.append(rec(HOUR, HOUR, b"nunca descarregado"))
    assert store.recover() == []
    assert store.segments(include_open=True) == []


@pytest.mark.unit
def test_corrupt_closed_segment_is_a_data_error(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    writer = store.open_writer("BTC", "bbo", HOUR, HOUR)
    writer.append(rec(HOUR, HOUR, b"x" * 100))
    ref = writer.close()
    data = bytearray(ref.path.read_bytes())
    data[-6] ^= 0xFF  # um bit do CRC
    ref.path.write_bytes(bytes(data))
    with pytest.raises(DataError, match="corrompido"):
        list(store.read(ref))
    ref.path.write_bytes(bytes(data[:-3]))
    with pytest.raises(DataError, match=r"truncado|corrompido"):
        list(store.read(ref))


@pytest.mark.unit
def test_segment_names_are_validated_and_never_reused(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    with pytest.raises(DataError, match="inválido"):
        store.open_writer("../x", "bbo", HOUR, HOUR)
    with pytest.raises(DataError, match="inválido"):
        store.open_writer("BTC", "", HOUR, HOUR)
    store.open_writer("BTC", "bbo", HOUR, HOUR).close()
    with pytest.raises(DataError, match="já existe"):
        store.open_writer("BTC", "bbo", HOUR, HOUR)


@pytest.mark.unit
def test_open_segment_is_never_deleted(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    writer = store.open_writer("BTC", "bbo", HOUR, HOUR)
    (opened,) = store.segments(include_open=True)
    with pytest.raises(DataError, match="aberto"):
        store.delete(opened)
    closed = writer.close()
    store.delete(closed)
    assert store.segments() == []


@pytest.mark.unit
def test_only_one_recorder_per_data_dir(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    errors: list[Exception] = []

    def second() -> None:
        try:
            with SegmentStore(tmp_path).exclusive():
                pass
        except ConfigError as exc:
            errors.append(exc)

    with store.exclusive():
        thread = threading.Thread(target=second)
        thread.start()
        thread.join()
    assert len(errors) == 1
    assert "Outro gravador" in str(errors[0])
    with store.exclusive():  # liberada
        pass


@pytest.mark.unit
def test_disk_bytes_counts_open_and_closed_segments(tmp_path: Path) -> None:
    store = SegmentStore(tmp_path)
    store.open_writer("BTC", "bbo", HOUR, HOUR).close()
    writer = store.open_writer("ETH", "bbo", HOUR, HOUR)
    writer.append(rec(HOUR, HOUR, b"y"))
    writer.flush()
    expected = sum(ref.path.stat().st_size for ref in store.segments(include_open=True))
    assert store.disk_bytes() == expected > 0
    writer.close()
