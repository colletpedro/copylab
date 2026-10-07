"""Hash de conteúdo (ADR-0006 decisão 5, design §3.2).

Prova de dente de `test_content_hash_ignores_file_bytes_and_row_order`, feita à mão em
2026-10-07 e restaurada, uma mutação por vez em `copylab.storage.hashing`:

- sem a ordenação canônica (`canonical.sort(...)` removido): o teste falhou, porque a
  cópia embaralhada deu outro hash; `test_hash_matches_the_documented_encoding` também.
- colunas na ordem do arquivo em vez de por nome (`for name in canonical.columns`): o
  teste falhou, porque a cópia tem as colunas em outra ordem.
- sem normalizar o zero negativo antes da ordenação: falharam
  `test_negative_zero_and_nan_payloads_are_normalized` e
  `test_negative_zero_ties_do_not_depend_on_arrival_order`, e não este, como esperado.
- sem o NaN canônico (`_canonical_nan` devolvendo `v`): falhou
  `test_negative_zero_and_nan_payloads_are_normalized`.
"""

import hashlib
import struct
from pathlib import Path

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.storage import ParquetStore, Span, content_hash
from copylab.timeutil import Ms

KEYS = ["time_ms", "seq"]


def fills() -> pl.DataFrame:
    """Três fills à mão. Dois no mesmo milissegundo, desempatados por `seq`."""
    return pl.DataFrame(
        {
            "time_ms": [1_000, 1_000, 2_000],
            "seq": [0, 1, 2],
            "coin": ["BTC", "BTC", "ETH"],
            "px": [100.5, 100.0, 2_500.25],
            "sz": [0.1, 0.2, 1.5],
            "crossed": [True, False, True],
            "twap_id": [None, 7, None],
            "liquidated_user": [None, None, "0xdead"],
        },
        schema={
            "time_ms": pl.Int64,
            "seq": pl.Int64,
            "coin": pl.String,
            "px": pl.Float64,
            "sz": pl.Float64,
            "crossed": pl.Boolean,
            "twap_id": pl.Int64,
            "liquidated_user": pl.String,
        },
    )


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.unit
def test_content_hash_ignores_file_bytes_and_row_order(tmp_path: Path) -> None:
    """O mesmo conteúdo em dois arquivos de bytes diferentes tem o mesmo hash.

    Arquivo 1: gravado pelo armazenamento (zstd, linhas em ordem de instante).
    Arquivo 2: linhas em ordem inversa, colunas em outra ordem, sem compressão.
    """
    original = fills()
    store = ParquetStore(tmp_path / "data")
    store.write("fills", ("0xabc",), original, span=Span(Ms(0), Ms(10_000)), instant="time_ms")
    first = tmp_path / "data" / "fills" / "0xabc.parquet"

    shuffled = original.reverse().select(sorted(original.columns, reverse=True))
    second = tmp_path / "copia.parquet"
    shuffled.write_parquet(second, compression="uncompressed")

    assert _file_digest(first) != _file_digest(second)
    from_first = content_hash(store.read("fills", ("0xabc",)), KEYS)
    from_second = content_hash(pl.read_parquet(second), KEYS)
    assert from_first == from_second == content_hash(original, KEYS)

    # E muda com um único valor: 100.5 vira 100.50000000000001 (o próximo float).
    changed = original.with_columns(
        pl.when(pl.col("seq") == 0).then(100.50000000000001).otherwise(pl.col("px")).alias("px")
    )
    assert content_hash(changed, KEYS) != content_hash(original, KEYS)


@pytest.mark.unit
def test_seq_is_part_of_the_hash() -> None:
    """Decisão 27 do design: trocar a ordem de dois fills do mesmo milissegundo muda o hash.

    Os preços 100.5 e 100.0 trocam de `seq`: o conteúdo como multiconjunto de (preço,
    tamanho) é o mesmo, mas o preço do último fill do evento muda.
    """
    original = fills()
    swapped = original.with_columns(
        pl.when(pl.col("seq") == 0)
        .then(1)
        .when(pl.col("seq") == 1)
        .then(0)
        .otherwise(pl.col("seq"))
        .alias("seq")
    )
    assert content_hash(swapped, KEYS) != content_hash(original, KEYS)


@pytest.mark.unit
def test_negative_zero_and_nan_payloads_are_normalized() -> None:
    nan_a = struct.unpack("<d", b"\x00\x00\x00\x00\x00\x00\xf8\x7f")[0]
    nan_b = struct.unpack("<d", b"\x01\x00\x00\x00\x00\x00\xf8\x7f")[0]
    a = pl.DataFrame({"k": [1, 2], "x": [0.0, nan_a]})
    b = pl.DataFrame({"k": [1, 2], "x": [-0.0, nan_b]})
    assert content_hash(a, ["k"]) == content_hash(b, ["k"])


@pytest.mark.unit
def test_negative_zero_ties_do_not_depend_on_arrival_order() -> None:
    """-0.0 e 0.0 empatados numa coluna de desempate não reordenam as linhas."""
    a = pl.DataFrame({"k": [1, 1], "x": [-0.0, 0.0], "y": [2, 1]})
    b = pl.DataFrame({"k": [1, 1], "x": [0.0, -0.0], "y": [2, 1]})
    assert content_hash(a, ["k"]) == content_hash(b, ["k"])


@pytest.mark.unit
def test_null_is_not_zero_nor_empty_text() -> None:
    assert content_hash(pl.DataFrame({"x": [None, 1]}), ["x"]) != content_hash(
        pl.DataFrame({"x": [0, 1]}), ["x"]
    )
    assert content_hash(
        pl.DataFrame({"s": [None]}, schema={"s": pl.String}), ["s"]
    ) != content_hash(pl.DataFrame({"s": [""]}), ["s"])


@pytest.mark.unit
def test_integer_width_does_not_matter_but_column_names_do() -> None:
    narrow = pl.DataFrame({"x": [1, 2]}, schema={"x": pl.Int32})
    wide = pl.DataFrame({"x": [1, 2]}, schema={"x": pl.Int64})
    renamed = pl.DataFrame({"y": [1, 2]}, schema={"y": pl.Int64})
    assert content_hash(narrow, ["x"]) == content_hash(wide, ["x"])
    assert content_hash(renamed, ["y"]) != content_hash(wide, ["x"])


@pytest.mark.unit
def test_hash_matches_the_documented_encoding() -> None:
    """A codificação da docstring de `hashing`, montada byte a byte aqui.

    Tabela: k = [2, 1] (inteiro), s = ["é", None] (texto), chave k. Em ordem canônica, as
    linhas viram (1, None) e (2, "é"). "é" em UTF-8 são 2 bytes, c3 a9.
    """

    def u64(n: int) -> bytes:
        return n.to_bytes(8, "little")

    expected = hashlib.sha256()
    expected.update(b"copylab/content-hash/v1\n")
    expected.update(u64(2) + u64(2))  # 2 linhas, 2 colunas
    # coluna "k": nome, tipo, validade, valores 1 e 2 em 64 bits com sinal
    expected.update(u64(1) + b"k" + b"i" + bytes([1, 1]))
    expected.update(struct.pack("<qq", 1, 2))
    # coluna "s": nome, tipo, validade (nulo, valor), texto vazio no lugar do nulo, "é"
    expected.update(u64(1) + b"s" + b"s" + bytes([0, 1]))
    expected.update(u64(0) + u64(2) + "é".encode())

    frame = pl.DataFrame({"k": [2, 1], "s": ["é", None]})
    assert content_hash(frame, ["k"]) == expected.hexdigest()


@pytest.mark.unit
def test_unknown_key_or_unsupported_type_is_data_error() -> None:
    with pytest.raises(DataError, match="não são colunas"):
        content_hash(fills(), ["tid"])
    with pytest.raises(DataError, match="não aceita"):
        content_hash(pl.DataFrame({"x": [[1, 2]]}), [])
    with pytest.raises(DataError, match="64 bits"):
        content_hash(pl.DataFrame({"x": [2**64 - 1]}, schema={"x": pl.UInt64}), [])
