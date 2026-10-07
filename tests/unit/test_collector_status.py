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
from copylab.storage.segments import EVENTS, Record, SegmentStore
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
