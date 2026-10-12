"""Status do coletor: cobertura, latência e projeção de disco (T-013).

Mesmo dia e mesmas convenções de `test_collector_compact.py`: `D0` = 2026-10-06T00:00Z =
1.791.244.800.000 ms, dia 20.732, silêncio máximo de 10 s.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
`copylab.collector.status`:

- sem a lacuna em curso (o silêncio desde a última mensagem): falhou
  `test_status_reports_gap_free_fraction_per_asset` (cobertura 0,565 em vez de 0,275).
- `recent` sem a conexão viva do dia compactado (`live_conn=None`): na primeira tentativa
  o teste não caiu, porque o cenário só tinha reconexão, cujo retrato é descartado de
  qualquer jeito. Entrou o caso de ETH, que continua a mesma conexão; com ele, o teste cai
  (a mensagem de 5 s vira retrato, e a cobertura de ETH vai a zero).
- `nearest_rank` com `round` no lugar de `ceil`: falhou
  `test_nearest_rank_has_no_interpolation`. O teste de latência não cai, porque com 100
  valores `round` e `ceil` coincidem; o teste direto existe por isso.
- projeção sem o horizonte (`projection_days` fora da conta): falhou
  `test_status_projects_disk_usage_against_budget`.
"""

import json
from pathlib import Path

import pytest

from copylab.collector.compact import Compactor
from copylab.collector.status import CollectorStatus, collector_status, nearest_rank
from copylab.storage import ParquetStore
from copylab.storage.segments import EVENTS, Record, SegmentRef, SegmentStore, SegmentWriter
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms

DAY = 20_732
D0 = 1_791_244_800_000
SILENCE = 10_000


def book(coin: str, t: int) -> bytes:
    levels = [[{"px": "100.0", "sz": "1.0", "n": 1}], [{"px": "101.0", "sz": "1.0", "n": 1}]]
    data = {"coin": coin, "time": t, "levels": levels, "fast": True}
    return json.dumps({"channel": "l2Book", "data": data}).encode()


def trade(coin: str, t: int, tid: int) -> bytes:
    data = [
        {
            "coin": coin,
            "side": "A",
            "px": "100.0",
            "sz": "1.0",
            "time": t,
            "hash": "0x00",
            "tid": tid,
            "users": ["0xaa", "0xbb"],
        }
    ]
    return json.dumps({"channel": "trades", "data": data}).encode()


def segment(
    store: SegmentStore,
    coin: str,
    channel: str,
    records: list[tuple[int, int, bytes]],
    *,
    close: bool = True,
) -> None:
    hour = Ms(records[0][0] // MS_PER_HOUR * MS_PER_HOUR)
    writer = store.open_writer(coin, channel, hour, Ms(records[0][0]))
    for recv, conn, raw in records:
        writer.append(Record(Ms(recv), Ms(conn), raw))
    if close:
        writer.close()
    else:
        writer.flush()


def status(tmp_path: Path, now: int, budget: int = 30 * 10**9) -> CollectorStatus:
    return collector_status(
        SegmentStore(tmp_path),
        ParquetStore(tmp_path),
        ["BTC", "ETH", "SOL"],
        now_ms=Ms(now),
        max_silence_ms=SILENCE,
        projection_days=45,
        budget_bytes=budget,
    )


@pytest.mark.unit
def test_status_reports_gap_free_fraction_per_asset(tmp_path: Path) -> None:
    """RF-COL-02 CA-02.3. BTC desde o primeiro livro, D0 + 1 s, até agora, D0 + 70 s.

    Já compactado (conexão a, aberta em D0 + 100 ms): livro em 1 s, 11 s e 31 s.
      lacuna 1, silêncio: [11 s, 31 s] = 20.000 ms.
    Ainda em segmento aberto (conexão b, reconexão em D0 + 40 s): retrato descartado,
    livro em 41 s e 50 s.
      lacuna 2, desconexão: [31 s, 41 s] = 10.000 ms. De 41 s a 50 s, 9 s: não é lacuna.
    Agora, D0 + 70 s: 20 s sem livro desde 50 s, lacuna em curso [50 s, 70 s] = 20.000 ms.

    Tempo desde o início: 70.000 - 1.000 = 69.000 ms. Lacunas: 50.000 ms.
    Cobertura: 1 - 50.000 / 69.000 = 19.000 / 69.000 = 0,27536...
    ETH continua na mesma conexão do trecho compactado para o segmento (conexão c, aberta
    em D0 + 100 ms): livro em 1 s, já compactado, e em 5 s e 14 s, ainda em segmento. A
    mensagem de 5 s não é retrato: a conexão já estava viva. Sem lacuna até 14 s; lacuna em
    curso [14 s, 70 s] = 56.000 ms. Cobertura: 1 - 56.000 / 69.000 = 13.000 / 69.000.
    SOL nunca gravou: cobertura ausente, e não zero inventado.
    """
    segments, tables = SegmentStore(tmp_path), ParquetStore(tmp_path)
    a, b = D0 + 100, D0 + 40_000
    segment(
        segments,
        "BTC",
        "book",
        [(a + 5, a, book("BTC", a))]
        + [(t + 300, a, book("BTC", t)) for t in (D0 + 1_000, D0 + 11_000, D0 + 31_000)],
    )
    c = D0 + 100
    segment(
        segments,
        "ETH",
        "book",
        [(c + 5, c, book("ETH", c)), (D0 + 1_300, c, book("ETH", D0 + 1_000))],
    )
    Compactor(segments, tables, SILENCE).compact_day(DAY)
    segment(
        segments,
        "ETH",
        "book",
        [(t + 300, c, book("ETH", t)) for t in (D0 + 5_000, D0 + 14_000)],
        close=False,
    )
    segment(
        segments,
        "BTC",
        "book",
        [(b + 5, b, book("BTC", b))]
        + [(t + 300, b, book("BTC", t)) for t in (D0 + 41_000, D0 + 50_000)],
        close=False,
    )

    result = status(tmp_path, D0 + 70_000)
    btc, eth, sol = result.assets
    assert btc.since_ms == D0 + 1_000
    assert btc.last_book_ms == D0 + 50_000
    assert btc.gap_count == 3
    assert btc.gap_ms == 50_000
    assert btc.covered_fraction == pytest.approx(19_000 / 69_000)
    assert eth.since_ms == D0 + 1_000
    assert eth.gap_ms == 56_000
    assert eth.covered_fraction == pytest.approx(13_000 / 69_000)
    assert sol.covered_fraction is None
    assert sol.since_ms is None


@pytest.mark.unit
def test_latency_report_gives_median_p95_p99(tmp_path: Path) -> None:
    """RF-COL-03 CA-03.2. Cem negócios de BTC com atrasos de 1 a 100 ms: 60 compactados,
    40 ainda em segmento. O retrato da assinatura, com 99.999 ms de idade, não conta.

    Posto mais próximo, n = 100: mediana é o 50º valor (50 ms), p95 o 95º (95 ms), p99 o
    99º (99 ms).
    """
    segments, tables = SegmentStore(tmp_path), ParquetStore(tmp_path)
    conn = D0 + 100
    old = [(conn + 5, conn, trade("BTC", conn + 5 - 99_999, 0))]
    first = [(D0 + 1_000 * i + i, conn, trade("BTC", D0 + 1_000 * i, i)) for i in range(1, 61)]
    segment(segments, "BTC", "trades", old + first)
    Compactor(segments, tables, SILENCE).compact_day(DAY)
    later = [(D0 + 1_000 * i + i, conn, trade("BTC", D0 + 1_000 * i, i)) for i in range(61, 101)]
    segment(segments, "BTC", "trades", later)

    result = status(tmp_path, D0 + 200_000)
    btc = result.assets[0]
    for latency in (btc.latency, result.latency):
        assert latency is not None
        assert (latency.count, latency.p50_ms, latency.p95_ms, latency.p99_ms) == (100, 50, 95, 99)


@pytest.mark.unit
def test_nearest_rank_has_no_interpolation() -> None:
    values = [10, 20, 30, 40]
    # p = 0,5: ceil(2) = 2º valor. p = 0,51: ceil(2,04) = 3º. p = 1: o último.
    assert (nearest_rank(values, 0.5), nearest_rank(values, 0.51), nearest_rank(values, 1)) == (
        20,
        30,
        40,
    )
    assert nearest_rank([7], 0.01) == 7


@pytest.mark.unit
def test_status_projects_disk_usage_against_budget(tmp_path: Path) -> None:
    """RF-COL-04 CA-04.2. Gravação começou em D0 (primeiro evento); agora, D0 + 1 h.

    Projeção para 45 dias: bytes usados * (45 * 24 h) / 1 h = bytes * 1.080.
    Orçamento de 1.000 vezes os bytes: estoura. De 2.000 vezes: cabe.
    """
    segments = SegmentStore(tmp_path)
    segment(segments, *EVENTS, [(D0, D0, b'{"event":"connect"}')])
    segment(segments, "BTC", "bbo", [(D0 + 5, D0, b"{}")])
    used = sum(r.path.stat().st_size for r in segments.segments(include_open=True))

    tight = status(tmp_path, D0 + MS_PER_HOUR, budget=used * 1_000)
    assert tight.started_ms == D0
    assert tight.disk_bytes == used
    assert tight.projected_bytes == used * 1_080
    assert tight.within_budget is False
    assert status(tmp_path, D0 + MS_PER_HOUR, budget=used * 2_000).within_budget is True
    assert 45 * MS_PER_DAY // MS_PER_HOUR == 1_080


@pytest.mark.unit
def test_status_of_an_empty_data_dir_has_no_projection(tmp_path: Path) -> None:
    result = status(tmp_path, D0)
    assert result.projected_bytes is None
    assert result.within_budget is None
    assert result.latency is None


# ─── Leitura enquanto o gravador roda ────────────────────────────────────────


class StaleListing(SegmentStore):
    """Um armazenamento cuja listagem foi tirada antes de o gravador mexer nos arquivos.

    É o que o status vê no Windows: lista os segmentos, e o gravador fecha (renomeia) ou a
    compactação apaga um deles antes de a leitura chegar lá.
    """

    def __init__(self, data_dir: Path, listing: list[SegmentRef]) -> None:
        super().__init__(data_dir)
        self._listing = listing

    def segments(self, *, include_open: bool = False) -> list[SegmentRef]:
        return [r for r in self._listing if include_open or r.closed]


def open_segment(
    store: SegmentStore, coin: str, records: list[tuple[int, int, bytes]]
) -> SegmentWriter:
    hour = Ms(records[0][0] // MS_PER_HOUR * MS_PER_HOUR)
    writer = store.open_writer(coin, "book", hour, Ms(records[0][0]))
    for recv, conn, raw in records:
        writer.append(Record(Ms(recv), Ms(conn), raw))
    writer.flush()
    return writer


@pytest.mark.unit
def test_status_survives_a_segment_renamed_or_deleted_between_listing_and_reading(
    tmp_path: Path,
) -> None:
    """Um segmento listado em escrita e fechado antes da leitura é relido pelo nome novo; um
    apagado nesse meio tempo é pulado. Nunca `FileNotFoundError`.

    BTC, conexão a aberta em D0 + 100: o retrato (primeira mensagem) é descartado e o livro
    vem em D0 + 1 s, 5 s e 9 s. Agora, D0 + 10 s.
      desde o primeiro livro, D0 + 1 s: 9.000 ms de tempo;
      intervalos de 4 s, abaixo do silêncio de 10 s: nenhuma lacuna;
      último livro em 9 s, 1 s de silêncio: não é lacuna em curso.
    Cobertura: 1 - 0 / 9.000 = 1.
    ETH gravou um segmento, que foi apagado depois da listagem: sem livro, cobertura
    ausente.

    Mutação registrada: trocar `read_live` por `read` em `_Reader.book_points` faz este
    teste cair com `FileNotFoundError` em BTC, que é o defeito visto no Windows.
    """
    store = SegmentStore(tmp_path)
    a = D0 + 100
    btc = open_segment(
        store,
        "BTC",
        [(a + 5, a, book("BTC", a))]
        + [(D0 + t + 300, a, book("BTC", D0 + t)) for t in (1_000, 5_000, 9_000)],
    )
    eth = open_segment(store, "ETH", [(a + 5, a, book("ETH", a))])
    listing = store.segments(include_open=True)
    assert [r.closed for r in listing] == [False, False]

    btc.close()  # renomeado depois da listagem
    store.delete(eth.close())  # fechado e apagado depois da listagem

    result = collector_status(
        StaleListing(tmp_path, listing),
        ParquetStore(tmp_path),
        ["BTC", "ETH"],
        now_ms=Ms(D0 + 10_000),
        max_silence_ms=SILENCE,
        projection_days=45,
        budget_bytes=30 * 10**9,
    )
    btc_status, eth_status = result.assets
    assert btc_status.since_ms == D0 + 1_000
    assert btc_status.gap_count == 0
    assert btc_status.covered_fraction == pytest.approx(1.0)
    assert eth_status.covered_fraction is None


@pytest.mark.unit
def test_disk_bytes_counts_a_closed_segment_by_its_new_name_and_skips_a_deleted_one(
    tmp_path: Path,
) -> None:
    """Soma estável com a listagem velha: BTC fechou (conta pelo nome de fechado) e ETH foi
    apagado (não conta). Valor esperado: o tamanho do arquivo de BTC em disco agora.

    Mutação registrada: somar `ref.path.stat()` direto, sem tentar o nome de fechado, faz
    este teste cair com `FileNotFoundError`."""
    store = SegmentStore(tmp_path)
    a = D0 + 100
    btc = open_segment(store, "BTC", [(a + 5, a, book("BTC", a))])
    eth = open_segment(store, "ETH", [(a + 5, a, book("ETH", a))])
    listing = store.segments(include_open=True)
    closed_btc = btc.close()
    closed_eth = eth.close()
    expected = closed_btc.path.stat().st_size
    store.delete(closed_eth)
    assert StaleListing(tmp_path, listing).disk_bytes() == expected


# ─── Cobertura por dia UTC ───────────────────────────────────────────────────

H = MS_PER_HOUR
LONG_SILENCE = 100 * H  # só reconexão faz lacuna nestes cenários


def day_status(tmp_path: Path, now: int) -> CollectorStatus:
    return collector_status(
        SegmentStore(tmp_path),
        ParquetStore(tmp_path),
        ["BTC"],
        now_ms=Ms(now),
        max_silence_ms=LONG_SILENCE,
        projection_days=45,
        budget_bytes=30 * 10**9,
    )


def build_three_days(tmp_path: Path) -> None:
    """BTC começa a gravar às 18 h do primeiro dia e tem uma desconexão de 1 h nele.

    Dia D0 (20.732), conexão a aberta às 18 h: retrato descartado, livro em 18 h + 1 s e
    às 20 h e 22 h. Conexão b aberta às 22,5 h: retrato descartado, livro às 23 h.
    Dia D0 + 1 dia, conexão b: livro às 0,5 h, 5 h, 10 h, 15 h, 20 h e 23,5 h.
    Dia D0 + 2 dias, ainda sem compactar: livro às 1 h, 3 h e 5 h.
    """
    segments, tables = SegmentStore(tmp_path), ParquetStore(tmp_path)
    a, b = D0 + 18 * H, D0 + 22 * H + H // 2
    segment(
        segments,
        "BTC",
        "book",
        [(a, a, book("BTC", a))]
        + [(t + 300, a, book("BTC", t)) for t in (a + 1_000, D0 + 20 * H, D0 + 22 * H)],
    )
    segment(
        segments,
        "BTC",
        "book",
        [(b, b, book("BTC", b)), (D0 + 23 * H + 300, b, book("BTC", D0 + 23 * H))],
    )
    d1 = D0 + MS_PER_DAY
    hours = (H // 2, 5 * H, 10 * H, 15 * H, 20 * H, 23 * H + H // 2)
    segment(segments, "BTC", "book", [(d1 + h + 300, b, book("BTC", d1 + h)) for h in hours])
    compactor = Compactor(segments, tables, LONG_SILENCE)
    compactor.compact_day(DAY)
    compactor.compact_day(DAY + 1)
    d2 = D0 + 2 * MS_PER_DAY
    segment(
        segments,
        "BTC",
        "book",
        [(d2 + h + 300, b, book("BTC", d2 + h)) for h in (H, 3 * H, 5 * H)],
        close=False,
    )


@pytest.mark.unit
def test_status_reports_coverage_per_utc_day_for_each_asset(tmp_path: Path) -> None:
    """RF-COL-05 CA-05.2: o número que a medida de custo usa. Agora: D0 + 2 dias + 6 h.

    Primeiro livro, D0 + 18 h + 1 s: `since`. Dia D0, encerrado, 24 h = 86.400.000 ms.
      lacuna: o livro em 22 h (conexão a) até o de 23 h (conexão b): 1 h = 3.600.000 ms.
      antes do primeiro livro: 18 h + 1 s = 64.801.000 ms, que conta como não coberto.
      cobertura: 1 - (3.600.000 + 64.801.000) / 86.400.000 = 17.999.000 / 86.400.000.
    Dia D0 + 1: a conexão b segue viva do dia anterior. Livro de 6 em 6 h no máximo, e o
    silêncio máximo do cenário é de 100 h: nenhuma lacuna, cobertura 1.
    Dia D0 + 2, em curso, 6 h = 21.600.000 ms decorridas: livro em 1 h, 3 h e 5 h, a última
    1 h antes de agora. Sem lacuna, cobertura 1 sobre as 6 h, e o dia vem como incompleto.

    Mutação registrada: contar só o tempo depois do primeiro livro no primeiro dia (sem o
    `unrecorded_ms`) faz o primeiro dia sair com 1 - 3.600.000 / 22.199.000 = 0,838 em vez
    de 0,208, e o teste cai.
    """
    build_three_days(tmp_path)
    now = D0 + 2 * MS_PER_DAY + 6 * H
    btc = day_status(tmp_path, now).assets[0]
    first, second, third = btc.daily
    assert [d.day for d in btc.daily] == [DAY, DAY + 1, DAY + 2]
    assert [d.complete for d in btc.daily] == [True, True, False]
    assert first.observed_ms == MS_PER_DAY
    assert first.gap_ms == 3_600_000
    assert first.unrecorded_ms == 64_801_000
    assert first.covered_fraction == pytest.approx(17_999_000 / 86_400_000)
    assert (second.gap_ms, second.unrecorded_ms) == (0, 0)
    assert second.covered_fraction == pytest.approx(1.0)
    assert third.observed_ms == 6 * H
    assert third.covered_fraction == pytest.approx(1.0)


@pytest.mark.unit
def test_status_over_compacted_tables_equals_status_over_the_same_raw_segments(
    tmp_path: Path,
) -> None:
    """O status lê tabelas para os dias compactados e segmentos para o dia aberto, e as duas
    leituras dão o mesmo número para o mesmo dado: compactar não muda o que o status diz.

    BTC, conexão a (aberta em D0 + 100): retrato descartado, livro em 1 s, 5 s, 20 s
    (lacuna de 15 s, acima do silêncio de 10 s), conexão b (aberta em D0 + 30 s), retrato
    descartado, livro em 31 s e 33 s. Negócios com atraso de recebimento de 100, 200 e
    300 ms na conexão a e de 400 ms depois do retrato da conexão b.

    Posto mais próximo, n = 4 atrasos (100, 200, 300, 400): p50 = 2º = 200, p95 = 4º = 400,
    p99 = 4º = 400. Lacunas: [5 s, 20 s] silêncio e [20 s, 31 s] desconexão.

    Mutação registrada: em `_Reader.book_points`, não descartar a primeira mensagem de cada
    conexão (o retrato) faz este teste cair, junto com os dois de cobertura acima, porque o
    retrato entra como ponto do livro e muda lacunas e `since`. O mesmo em
    `_Reader.trade_delays`: o retrato dos negócios entra com atraso de 10 ms e muda a
    mediana e a contagem (cai este teste).
    """
    now = D0 + 40_000
    a, b = D0 + 100, D0 + 30_000

    def fill(store: SegmentStore) -> None:
        segment(
            store,
            "BTC",
            "book",
            [(a, a, book("BTC", a))]
            + [(t + 300, a, book("BTC", t)) for t in (D0 + 1_000, D0 + 5_000, D0 + 20_000)]
            + [(b, b, book("BTC", b))]
            + [(t + 300, b, book("BTC", t)) for t in (D0 + 31_000, D0 + 33_000)],
        )
        segment(
            store,
            "BTC",
            "trades",
            [(a + 5, a, trade("BTC", a - 5, 0))]
            + [
                (D0 + 2_000 + d, a, trade("BTC", D0 + 2_000, i))
                for i, d in enumerate((100, 200, 300))
            ]
            + [
                (b + 5, b, trade("BTC", b - 5, 9)),
                (D0 + 32_000 + 400, b, trade("BTC", D0 + 32_000, 10)),
            ],
        )

    raw_dir, table_dir = tmp_path / "raw", tmp_path / "tables"
    fill(SegmentStore(raw_dir))
    fill(SegmentStore(table_dir))
    Compactor(SegmentStore(table_dir), ParquetStore(table_dir), SILENCE).compact_day(DAY)

    def read(root: Path) -> CollectorStatus:
        return collector_status(
            SegmentStore(root),
            ParquetStore(root),
            ["BTC"],
            now_ms=Ms(now),
            max_silence_ms=SILENCE,
            projection_days=45,
            budget_bytes=30 * 10**9,
        )

    from_segments, from_tables = read(raw_dir).assets[0], read(table_dir).assets[0]
    assert from_segments == from_tables
    assert (from_tables.gap_count, from_tables.gap_ms) == (2, 26_000)
    latency = from_tables.latency
    assert latency is not None
    assert (latency.count, latency.p50_ms, latency.p95_ms, latency.p99_ms) == (4, 200, 400, 400)
