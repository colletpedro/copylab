"""Armazenamento em arquivos Parquet, sem servidor de banco (ADR-0006, design §3.2).

Único pacote que conhece o diretório de dados e o formato dos arquivos. Este é o núcleo
genérico (T-004): diretório, escrita atômica, leitura por partição, hash de conteúdo,
interface de escrita e janelas congeladas; os esquemas das tabelas (``tables``) e a leitura
por janela que implementa ``copylab.ports.Repository`` (``repository``).
"""

from copylab.storage.files import (
    ParquetStore,
    Partition,
    WriteOutcome,
    Writer,
    multiset_difference,
)
from copylab.storage.hashing import content_hash
from copylab.storage.repository import ParquetRepository
from copylab.storage.spans import Span, intersect, normalize

__all__ = [
    "ParquetRepository",
    "ParquetStore",
    "Partition",
    "Span",
    "WriteOutcome",
    "Writer",
    "content_hash",
    "intersect",
    "multiset_difference",
    "normalize",
]
