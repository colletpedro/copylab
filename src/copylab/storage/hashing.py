"""Hash de conteúdo de uma tabela (ADR-0006 decisão 5, design §3.2).

O hash é calculado dos valores, e nunca dos bytes do arquivo: reescrever o mesmo
conteúdo com outra compressão, outra versão de biblioteca ou outra ordem de linhas não o
muda, e mudar um único valor muda.

**Codificação (versão 1).** As linhas são postas em ordem canônica: as colunas-chave da
tabela, na ordem dada, e as demais colunas, por nome, como desempate. Então, SHA-256 de:

1. o marcador ``copylab/content-hash/v1`` e uma quebra de linha;
2. o número de linhas e o de colunas, cada um em 8 bytes little-endian;
3. para cada coluna, em ordem de nome: o nome (UTF-8 com prefixo de tamanho), uma letra
   de tipo (``i`` inteiro, ``f`` ponto flutuante, ``b`` booleano, ``s`` texto, ``y``
   bytes), um byte por linha dizendo se há valor (1) ou nulo (0), e os valores:
   inteiros como padrão de bits de 64 bits com sinal; flutuantes como padrão de bits
   IEEE 754 de 64 bits, com zero negativo virando zero e todo NaN virando o NaN canônico;
   booleanos em um byte; textos em UTF-8 e bytes como estão, cada um com prefixo de
   tamanho de 8 bytes. Nulo ocupa o lugar de um zero, ou de um texto vazio.

A codificação vai por coluna, e não por linha, para os números irem em bloco. Os nomes
das colunas entram no hash: renomear uma coluna muda o conteúdo. Inteiro de 8, 16 ou 32
bits e o de 64 bits com o mesmo valor dão o mesmo hash, porque a letra de tipo é a
categoria, e não o tipo da biblioteca.

Mudar qualquer regra acima é mudar de versão: o marcador muda junto, e os hashes de
congelamentos antigos deixam de bater, de propósito.
"""

import hashlib
import struct
import sys
from array import array
from collections.abc import Sequence
from typing import Final, Protocol

import polars as pl

from copylab.exceptions import DataError

__all__ = ["content_hash"]

_MAGIC: Final = b"copylab/content-hash/v1\n"
#: Linhas por bloco ao converter uma coluna, para não materializar a tabela inteira.
_CHUNK: Final = 1 << 20
_CANONICAL_NAN: Final = struct.unpack("<d", b"\x00\x00\x00\x00\x00\x00\xf8\x7f")[0]


class _Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _u64(n: int) -> bytes:
    return n.to_bytes(8, "little", signed=False)


def _kind(name: str, dtype: pl.DataType) -> str:
    if dtype.is_integer():
        return "i"
    if dtype.is_float():
        return "f"
    if dtype == pl.Boolean:
        return "b"
    if dtype == pl.String:
        return "s"
    if dtype == pl.Binary:
        return "y"
    raise DataError(f"Coluna {name!r} tem tipo {dtype}, que o hash de conteúdo não aceita.")


def _little_endian(values: array[int] | array[float]) -> bytes:
    if sys.byteorder != "little":  # pragma: no cover - as máquinas do projeto são little-endian
        values.byteswap()
    return values.tobytes()


def _canonical_nan(v: float) -> float:
    """Qualquer NaN vira o NaN canônico. O zero negativo já foi normalizado antes."""
    return float(_CANONICAL_NAN) if v != v else v


def _feed_validity(digest: _Digest, column: pl.Series) -> None:
    for offset in range(0, column.len(), _CHUNK):
        digest.update(bytes(column.slice(offset, _CHUNK).is_not_null().cast(pl.UInt8).to_list()))


def _feed_values(digest: _Digest, name: str, kind: str, column: pl.Series) -> None:
    for offset in range(0, column.len(), _CHUNK):
        chunk = column.slice(offset, _CHUNK)
        if kind == "i":
            try:
                ints = chunk.fill_null(0).cast(pl.Int64, strict=True).to_list()
            except pl.exceptions.InvalidOperationError as exc:
                raise DataError(f"Coluna {name!r} tem inteiro fora de 64 bits com sinal.") from exc
            digest.update(_little_endian(array("q", ints)))
        elif kind == "f":
            floats = chunk.fill_null(0.0).cast(pl.Float64).to_list()
            digest.update(_little_endian(array("d", [_canonical_nan(v) for v in floats])))
        elif kind == "b":
            digest.update(bytes(chunk.fill_null(False).cast(pl.UInt8).to_list()))
        else:
            for value in chunk.to_list():
                raw = b"" if value is None else (value.encode() if kind == "s" else value)
                digest.update(_u64(len(raw)))
                digest.update(raw)


def content_hash(frame: pl.DataFrame, keys: Sequence[str]) -> str:
    """SHA-256, em hexadecimal, do conteúdo de ``frame`` em ordem canônica por ``keys``.

    Raises:
        DataError: chave que não é coluna, ou coluna de tipo que a codificação não cobre.
    """
    missing = [k for k in keys if k not in frame.columns]
    if missing:
        raise DataError(f"Chaves {missing} não são colunas da tabela ({frame.columns}).")
    kinds = {name: _kind(name, dtype) for name, dtype in frame.schema.items()}

    # Zero negativo vira zero antes da ordenação, ou -0.0 e 0.0 empatados ordenariam as
    # linhas de jeitos diferentes conforme a ordem de chegada.
    canonical = frame.with_columns(
        pl.when(pl.col(name) == 0.0).then(pl.lit(0.0)).otherwise(pl.col(name)).alias(name)
        for name, kind in kinds.items()
        if kind == "f"
    )
    order = [*keys, *sorted(c for c in frame.columns if c not in keys)]
    if order:
        canonical = canonical.sort(order, nulls_last=True, maintain_order=True)

    digest = hashlib.sha256(_MAGIC)
    digest.update(_u64(canonical.height))
    digest.update(_u64(canonical.width))
    for name in sorted(canonical.columns):
        column = canonical.get_column(name)
        encoded_name = name.encode()
        digest.update(_u64(len(encoded_name)))
        digest.update(encoded_name)
        digest.update(kinds[name].encode())
        _feed_validity(digest, column)
        _feed_values(digest, name, kinds[name], column)
    return digest.hexdigest()
