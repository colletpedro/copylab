"""Nomes, colunas e partições das tabelas da fase (design §3.2, ADR-0006).

Só ``storage`` conhece o formato dos arquivos, e o esquema de cada tabela mora aqui, para
que uma leitura sem partição nenhuma devolva a tabela vazia com as colunas certas, e não
um quadro sem colunas. Quem produz as linhas (ingestão, coletor) monta o quadro com estes
esquemas e o entrega a :class:`~copylab.storage.files.ParquetStore`.

Colunas além das do design: ``conn_ms`` nas tabelas do coletor (design 1.2 §3.2) e
``sha256`` e ``snapshot_ms`` no leaderboard bruto, que o design descreve como "corpo bruto
comprimido e sha256". A partição de cada tabela está no comentário dela.
"""

from typing import Any, Final

import polars as pl

__all__ = [
    "BBO",
    "BOOK",
    "BOOK_LEVELS",
    "COLLECTOR_DAY_TABLES",
    "COVERAGE",
    "DIVERGENCES",
    "FILLS",
    "FUNDING",
    "GAPS",
    "LEADERBOARD",
    "META",
    "PROXY",
    "RAW_LEADERBOARD",
    "ROLES",
    "SCHEMAS",
    "TRADES",
]

#: Níveis por lado do livro na assinatura rápida (documentação da Hyperliquid, l2Book
#: com ``fast``: "5 levels").
BOOK_LEVELS: Final = 5

RAW_LEADERBOARD: Final = "raw/leaderboard"  # partição: instante do snapshot
LEADERBOARD: Final = "leaderboard"  # partição: instante do snapshot
META: Final = "meta"  # partição: instante da coleta
ROLES: Final = "roles"  # partição: instante da coleta
FILLS: Final = "fills"  # partição: endereço
COVERAGE: Final = "coverage"  # partição: endereço
DIVERGENCES: Final = "divergences"  # partição: endereço
FUNDING: Final = "funding"  # partição: ativo
PROXY: Final = "proxy"  # partição: ativo, dia UTC
BBO: Final = "bbo"  # partição: ativo, dia UTC de recebimento
BOOK: Final = "book"  # partição: ativo, dia UTC de recebimento
TRADES: Final = "trades"  # partição: ativo, dia UTC de recebimento
GAPS: Final = "gaps"  # partição: ativo

#: Tabelas do coletor particionadas pelo dia de recebimento (design 1.2 §3.2).
COLLECTOR_DAY_TABLES: Final = (BBO, BOOK, TRADES)

_COLLECTOR_TIMES: Final = {"time_ms": pl.Int64, "recv_ms": pl.Int64, "conn_ms": pl.Int64}

SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    RAW_LEADERBOARD: {"snapshot_ms": pl.Int64, "sha256": pl.String, "body": pl.Binary},
    LEADERBOARD: {"address": pl.String, "account_value": pl.Float64},
    META: {"coin": pl.String, "sz_decimals": pl.Int64},
    ROLES: {"address": pl.String, "role": pl.String},
    FILLS: {
        "seq": pl.Int64,
        "time_ms": pl.Int64,
        "coin": pl.String,
        "kind": pl.String,
        "px": pl.Float64,
        "sz": pl.Float64,
        "side": pl.String,
        "start_position": pl.Float64,
        "dir": pl.String,
        "crossed": pl.Boolean,
        "closed_pnl": pl.Float64,
        "fee": pl.Float64,
        "tid": pl.Int64,
        "oid": pl.Int64,
        "twap_id": pl.Int64,
        "liquidated_user": pl.String,
    },
    COVERAGE: {
        "start_ms": pl.Int64,
        "end_ms": pl.Int64,
        "ingested_at_ms": pl.Int64,
        "n_fills": pl.Int64,
        "status": pl.String,
        "content_hash": pl.String,
    },
    DIVERGENCES: {
        "time_ms": pl.Int64,
        "tid": pl.Int64,
        "field": pl.String,
        "old": pl.String,
        "new": pl.String,
        "detected_at_ms": pl.Int64,
    },
    FUNDING: {"hour_ms": pl.Int64, "time_ms": pl.Int64, "rate": pl.Float64, "premium": pl.Float64},
    PROXY: {
        "second": pl.Int64,
        "low": pl.Float64,
        "high": pl.Float64,
        "last": pl.Float64,
        "n_trades": pl.Int64,
    },
    BBO: {
        **_COLLECTOR_TIMES,
        "bid_px": pl.Float64,
        "bid_sz": pl.Float64,
        "ask_px": pl.Float64,
        "ask_sz": pl.Float64,
    },
    BOOK: {
        **_COLLECTOR_TIMES,
        **{
            f"{side}_{kind}_{level}": pl.Float64
            for side in ("bid", "ask")
            for level in range(1, BOOK_LEVELS + 1)
            for kind in ("px", "sz")
        },
    },
    TRADES: {
        **_COLLECTOR_TIMES,
        "px": pl.Float64,
        "sz": pl.Float64,
        "side": pl.String,
        "buyer": pl.String,
        "seller": pl.String,
        "tid": pl.Int64,
    },
    GAPS: {"start_ms": pl.Int64, "end_ms": pl.Int64, "reason": pl.String},
}
