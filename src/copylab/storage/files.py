"""Diretório de dados, partições Parquet e escrita atômica (ADR-0006, design §3.2).

Só este pacote conhece o diretório de dados e o formato dos arquivos
(``test_architecture_storage_isolation``). Cada tabela é uma pasta sob o diretório de
dados, e cada partição é um arquivo Parquet nela:
``<diretório>/<tabela>/<parte 1>/.../<parte n>.parquet``. A chave de partição de cada
tabela é a de design §3.2, e quem a escolhe é o código daquela tabela.

**Escrita atômica.** Toda escrita vai para um arquivo temporário oculto, na mesma pasta,
que é sincronizado com o disco e então trocado de nome por cima do anterior. Uma queda no
meio deixa a partição anterior intacta e, no máximo, um temporário que a leitura ignora.

**Trechos gravados e janelas congeladas.** Cada escrita declara o intervalo
``[início, fim)`` que ela descreve por inteiro numa partição, e substitui as linhas
gravadas nesse intervalo. A partição guarda, nos metadados do próprio arquivo Parquet,
a lista dos intervalos já gravados: o registro e os dados mudam na mesma troca de nome.
O :class:`ParquetStore` recebe as janelas congeladas, que a CLI lê dos congelamentos.
Onde uma janela congelada encontra um trecho já gravado, as linhas gravadas ficam como
estão e a escrita nova não entra; as diferenças voltam ao chamador em
:class:`WriteOutcome` e são logadas. Gravar pela primeira vez dentro de uma janela
congelada é permitido (design §3.2, "Janela congelada").
"""

import json
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import polars as pl

from copylab.config import Settings
from copylab.exceptions import ConfigError, DataError
from copylab.logging import get_logger
from copylab.storage.spans import Span, intersect, normalize
from copylab.timeutil import Ms, iso

__all__ = ["ParquetStore", "Partition", "WriteOutcome", "Writer", "multiset_difference"]

log = get_logger(__name__)

Partition = tuple[str, ...]
"""Valores da chave de partição de uma tabela, na ordem da chave."""

_SUFFIX: Final = ".parquet"
_TMP_SUFFIX: Final = ".tmp"
#: Chave, nos metadados do Parquet, da lista de trechos gravados da partição.
_SPANS_KEY: Final = "copylab.spans"
#: Uma parte de caminho aceita: sem separador, sem começar por ponto, não vazia.
_SEGMENT: Final = re.compile(r"[^/\\\x00.][^/\\\x00]*")


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """O que uma escrita fez.

    ``frozen_kept`` são linhas já gravadas em trecho congelado que a coleta nova não
    reproduz; elas continuam gravadas. ``frozen_rejected`` são linhas da coleta nova em
    trecho congelado que não estavam gravadas; elas não entram. As duas são multiconjuntos
    de linhas inteiras: uma linha alterada aparece uma vez em cada.
    """

    rows: int
    frozen_kept: pl.DataFrame
    frozen_rejected: pl.DataFrame

    @property
    def diverged(self) -> bool:
        return self.frozen_kept.height > 0 or self.frozen_rejected.height > 0


class Writer(Protocol):
    """Escrita em tabela. Só ingestão, coletor e CLI recebem esta interface."""

    def write(
        self,
        table: str,
        partition: Partition,
        frame: pl.DataFrame,
        *,
        span: Span,
        instant: str | pl.Expr,
    ) -> WriteOutcome: ...


def _check_segment(kind: str, value: str) -> str:
    if _SEGMENT.fullmatch(value) is None:
        raise DataError(f"{kind} inválido para caminho: {value!r}.")
    return value


def _in_spans(instant: pl.Expr, spans: Sequence[Span]) -> pl.Expr:
    condition = pl.lit(False)
    for span in spans:
        condition = condition | ((instant >= span.start) & (instant < span.end))
    return condition


def _cell_key(value: object) -> object:
    if isinstance(value, float):
        if value != value:
            return ("nan",)
        if value == 0.0:
            return 0.0
    return value


def _row_key(row: tuple[object, ...]) -> tuple[object, ...]:
    """Linha comparável num ``Counter``: NaN é igual a NaN, e -0.0 a 0.0."""
    return tuple(_cell_key(value) for value in row)


def multiset_difference(
    left: pl.DataFrame, right: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Linhas só de ``left`` e linhas só de ``right``, contando repetições.

    NaN é igual a NaN e -0.0 a 0.0. As linhas saem na ordem em que estavam.
    """
    left_rows, right_rows = left.rows(), right.rows()
    common = Counter(map(_row_key, left_rows)) & Counter(map(_row_key, right_rows))

    def only(rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
        budget = Counter(common)
        out = []
        for row in rows:
            key = _row_key(row)
            if budget[key] > 0:
                budget[key] -= 1
            else:
                out.append(row)
        return out

    return (
        pl.DataFrame(only(left_rows), schema=left.schema, orient="row"),
        pl.DataFrame(only(right_rows), schema=right.schema, orient="row"),
    )


class ParquetStore:
    """Tabelas Parquet sob o diretório de dados. Implementa :class:`Writer`."""

    def __init__(self, root: Path, frozen: Sequence[Span] = ()) -> None:
        if root.exists() and not root.is_dir():
            raise ConfigError(f"O diretório de dados {root} existe e não é um diretório.")
        self._root = root
        self._frozen = normalize(frozen)

    @classmethod
    def from_settings(cls, settings: Settings, frozen: Sequence[Span] = ()) -> "ParquetStore":
        """Abre o diretório de ``COPYLAB_DATA_DIR``.

        Raises:
            ConfigError: se a variável não estiver definida.
        """
        if settings.data_dir is None:
            raise ConfigError(
                "COPYLAB_DATA_DIR não está definido. Aponte-o para o diretório de dados, "
                "fora do git (ver .env.example)."
            )
        return cls(settings.data_dir, frozen)

    @property
    def frozen(self) -> tuple[Span, ...]:
        """Janelas congeladas que esta instância respeita, já normalizadas."""
        return self._frozen

    # ─── Caminhos ────────────────────────────────────────────────────────────

    def _table_dir(self, table: str) -> Path:
        parts = table.split("/")
        for part in parts:
            _check_segment("Nome de tabela", part)
        return self._root.joinpath(*parts)

    def _path(self, table: str, partition: Partition) -> Path:
        if not partition:
            raise DataError(f"Partição vazia na tabela {table!r}.")
        for part in partition:
            _check_segment("Valor de partição", part)
        *folders, leaf = partition
        return self._table_dir(table).joinpath(*folders, f"{leaf}{_SUFFIX}")

    # ─── Leitura ─────────────────────────────────────────────────────────────

    def partitions(self, table: str) -> list[Partition]:
        """Partições gravadas da tabela, em ordem. Temporários de escrita ficam de fora."""
        base = self._table_dir(table)
        if not base.is_dir():
            return []
        found = []
        for path in base.rglob(f"*{_SUFFIX}"):
            relative = path.relative_to(base).with_suffix("").parts
            if not any(part.startswith(".") for part in relative):
                found.append(tuple(relative))
        return sorted(found)

    def disk_bytes(self, table: str) -> int:
        """Bytes ocupados pelas partições da tabela (temporários incluídos)."""
        base = self._table_dir(table)
        return sum(path.stat().st_size for path in base.rglob("*") if path.is_file())

    def exists(self, table: str, partition: Partition) -> bool:
        return self._path(table, partition).is_file()

    def read(self, table: str, partition: Partition) -> pl.DataFrame:
        """Conteúdo inteiro da partição.

        Raises:
            DataError: se a partição não existe.
        """
        path = self._path(table, partition)
        if not path.is_file():
            raise DataError(f"Partição {partition} da tabela {table!r} não existe.")
        return pl.read_parquet(path)

    def spans(self, table: str, partition: Partition) -> tuple[Span, ...]:
        """Trechos já gravados na partição; vazio se ela não existe."""
        path = self._path(table, partition)
        if not path.is_file():
            return ()
        raw = pl.read_parquet_metadata(path).get(_SPANS_KEY)
        if raw is None:
            raise DataError(f"Partição {partition} de {table!r} sem registro de trechos.")
        return tuple(Span(Ms(start), Ms(end)) for start, end in json.loads(raw))

    # ─── Escrita ─────────────────────────────────────────────────────────────

    def write(
        self,
        table: str,
        partition: Partition,
        frame: pl.DataFrame,
        *,
        span: Span,
        instant: str | pl.Expr,
    ) -> WriteOutcome:
        """Grava ``frame`` como o conteúdo completo de ``span`` na partição.

        ``instant`` é a coluna (ou expressão) com o instante em ``Ms`` de cada linha; é por
        ele que uma linha cai dentro ou fora de ``span`` e das janelas congeladas.

        Raises:
            DataError: linha de ``frame`` fora de ``span``, ou esquema diferente do gravado.
        """
        when = pl.col(instant) if isinstance(instant, str) else instant
        path = self._path(table, partition)
        outside = frame.filter(~_in_spans(when, [span]))
        if outside.height:
            raise DataError(
                f"{outside.height} linha(s) fora do trecho declarado "
                f"[{iso(span.start)}, {iso(span.end)}) em {table!r} {partition}."
            )

        collected = self.spans(table, partition)
        empty = frame.clear()
        kept, rejected = empty, empty
        if path.is_file():
            stored = pl.read_parquet(path)
            if stored.schema != frame.schema:
                raise DataError(
                    f"Esquema novo de {table!r} {partition} difere do gravado: "
                    f"{dict(frame.schema)} contra {dict(stored.schema)}."
                )
            protected = intersect(intersect([span], self._frozen), collected)
            in_protected = _in_spans(when, protected)
            stored_protected = stored.filter(in_protected)
            kept, rejected = multiset_difference(stored_protected, frame.filter(in_protected))
            result = pl.concat(
                [
                    stored.filter(~_in_spans(when, [span])),
                    stored_protected,
                    frame.filter(~in_protected),
                ]
            ).sort(when, maintain_order=True)
        else:
            result = frame.sort(when, maintain_order=True)

        self._replace(path, result, normalize([*collected, span]))
        outcome = WriteOutcome(result.height, kept, rejected)
        if outcome.diverged:
            log.warning(
                "storage.frozen_divergence",
                table=table,
                partition=list(partition),
                kept=kept.height,
                rejected=rejected.height,
            )
        return outcome

    def create(self, table: str, partition: Partition, frame: pl.DataFrame) -> None:
        """Grava uma partição nova, que nunca é sobrescrita (snapshots, ADR-0006 item 3).

        Raises:
            DataError: se a partição já existe; a gravada fica como estava.
        """
        path = self._path(table, partition)
        if path.is_file():
            raise DataError(
                f"Partição {partition} de {table!r} já existe e não é sobrescrita: "
                "um snapshot é gravado uma vez só."
            )
        self._replace(path, frame, ())

    def append(self, table: str, partition: Partition, frame: pl.DataFrame) -> int:
        """Acrescenta linhas a um registro que só cresce, como ``divergences``.

        As linhas gravadas nunca mudam, e a escrita não passa pela proteção de janela
        congelada: um registro de divergências precisa aceitar justamente as que caem
        dentro de uma janela congelada. Devolve o total de linhas depois da escrita.

        Raises:
            DataError: esquema diferente do gravado.
        """
        path = self._path(table, partition)
        if path.is_file():
            stored = pl.read_parquet(path)
            if stored.schema != frame.schema:
                raise DataError(
                    f"Esquema novo de {table!r} {partition} difere do gravado: "
                    f"{dict(frame.schema)} contra {dict(stored.schema)}."
                )
            frame = pl.concat([stored, frame])
        self._replace(path, frame, ())
        return frame.height

    def _replace(self, path: Path, frame: pl.DataFrame, spans: Sequence[Span]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=_TMP_SUFFIX
        )
        os.close(handle)
        try:
            frame.write_parquet(
                temporary,
                compression="zstd",
                metadata={_SPANS_KEY: json.dumps([[s.start, s.end] for s in spans])},
            )
            with open(temporary, "rb+") as written:
                os.fsync(written.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        if sys.platform == "win32":
            return  # o Windows não abre pasta como arquivo; o NTFS registra a troca de nome
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
