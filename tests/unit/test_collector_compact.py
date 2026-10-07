"""Compactação: tabelas bbo, book e trades, e a tabela de lacunas (T-012).

Os segmentos são montados à mão, com instantes redondos. O dia é 2026-10-06,
`DAY` = 20.732 (2026-10-06 é 35 dias depois de 2026-09-01, dia 20.697), que começa em
`D0` = 20.732 * 86.400.000 = 1.791.244.800.000 ms. O instante da corretora vem antes do
de recebimento, como no dado real (300 ms de latência aqui).

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
`copylab.collector.compact`:

- `find_gaps` com `>=` no lugar de `>`: falhou
  `test_book_silence_over_10s_is_gap_and_trades_silence_is_not` (10 s exatos viraram
  lacuna).
- `find_gaps` sem o caso de desconexão: falharam `test_gaps_are_recorded_in_exchange_time`,
  `test_gap_across_midnight_uses_the_previous_day_row` e o teste direto de `find_gaps`.
- `find_gaps` registrando os instantes de recebimento (`recv_ms`) em vez dos da corretora:
  falharam `test_gaps_are_recorded_in_exchange_time` e os outros três de lacuna.
- `rows_from_segments` sem descartar a primeira mensagem: falharam
  `test_first_message_of_each_subscription_is_dropped` e outros quatro, cujas contas
  supõem o descarte.
"""

import json
from pathlib import Path

import polars as pl
import pytest

from copylab.collector.compact import BookPoint, Compactor, Gap, find_gaps
from copylab.exceptions import DataError
from copylab.storage import ParquetStore
from copylab.storage.segments import EVENTS, Record, SegmentStore
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms

DAY = 20_732
D0 = 1_791_244_800_000
LATENCY = 300
SILENCE = 10_000
BUYER = "0x1e1e5046b07be9a2d0f5223a723bf49e23b5ef73"
SELLER = "0xf58b673c1633ccef0ac58263cdc95ed80f817fc7"


def bbo(coin: str, t: int, bid: float = 100.0, ask: float = 101.0) -> bytes:
    data = {
        "coin": coin,
        "time": t,
        "bbo": [{"px": str(bid), "sz": "1.5", "n": 3}, {"px": str(ask), "sz": "2.5", "n": 4}],
    }
    return json.dumps({"channel": "bbo", "data": data}).encode()


def book(coin: str, t: int, levels: int = 5) -> bytes:
    bids = [{"px": str(100.0 - i), "sz": str(1.0 + i), "n": 1} for i in range(levels)]
    asks = [{"px": str(101.0 + i), "sz": str(2.0 + i), "n": 1} for i in range(levels)]
    data = {"coin": coin, "time": t, "levels": [bids, asks], "fast": True}
    return json.dumps({"channel": "l2Book", "data": data}).encode()


def trades(coin: str, *items: tuple[int, float, int]) -> bytes:
    data = [
        {
            "coin": coin,
            "side": "B",
            "px": str(px),
            "sz": "0.5",
            "time": t,
            "hash": "0x00",
            "tid": tid,
            "users": [BUYER, SELLER],
        }
        for t, px, tid in items
    ]
    return json.dumps({"channel": "trades", "data": data}).encode()


def write_segment(
    store: SegmentStore, coin: str, channel: str, records: list[tuple[int, int, bytes]]
) -> None:
    """Um segmento fechado com (instante da corretora + latência, conexão, mensagem)."""
    hour = Ms(records[0][0] // MS_PER_HOUR * MS_PER_HOUR)
    assert all(r[0] // MS_PER_HOUR * MS_PER_HOUR == hour for r in records), "uma hora só"
    writer = store.open_writer(coin, channel, hour, Ms(records[0][0]))
    for recv, conn, raw in records:
        writer.append(Record(Ms(recv), Ms(conn), raw))
    writer.close()


def book_records(coin: str, conn: int, times: list[int]) -> list[tuple[int, int, bytes]]:
    return [(t + LATENCY, conn, book(coin, t)) for t in times]


def make(tmp_path: Path) -> tuple[SegmentStore, ParquetStore, Compactor]:
    segments = SegmentStore(tmp_path)
    tables = ParquetStore(tmp_path)
    return segments, tables, Compactor(segments, tables, SILENCE)


# ─── Regra de lacuna ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_book_silence_over_10s_is_gap_and_trades_silence_is_not(tmp_path: Path) -> None:
    """RF-COL-02 CA-02.2. Conexão aberta em D0 + 100 ms; livro de BTC em 1 s, 11 s e
    21,001 s depois de D0, depois do retrato (descartado).

    1 s -> 11 s: exatamente 10 s, não é lacuna (o limiar inclui o valor, design §3.6).
    11 s -> 21,001 s: 10,001 s, é lacuna [D0 + 11.000, D0 + 21.001], motivo silêncio.
    Negócios de BTC em 1 s e 26 s: 25 s de silêncio que não fazem lacuna nenhuma.
    """
    segments, tables, compactor = make(tmp_path)
    conn = D0 + 100
    write_segment(
        segments,
        "BTC",
        "book",
        [
            (conn + 5, conn, book("BTC", conn)),
            *book_records("BTC", conn, [D0 + 1_000, D0 + 11_000, D0 + 21_001]),
        ],
    )
    write_segment(
        segments,
        "BTC",
        "trades",
        [
            (conn + 5, conn, trades("BTC", (conn - 40_000, 1.0, 1))),  # retrato, descartado
            (D0 + 1_000 + LATENCY, conn, trades("BTC", (D0 + 1_000, 1.0, 2))),
            (D0 + 26_000 + LATENCY, conn, trades("BTC", (D0 + 26_000, 1.0, 3))),
        ],
    )
    report = compactor.compact_day(DAY)

    assert report.gaps["BTC"] == [Gap(D0 + 11_000, D0 + 21_001, "silence")]
    assert tables.read("gaps", ("BTC",)).rows() == [(D0 + 11_000, D0 + 21_001, "silence")]


@pytest.mark.unit
def test_gaps_are_recorded_in_exchange_time(tmp_path: Path) -> None:
    """RF-COL-02 CA-02.1. A lacuna vai do instante da corretora da última mensagem antes
    dela ao da primeira depois, e não dos instantes de recebimento.

    Conexão A (D0 + 100 ms): retrato descartado, livro em D0 + 1 s e D0 + 2 s (corretora),
    recebido 300 ms depois. Conexão B (reconexão, D0 + 3,5 s): retrato descartado, e livro
    em D0 + 5 s. Lacuna: [D0 + 2.000, D0 + 5.000], motivo desconexão, mesmo com só 3 s
    entre as duas mensagens.
    """
    segments, tables, compactor = make(tmp_path)
    a, b = D0 + 100, D0 + 3_500
    write_segment(
        segments,
        "ETH",
        "book",
        [
            (a + 5, a, book("ETH", a)),
            *book_records("ETH", a, [D0 + 1_000, D0 + 2_000]),
            (b + 5, b, book("ETH", b)),
            *book_records("ETH", b, [D0 + 5_000]),
        ],
    )
    compactor.compact_day(DAY)
    assert tables.read("gaps", ("ETH",)).rows() == [(D0 + 2_000, D0 + 5_000, "disconnect")]


@pytest.mark.unit
def test_find_gaps_needs_no_previous_and_uses_it_when_given() -> None:
    p = [BookPoint(100, 400, 1), BookPoint(200, 500, 1)]
    assert find_gaps(p, None, 10) == [Gap(100, 200, "silence")]
    assert find_gaps(p, BookPoint(50, 90, 0), 1_000) == [Gap(50, 100, "disconnect")]
    assert find_gaps([], BookPoint(50, 90, 0), 10) == []


@pytest.mark.unit
def test_gap_across_midnight_uses_the_previous_day_row(tmp_path: Path) -> None:
    """Último livro de BTC às 23:59:58 do dia anterior (conexão A); a conexão cai e a B
    traz o próximo às 00:00:03. A lacuna aparece ao compactar o segundo dia, uma vez só."""
    segments, tables, compactor = make(tmp_path)
    a, b = D0 - 60_000, D0 + 1_000
    write_segment(
        segments, "BTC", "book", [(a + 5, a, book("BTC", a)), *book_records("BTC", a, [D0 - 2_000])]
    )
    compactor.compact_day(DAY - 1)
    write_segment(
        segments, "BTC", "book", [(b + 5, b, book("BTC", b)), *book_records("BTC", b, [D0 + 3_000])]
    )
    compactor.compact_day(DAY)

    assert tables.read("gaps", ("BTC",)).rows() == [(D0 - 2_000, D0 + 3_000, "disconnect")]


# ─── Tabelas ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_trades_are_recorded_with_both_addresses_and_timestamps(tmp_path: Path) -> None:
    """RF-COL-03 CA-03.1. Cada negócio vira uma linha com as duas pontas, o lado agressor,
    preço, tamanho e os dois instantes. Uma mensagem com dois negócios dá duas linhas."""
    segments, tables, compactor = make(tmp_path)
    conn = D0 + 100
    write_segment(
        segments,
        "SOL",
        "trades",
        [
            (conn + 5, conn, trades("SOL", (conn - 9_000, 1.0, 1))),
            (D0 + 700, conn, trades("SOL", (D0 + 400, 150.25, 10), (D0 + 400, 150.5, 11))),
        ],
    )
    compactor.compact_day(DAY)
    frame = tables.read("trades", ("SOL", str(DAY)))
    assert frame.select(
        "time_ms", "recv_ms", "px", "sz", "side", "buyer", "seller", "tid"
    ).rows() == [
        (D0 + 400, D0 + 700, 150.25, 0.5, "B", BUYER, SELLER, 10),
        (D0 + 400, D0 + 700, 150.5, 0.5, "B", BUYER, SELLER, 11),
    ]


@pytest.mark.unit
def test_bbo_and_book_tables_have_both_timestamps_and_five_levels(tmp_path: Path) -> None:
    segments, tables, compactor = make(tmp_path)
    conn = D0 + 100
    write_segment(
        segments,
        "BTC",
        "bbo",
        [(conn + 5, conn, bbo("BTC", conn)), (D0 + 300, conn, bbo("BTC", D0, 99.5, 100.5))],
    )
    write_segment(
        segments,
        "BTC",
        "book",
        [(conn + 5, conn, book("BTC", conn)), (D0 + 300, conn, book("BTC", D0, levels=3))],
    )
    compactor.compact_day(DAY)

    (row,) = tables.read("bbo", ("BTC", str(DAY))).rows(named=True)
    assert row == {
        "time_ms": D0,
        "recv_ms": D0 + 300,
        "conn_ms": conn,
        "bid_px": 99.5,
        "bid_sz": 1.5,
        "ask_px": 100.5,
        "ask_sz": 2.5,
    }
    (level,) = tables.read("book", ("BTC", str(DAY))).rows(named=True)
    # Três níveis por lado: 100, 99, 98 de compra; 101, 102, 103 de venda; o 4º e o 5º vazios.
    assert (level["bid_px_1"], level["bid_px_3"], level["ask_px_3"]) == (100.0, 98.0, 103.0)
    assert (level["bid_sz_1"], level["ask_sz_2"]) == (1.0, 3.0)
    assert level["bid_px_4"] is None and level["ask_sz_5"] is None


@pytest.mark.unit
def test_first_message_of_each_subscription_is_dropped(tmp_path: Path) -> None:
    """Conexão A: 3 mensagens de bbo; reconexão B: 2. Ficam 2 + 1 = 3 linhas."""
    segments, tables, compactor = make(tmp_path)
    a, b = D0 + 1_000, D0 + 9_000
    write_segment(
        segments,
        "BTC",
        "bbo",
        [(a + 5 + i, a, bbo("BTC", a + i)) for i in range(3)]
        + [(b + 5 + i, b, bbo("BTC", b + i)) for i in range(2)],
    )
    report = compactor.compact_day(DAY)
    assert tables.read("bbo", ("BTC", str(DAY)))["time_ms"].to_list() == [a + 1, a + 2, b + 1]
    assert report.dropped_first[("BTC", "bbo")] == 2


@pytest.mark.unit
def test_connection_alive_across_midnight_is_not_dropped_again(tmp_path: Path) -> None:
    """A conexão A abriu no dia anterior e segue viva: a primeira mensagem dela no dia novo
    não é retrato e fica."""
    segments, tables, compactor = make(tmp_path)
    a = D0 - 60_000
    write_segment(
        segments, "BTC", "bbo", [(a + 5, a, bbo("BTC", a)), (a + 10, a, bbo("BTC", a + 1))]
    )
    compactor.compact_day(DAY - 1)
    write_segment(segments, "BTC", "bbo", [(D0 + 5, a, bbo("BTC", D0))])
    compactor.compact_day(DAY)
    assert tables.read("bbo", ("BTC", str(DAY)))["time_ms"].to_list() == [D0]


# ─── Contagens, apagamento e falhas ──────────────────────────────────────────


@pytest.mark.unit
def test_segments_are_deleted_only_after_counts_match_and_events_are_kept(
    tmp_path: Path,
) -> None:
    segments, _, compactor = make(tmp_path)
    conn = D0 + 1_000
    write_segment(
        segments, "BTC", "bbo", [(conn + 5 + i, conn, bbo("BTC", conn + i)) for i in range(3)]
    )
    write_segment(segments, *EVENTS, [(conn, conn, b'{"event":"connect"}')])
    report = compactor.compact_day(DAY)
    assert report.deleted_segments == 1
    assert [(s.coin, s.channel) for s in segments.segments()] == [EVENTS]


@pytest.mark.unit
def test_count_mismatch_keeps_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    segments, _, compactor = make(tmp_path)
    conn = D0 + 1_000
    write_segment(
        segments, "BTC", "bbo", [(conn + 5 + i, conn, bbo("BTC", conn + i)) for i in range(3)]
    )
    real_read = ParquetStore.read

    def lossy(self: ParquetStore, table: str, partition: tuple[str, ...]) -> pl.DataFrame:
        return real_read(self, table, partition).head(1)

    monkeypatch.setattr(ParquetStore, "read", lossy)
    with pytest.raises(DataError, match="Segmentos mantidos"):
        compactor.compact_day(DAY)
    assert len(segments.segments()) == 1


@pytest.mark.unit
def test_unreadable_message_keeps_segments(tmp_path: Path) -> None:
    segments, _, compactor = make(tmp_path)
    conn = D0 + 1_000
    write_segment(
        segments,
        "BTC",
        "bbo",
        [(conn + 5, conn, bbo("BTC", conn)), (conn + 6, conn, b'{"channel":"bbo","data":{}}')],
    )
    with pytest.raises(DataError, match="ilegível"):
        compactor.compact_day(DAY)
    assert len(segments.segments()) == 1


@pytest.mark.unit
def test_compaction_is_idempotent(tmp_path: Path) -> None:
    """Uma queda depois de gravar e antes de apagar: rodar de novo dá as mesmas tabelas."""
    segments, tables, compactor = make(tmp_path)
    conn = D0 + 1_000
    times = [conn, conn + 1_000, conn + 20_000]
    write_segment(segments, "BTC", "book", book_records("BTC", conn, times))
    kept = segments.segments()
    copies = {ref.path: ref.path.read_bytes() for ref in kept}
    compactor.compact_day(DAY)
    first = (tables.read("book", ("BTC", str(DAY))), tables.read("gaps", ("BTC",)))
    for path, data in copies.items():  # os segmentos "sobreviveram"
        path.write_bytes(data)
    compactor.compact_day(DAY)
    assert tables.read("book", ("BTC", str(DAY))).equals(first[0])
    assert tables.read("gaps", ("BTC",)).equals(first[1])


@pytest.mark.unit
def test_pending_days_skip_today_and_days_with_open_segments(tmp_path: Path) -> None:
    segments, _, compactor = make(tmp_path)
    for day in (DAY - 2, DAY - 1, DAY):
        write_segment(segments, "BTC", "bbo", [(day * MS_PER_DAY + 5, 1, bbo("BTC", 1))])
    opened = segments.open_writer("ETH", "book", Ms((DAY - 1) * MS_PER_DAY), Ms(5))
    write_segment(segments, *EVENTS, [((DAY - 3) * MS_PER_DAY, 1, b"{}")])

    assert compactor.pending_days(today=DAY) == [DAY - 2]
    opened.close()
    assert compactor.pending_days(today=DAY) == [DAY - 2, DAY - 1]
