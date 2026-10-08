"""Leitura por janela das tabelas (design 1.2 §3.2): ``ParquetRepository``.

As tabelas do coletor são particionadas pelo dia UTC de recebimento e lidas pelo instante
da corretora. Os casos usam o dia ``DAY`` = 20.732 (2026-10-06), que começa em
``D0`` = 20.732 x 86.400.000 = 1.791.244.800.000 ms, e o seguinte, que começa em
``D1`` = ``D0`` + 86.400.000.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
``copylab.storage.repository``:

- ``_exchange_time`` sem o dia anterior (``utc_day(start) - 1`` trocado por
  ``utc_day(start)``): falhou
  ``test_collector_tables_read_by_exchange_time_open_previous_day_partition``, que perde
  a linha gravada na partição do dia anterior pelo relógio atrasado.
- ``_exchange_time`` sem o dia seguinte (``+ 1`` removido): falhou
  ``test_collector_tables_read_by_exchange_time_open_next_day_partition``.
- ``_exchange_time`` filtrando por ``recv_ms`` em vez de ``time_ms``: falharam os dois.
- ``gaps`` filtrando só lacunas que começam dentro do intervalo: falhou
  ``test_gaps_overlapping_the_interval_are_returned_in_exchange_time``.
"""

from pathlib import Path

import polars as pl
import pytest

from copylab.storage import ParquetRepository, ParquetStore, Span
from copylab.storage.tables import BBO, BOOK, GAPS, SCHEMAS, TRADES
from copylab.timeutil import MS_PER_DAY, Ms

DAY = 20_732
D0 = 1_791_244_800_000
D1 = D0 + MS_PER_DAY


def collector_row(table: str, time_ms: int, recv_ms: int) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SCHEMAS[table])
    row.update(time_ms=time_ms, recv_ms=recv_ms, conn_ms=D0 - 60_000)
    if table == TRADES:
        row.update(px=100.0, sz=1.0, side="B", buyer="0xa", seller="0xb", tid=time_ms)
    else:
        row.update({name: 1.0 for name, dtype in SCHEMAS[table].items() if dtype == pl.Float64})
    return row


def write_day(
    store: ParquetStore, table: str, coin: str, day: int, rows: list[dict[str, object]]
) -> None:
    frame = pl.DataFrame(rows, schema=SCHEMAS[table], orient="row")
    span = Span(Ms(day * MS_PER_DAY), Ms((day + 1) * MS_PER_DAY))
    store.write(table, (coin, str(day)), frame, span=span, instant="recv_ms")


@pytest.mark.unit
@pytest.mark.parametrize("table", [BBO, BOOK, TRADES])
def test_collector_tables_read_by_exchange_time_open_previous_day_partition(
    tmp_path: Path, table: str
) -> None:
    # A linha da corretora em D1 + 100 ms chegou quando o relógio do coletor, atrasado
    # 500 ms, marcava D1 - 400 ms: pelo dia de recebimento, ela mora na partição de DAY.
    # A leitura de [D1, D1 + 1 h) tem de achá-la; a linha de D0 + 5 s, não.
    store = ParquetStore(tmp_path)
    late = collector_row(table, D1 + 100, D1 - 400)
    write_day(store, table, "BTC", DAY, [collector_row(table, D0 + 5_000, D0 + 4_500), late])
    write_day(store, table, "BTC", DAY + 1, [collector_row(table, D1 + 200, D1 + 50)])
    repo = ParquetRepository(store)

    read = getattr(repo, table)("BTC", Ms(D1), Ms(D1 + 3_600_000))

    assert read.get_column("time_ms").to_list() == [D1 + 100, D1 + 200]
    assert read.get_column("recv_ms").to_list() == [D1 - 400, D1 + 50]


@pytest.mark.unit
@pytest.mark.parametrize("table", [BBO, BOOK, TRADES])
def test_collector_tables_read_by_exchange_time_open_next_day_partition(
    tmp_path: Path, table: str
) -> None:
    # Relógio adiantado: a linha da corretora em D1 - 100 ms foi recebida em D1 + 300 ms
    # pelo relógio local e mora na partição de DAY + 1. A leitura do último minuto de DAY,
    # [D1 - 60 s, D1), tem de achá-la.
    store = ParquetStore(tmp_path)
    write_day(store, table, "BTC", DAY, [collector_row(table, D1 - 30_000, D1 - 29_700)])
    write_day(store, table, "BTC", DAY + 1, [collector_row(table, D1 - 100, D1 + 300)])
    repo = ParquetRepository(store)

    read = getattr(repo, table)("BTC", Ms(D1 - 60_000), Ms(D1))

    assert read.get_column("time_ms").to_list() == [D1 - 30_000, D1 - 100]


@pytest.mark.unit
def test_collector_read_without_partitions_is_empty_with_the_table_columns(
    tmp_path: Path,
) -> None:
    repo = ParquetRepository(ParquetStore(tmp_path))
    read = repo.bbo("ETH", Ms(D0), Ms(D1))
    assert read.height == 0
    assert read.schema == pl.Schema(SCHEMAS[BBO])


@pytest.mark.unit
def test_gaps_overlapping_the_interval_are_returned_in_exchange_time(tmp_path: Path) -> None:
    # Lacunas no relógio da corretora: [D1 - 20 s, D1 + 10 s) atravessa a meia-noite e
    # se sobrepõe a [D1, D1 + 1 h); [D0, D0 + 15 s) não; [D1 + 1 h, ...) começa no fim
    # exclusivo e não entra.
    store = ParquetStore(tmp_path)
    frame = pl.DataFrame(
        [
            (D0, D0 + 15_000, "silence"),
            (D1 - 20_000, D1 + 10_000, "disconnect"),
            (D1 + 3_600_000, D1 + 3_700_000, "silence"),
        ],
        schema=SCHEMAS[GAPS],
        orient="row",
    )
    store.write(GAPS, ("BTC",), frame, span=Span(Ms(0), Ms(2**62)), instant="start_ms")

    read = ParquetRepository(store).gaps("BTC", Ms(D1), Ms(D1 + 3_600_000))

    assert read.rows() == [(D1 - 20_000, D1 + 10_000, "disconnect")]
