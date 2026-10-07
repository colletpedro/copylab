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

`test_rename_is_retried_while_another_process_holds_the_file`: `_rename` sem nova
tentativa (`if True: raise`) fez o teste falhar.
"""

import gzip
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from copylab.exceptions import ConfigError, DataError
from copylab.storage.segments import Record, SegmentStore
from copylab.timeutil import Ms

HOUR = Ms(1_791_259_200_000)  # 2026-10-06T04:00:00Z, uma hora cheia


def rec(recv: int, conn: int, raw: bytes) -> Record:
    return Record(Ms(recv), Ms(conn), raw)


#: Um processo que grava e morre sem fechar nada, como numa queda de energia. Rodar a
#: queda num processo à parte é o que a torna real: o sistema fecha os arquivos do morto,
#: e nenhum objeto deste processo fica segurando o segmento (no Windows, isso impediria a
#: recuperação de renomeá-lo).
CRASH = """
import gzip, os, sys
from pathlib import Path
from copylab.storage.segments import Record, SegmentStore
from copylab.timeutil import Ms

root, hour, mode = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
if mode == "torn":
    writer = SegmentStore(root).open_writer("SOL", "trades", Ms(hour), Ms(hour + 1))
    writer.append(Record(Ms(hour + 10), Ms(hour + 1), b"a"))
    writer.append(Record(Ms(hour + 11), Ms(hour + 1), b"b"))
    writer.flush()
    writer.append(Record(Ms(hour + 12), Ms(hour + 1), b"c"))
    torn = gzip.compress(Record(Ms(hour + 12), Ms(hour + 1), b"c").encode(), mtime=0)[:15]
    with writer.ref.path.open("ab") as handle:
        handle.write(torn)
else:
    writer = SegmentStore(root).open_writer("BTC", "bbo", Ms(hour), Ms(hour))
    writer.append(Record(Ms(hour), Ms(hour), b"nunca descarregado"))
os._exit(1)
"""


def crash(root: Path, mode: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", CRASH, str(root), str(HOUR), mode], capture_output=True, check=False
    )
    assert result.returncode == 1, result.stderr.decode()


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

    Processo 1, de verdade um processo à parte (`CRASH`, modo "torn"): grava a e b,
    descarrega; grava c, que não chega a ser descarregado; o disco fica com meio bloco
    gzip no fim (a queda foi durante a escrita dele); o processo morre sem fechar nada.
    Reinício: `recover` fecha o segmento até o último bloco íntegro (a e b). Processo 2:
    grava d num segmento novo da mesma hora. Leitura: a, b, d, uma vez cada, e c perdido,
    que é o máximo que uma queda custa (o que não foi descarregado).
    """
    crash(tmp_path, "torn")
    store = SegmentStore(tmp_path)
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
    crash(tmp_path, "empty")
    store = SegmentStore(tmp_path)
    assert len(store.segments(include_open=True)) == 1
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


@pytest.mark.unit
def test_rename_is_retried_while_another_process_holds_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Windows, renomear falha enquanto outro processo (o status, o antivírus) segura o
    arquivo. Com uma espera, o fechamento tenta de novo; sem ela, o erro sobe."""
    import os

    real_replace = os.replace
    failures = [2]

    def busy(src: Path, dst: Path) -> None:
        if failures[0] > 0:
            failures[0] -= 1
            raise PermissionError("arquivo em uso por outro processo")
        real_replace(src, dst)

    monkeypatch.setattr("copylab.storage.segments.os.replace", busy)
    waits: list[float] = []
    writer = SegmentStore(tmp_path, wait=waits.append).open_writer("BTC", "bbo", HOUR, HOUR)
    writer.append(rec(HOUR, HOUR, b"x"))
    ref = writer.close()
    assert ref.path.is_file()
    assert waits == [0.1, 0.1]

    failures[0] = 1
    plain = SegmentStore(tmp_path / "sem-espera").open_writer("BTC", "bbo", HOUR, HOUR)
    with pytest.raises(PermissionError):
        plain.close()
