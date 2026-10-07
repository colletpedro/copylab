"""Armazenamento em arquivos Parquet, sem servidor de banco (ADR-0006, design §3.2).

Único pacote que conhece o diretório de dados e o formato dos arquivos. Este é o núcleo
genérico (T-004): diretório, escrita atômica, leitura por partição, hash de conteúdo,
interface de escrita e janelas congeladas. As tabelas de cada origem chegam com a
ingestão e o coletor.
"""

from copylab.storage.files import ParquetStore, Partition, WriteOutcome, Writer
from copylab.storage.hashing import content_hash
from copylab.storage.spans import Span, intersect, normalize

__all__ = [
    "ParquetStore",
    "Partition",
    "Span",
    "WriteOutcome",
    "Writer",
    "content_hash",
    "intersect",
    "normalize",
]
