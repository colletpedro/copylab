"""Fills por carteira: paginação, classificação, validação, teto, cobertura, retomada e
reingestão (T-022, T-023; RF-ING-02, RF-ING-07 CA-07.2, RF-ING-08).

O provedor é o falso (``FakeInfo``), que imita a paginação medida na verificação: ordem
crescente de instante, ``startTime`` e ``endTime`` inclusivos, no máximo ``page_size``
fills por resposta. A janela é ``[W0, W1)``, de 2026-07-01 a 2026-09-01; os instantes dos
fills são ``W0`` mais segundos redondos, para a conta caber de cabeça.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
``copylab.ingestion.fills``:

- Início de página exclusivo (``cursor = times[-1] + 1``): falharam os dois testes de
  paginação, o da recusa de mais de uma página num milissegundo e o do teto (o recomeço
  pulava os fills da fronteira que não tinham cabido na página).
- Deduplicação por conjunto, e não por multiconjunto (``key in remaining``, sem
  decrementar): falhou só o teste dos 300 fills, que tem cópias idênticas atravessando a
  fronteira, e perdeu uma.
- Sem deduplicação: falharam os mesmos quatro da primeira mutação.
- Teto com ``>=`` no lugar de ``>``: falhou
  ``test_wallet_over_fill_cap_stops_and_is_marked_incompatible`` (exatamente 5 fills, o
  teto, já marcavam a carteira).
- Reingestão comparando com ``seq``: falhou
  ``test_reingesting_window_keeps_fill_count_and_hash``, porque a mesma janela, com a
  ordem dentro do milissegundo trocada, virou divergência.
- Reingestão sem gravar ``divergences``: falharam os três testes de divergência.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.ingestion.fake import FakeInfo
from copylab.ingestion.fills import (
    STATUS_FAILED,
    STATUS_INCOMPATIBLE,
    STATUS_OK,
    classify,
    collect_fills,
    ingest_fills,
)
from copylab.storage import ParquetRepository, ParquetStore, Span, content_hash
from copylab.timeutil import Ms

W0 = Ms(1_782_864_000_000)  # 2026-07-01T00:00:00Z
W1 = Ms(1_788_220_800_000)  # 2026-09-01T00:00:00Z
WINDOW = Span(W0, W1)
NOW = Ms(1_791_244_800_000)  # 2026-10-06, instante da coleta
PERPS = frozenset({"BTC", "ETH", "kPEPE"})
A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40


def fill(t: int, coin: str = "BTC", tid: int = 1, **override: Any) -> dict[str, Any]:
    """Um fill no formato da API (números como texto, como ela os devolve)."""
    base: dict[str, Any] = {
        "time": t,
        "coin": coin,
        "px": "100.5",
        "sz": "0.1",
        "side": "B",
        "startPosition": "0.0",
        "dir": "Open Long",
        "crossed": True,
        "closedPnl": "0.0",
        "fee": "0.01",
        "tid": tid,
        "oid": 7,
        "hash": "0x00",
        "feeToken": "USDC",
        "twapId": None,
    }
    base.update(override)
    return base


def clock() -> Ms:
    return NOW


def keys(fills: list[dict[str, Any]]) -> Counter[str]:
    return Counter(json.dumps(f, sort_keys=True) for f in fills)


# ─── Paginação (CA-02.1) ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_pagination_inclusive_start_dedupes_boundary_millisecond() -> None:
    # Páginas de 3. Fills em W0 + 1 s (tid 1), dois em W0 + 2 s (tids 2 e 3), em 3 s (4)
    # e em 4 s (5).
    # Página 1: [1, 2, 3], cheia: recomeça em 2 s, tendo visto {2, 3} nesse milissegundo.
    # Página 2: [2, 3, 4], cheia: 2 e 3 descartados, 4 é novo; recomeça em 3 s, viu {4}.
    # Página 3: [4, 5], com menos de 3: 4 descartado, 5 novo, fim. Total 5 em 3 páginas.
    source = {
        A: [
            fill(W0 + 1_000, tid=1),
            fill(W0 + 2_000, tid=2),
            fill(W0 + 2_000, tid=3),
            fill(W0 + 3_000, tid=4),
            fill(W0 + 4_000, tid=5),
        ]
    }
    got = collect_fills(FakeInfo(fills=source, page_size=3), A, W0, W1, cap=100, page_max=3)
    assert [f["tid"] for f in got.fills] == [1, 2, 3, 4, 5]
    assert got.pages == 3
    assert not got.capped


@pytest.mark.unit
def test_300_fills_in_one_millisecond_across_page_boundary_are_neither_lost_nor_duplicated(
    tmp_path: Path,
) -> None:
    # Página real de 2.000. 1.849 fills antes de X = W0 + 10 s, 300 fills em X e 100
    # depois: 2.249 no total.
    # Os 300 de X são 150 conteúdos distintos (tid 10.000 a 10.149), cada um duas vezes
    # seguidas: c0, c0, c1, c1, ... — cópias idênticas genuínas.
    # Página 1: 1.849 + os 151 primeiros de X (c0..c74 duas vezes e a primeira cópia de
    # c75). Cheia: recomeça em X tendo visto c0..c74 x2 e c75 x1.
    # Página 2: os 300 de X e os 100 depois (400 < 2.000, última). Descarta c0..c74 x2 e
    # c75 x1 (151); ficam a segunda cópia de c75, c76..c149 x2 (149) e os 100: 249 novos.
    # Total: 2.000 + 249 = 2.249, cada conteúdo com a multiplicidade que tinha na origem.
    x = W0 + 10_000
    before = [fill(W0 + i, tid=i + 1) for i in range(1_849)]
    at_x = [fill(x, tid=10_000 + i // 2) for i in range(300)]
    after = [fill(x + 1 + i, tid=20_000 + i) for i in range(100)]
    source = before + at_x + after
    fake = FakeInfo(fills={A: source})

    got = collect_fills(fake, A, W0, W1, cap=20_000)
    assert got.pages == 2
    assert len(got.fills) == 2_249
    assert keys(got.fills) == keys(source)

    store = ParquetStore(tmp_path)
    report = ingest_fills(fake, store, [A], WINDOW, PERPS, 20_000, clock)
    stored = ParquetRepository(store).fills(A, W0, W1)
    assert report.wallets[0].n_fills == stored.height == 2_249
    assert stored.filter(pl.col("time_ms") == x).height == 300
    assert stored.get_column("seq").to_list() == list(range(2_249))


@pytest.mark.unit
def test_more_than_a_page_in_one_millisecond_fails_explicitly() -> None:
    # Quatro fills no mesmo milissegundo com páginas de 3: a página 2, a partir dele,
    # devolve os mesmos três e nada novo. Sem a recusa, seria laço infinito.
    source = {A: [fill(W0 + 1_000, tid=i) for i in range(1, 5)]}
    with pytest.raises(DataError, match="mais de 3 fills"):
        collect_fills(FakeInfo(fills=source, page_size=3), A, W0, W1, cap=100, page_max=3)


@pytest.mark.unit
def test_page_out_of_order_or_window_fails() -> None:
    class Disordered(FakeInfo):
        def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
            return [fill(W0 + 2_000), fill(W0 + 1_000)]

    class Outside(FakeInfo):
        def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, Any]]:
            return [fill(W1)]

    with pytest.raises(DataError, match="ordem crescente"):
        collect_fills(Disordered(), A, W0, W1, cap=100)
    with pytest.raises(DataError, match="fora de"):
        collect_fills(Outside(), A, W0, W1, cap=100)


# ─── Teto (CA-02.3) ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_wallet_over_fill_cap_stops_and_is_marked_incompatible(tmp_path: Path) -> None:
    # Teto 5, páginas de 3, um fill por segundo. A tem 5 fills: no teto, ok. B tem 9:
    # página 1 [0, 1, 2] (3 coletados), recomeça em 2 s; página 2 [2, 3, 4] (2 novos, 5);
    # página 3 [4, 5, 6] (2 novos, 7 > 5): a coleta para ali, sem pedir a página 4.
    source = {
        A: [fill(W0 + i * 1_000, tid=i + 1) for i in range(5)],
        B: [fill(W0 + i * 1_000, tid=i + 1) for i in range(9)],
    }
    fake = FakeInfo(fills=source, page_size=3)
    store = ParquetStore(tmp_path)
    report = ingest_fills(fake, store, [A, B], WINDOW, PERPS, 5, clock, page_max=3)

    assert [(w.status, w.n_fills) for w in report.wallets] == [
        (STATUS_OK, 5),
        (STATUS_INCOMPATIBLE, 7),
    ]
    assert len([c for c in fake.calls if c[1] == B]) == 3
    repo = ParquetRepository(store)
    assert repo.fills(B, W0, W1).height == 0  # nada gravado: o histórico ficaria truncado
    assert repo.coverage(B, W0, W1).item(0, "status") == STATUS_INCOMPATIBLE


# ─── Classificação e validação (CA-02.4, CA-02.5) ────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("coin", "kind"),
    [
        ("BTC", "perp"),
        ("kPEPE", "perp"),
        ("xyz:TSLA", "hip3"),
        ("@107", "spot"),
        ("PURR/USDC", "spot"),
        ("#1234", "outcome"),
        ("OLDCOIN", "other"),
    ],
)
def test_fill_is_classified_by_instrument_kind(coin: str, kind: str) -> None:
    assert classify(coin, PERPS) == kind


@pytest.mark.unit
def test_out_of_universe_fills_are_kept_and_flagged(tmp_path: Path) -> None:
    # Perpétuo, HIP-3, spot, resultado e um perpétuo que saiu do meta: todos gravados, com
    # a classe; o que saiu do meta é "outro" e vai para o relatório.
    coins = ["BTC", "xyz:TSLA", "@107", "#1234", "OLDCOIN"]
    source = {A: [fill(W0 + i * 1_000, coin=c, tid=i + 1) for i, c in enumerate(coins)]}
    store = ParquetStore(tmp_path)
    report = ingest_fills(FakeInfo(fills=source), store, [A], WINDOW, PERPS, 100, clock)

    stored = ParquetRepository(store).fills(A, W0, W1)
    assert stored.select("coin", "kind").rows() == [
        ("BTC", "perp"),
        ("xyz:TSLA", "hip3"),
        ("@107", "spot"),
        ("#1234", "outcome"),
        ("OLDCOIN", "other"),
    ]
    assert report.other_coins == ["OLDCOIN"]


@pytest.mark.unit
def test_perp_fill_with_invalid_field_makes_wallet_ineligible(tmp_path: Path) -> None:
    # Um fill de BTC com tid zero (não interpretável, como o da conversão de saldo) e um
    # com px "abc". Os dois são gravados, com o campo nulo, e a carteira sai com 2 fills de
    # perpétuo inválidos: é o que F3 lê (T-063). O fill de spot com tid zero não conta.
    source = {
        A: [
            fill(W0 + 1_000, tid=0),
            fill(W0 + 2_000, tid=2, px="abc"),
            fill(W0 + 3_000, tid=3),
            fill(W0 + 4_000, coin="@107", tid=0),
        ]
    }
    store = ParquetStore(tmp_path)
    report = ingest_fills(FakeInfo(fills=source), store, [A], WINDOW, PERPS, 100, clock)

    assert report.wallets[0].invalid_perp_fills == 2
    stored = ParquetRepository(store).fills(A, W0, W1)
    assert stored.get_column("tid").to_list() == [None, 2, 3, None]
    assert stored.get_column("px").to_list() == [100.5, None, 100.5, 100.5]


@pytest.mark.unit
def test_non_perp_fill_without_price_counts_zero_notional(tmp_path: Path) -> None:
    # Liquidação de token de resultado com px "0" (Settlement) e spot com sz vazio: são
    # gravados, com o campo nulo, e contados como notional zero. Não tornam a carteira
    # inelegível: só os perpétuos do primeiro dex precisam dos 12 campos.
    source = {
        A: [
            fill(W0 + 1_000, coin="#1234", px="0", dir="Settlement"),
            fill(W0 + 2_000, coin="@107", sz=""),
        ]
    }
    store = ParquetStore(tmp_path)
    report = ingest_fills(FakeInfo(fills=source), store, [A], WINDOW, PERPS, 100, clock)

    wallet = report.wallets[0]
    assert (wallet.zero_notional_fills, wallet.invalid_perp_fills) == (2, 0)
    stored = ParquetRepository(store).fills(A, W0, W1)
    notional = stored.select((pl.col("px") * pl.col("sz")).fill_null(0.0)).to_series()
    assert notional.to_list() == [0.0, 0.0]


@pytest.mark.unit
def test_fill_fields_are_read_into_typed_columns(tmp_path: Path) -> None:
    liquidation = {"liquidatedUser": A.upper().replace("0X", "0x"), "markPx": "1", "method": "x"}
    source = {
        A: [
            fill(
                W0 + 1_000,
                coin="ETH",
                px="2500.25",
                sz="1.5",
                side="A",
                startPosition="-3.0",
                dir="Open Short",
                crossed=False,
                closedPnl="-1.25",
                fee="0.5",
                tid=99,
                oid=123,
                twapId=4,
                liquidation=liquidation,
            )
        ]
    }
    store = ParquetStore(tmp_path)
    ingest_fills(FakeInfo(fills=source), store, [A], WINDOW, PERPS, 100, clock)
    row = ParquetRepository(store).fills(A, W0, W1).row(0, named=True)
    assert row == {
        "seq": 0,
        "time_ms": W0 + 1_000,
        "coin": "ETH",
        "kind": "perp",
        "px": 2500.25,
        "sz": 1.5,
        "side": "A",
        "start_position": -3.0,
        "dir": "Open Short",
        "crossed": False,
        "closed_pnl": -1.25,
        "fee": 0.5,
        "tid": 99,
        "oid": 123,
        "twap_id": 4,
        "liquidated_user": A,
    }


@pytest.mark.unit
def test_fill_without_instant_is_a_wallet_failure(tmp_path: Path) -> None:
    source = {A: [fill(W0 + 1_000), {**fill(W0 + 2_000), "coin": None}]}
    store = ParquetStore(tmp_path)
    report = ingest_fills(FakeInfo(fills=source), store, [A], WINDOW, PERPS, 100, clock)
    assert report.wallets[0].status == STATUS_FAILED


# ─── Cobertura, retomada e falha (RF-ING-07 CA-07.2, RF-ING-08 CA-08.1) ─────


@pytest.mark.unit
def test_result_records_ingestion_instants_and_content_hash(tmp_path: Path) -> None:
    source = {A: [fill(W0 + 1_000, tid=1), fill(W0 + 2_000, tid=2)]}
    store = ParquetStore(tmp_path)
    ingest_fills(FakeInfo(fills=source), store, [A], WINDOW, PERPS, 100, clock)
    repo = ParquetRepository(store)
    coverage = repo.coverage(A, W0, W1).row(0, named=True)
    stored = repo.fills(A, W0, W1)
    assert coverage == {
        "start_ms": W0,
        "end_ms": W1,
        "ingested_at_ms": NOW,
        "n_fills": 2,
        "status": STATUS_OK,
        "content_hash": content_hash(stored, ["time_ms", "seq"]),
    }


@pytest.mark.unit
def test_failure_does_not_abort_other_wallets_and_resumes_from_first_without_coverage(
    tmp_path: Path,
) -> None:
    # B falha (rede esgotada); A e C são gravados. Na segunda execução, A e C são pulados
    # sem nenhuma requisição, e só B é coletado de novo.
    source = {a: [fill(W0 + 1_000)] for a in (A, B, C)}
    store = ParquetStore(tmp_path)
    first = ingest_fills(
        FakeInfo(fills=source, failing=frozenset({B})), store, [A, B, C], WINDOW, PERPS, 100, clock
    )
    assert [w.status for w in first.wallets] == [STATUS_OK, STATUS_FAILED, STATUS_OK]
    assert [w.address for w in first.failed] == [B]
    assert ParquetRepository(store).coverage(B, W0, W1).item(0, "status") == STATUS_FAILED

    retry = FakeInfo(fills=source)
    second = ingest_fills(retry, store, [A, B, C], WINDOW, PERPS, 100, clock)
    assert [w.skipped for w in second.wallets] == [True, False, True]
    assert {call[1] for call in retry.calls} == {B}
    assert not second.failed
    assert ParquetRepository(store).coverage(B, W0, W1).item(0, "status") == STATUS_OK


# ─── Reingestão (T-023; CA-02.2, CA-08.2) ────────────────────────────────────


@pytest.mark.unit
def test_reingesting_window_keeps_fill_count_and_hash(tmp_path: Path) -> None:
    # Na segunda coleta, a API devolve os dois fills do mesmo milissegundo na ordem
    # inversa. O conteúdo é o mesmo: nada muda, e a ordem gravada (seq) fica.
    one, two = fill(W0 + 1_000, tid=1), fill(W0 + 1_000, tid=2)
    store = ParquetStore(tmp_path)
    ingest_fills(FakeInfo(fills={A: [one, two]}), store, [A], WINDOW, PERPS, 100, clock)
    repo = ParquetRepository(store)
    before = repo.coverage(A, W0, W1).item(0, "content_hash")

    report = ingest_fills(
        FakeInfo(fills={A: [two, one]}), store, [A], WINDOW, PERPS, 100, clock, reingest=True
    )
    assert not report.wallets[0].changed
    assert report.wallets[0].n_fills == 2
    assert repo.fills(A, W0, W1).get_column("tid").to_list() == [1, 2]
    assert repo.coverage(A, W0, W1).item(0, "content_hash") == before
    assert repo.divergences(A, W0, W1).height == 0


@pytest.mark.unit
def test_changed_fill_is_logged_and_changes_hash(tmp_path: Path) -> None:
    # O fill de tid 2 volta com px 101 no lugar de 100,5: uma divergência, com o valor
    # anterior e o novo; o conteúdo novo substitui o antigo, e o hash muda.
    store = ParquetStore(tmp_path)
    original = [fill(W0 + 1_000, tid=1), fill(W0 + 2_000, tid=2)]
    changed = [fill(W0 + 1_000, tid=1), fill(W0 + 2_000, tid=2, px="101")]
    ingest_fills(FakeInfo(fills={A: original}), store, [A], WINDOW, PERPS, 100, clock)
    repo = ParquetRepository(store)
    before = repo.coverage(A, W0, W1).item(0, "content_hash")

    report = ingest_fills(
        FakeInfo(fills={A: changed}), store, [A], WINDOW, PERPS, 100, clock, reingest=True
    )
    assert report.wallets[0].divergences == 1
    assert repo.divergences(A, W0, W1).rows() == [(W0 + 2_000, 2, "px", "100.5", "101.0", NOW)]
    assert repo.fills(A, W0, W1).get_column("px").to_list() == [100.5, 101.0]
    assert repo.coverage(A, W0, W1).item(0, "content_hash") != before


@pytest.mark.unit
def test_missing_and_new_fills_are_recorded_as_whole_rows(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    ingest_fills(
        FakeInfo(fills={A: [fill(W0 + 1_000, tid=1)]}), store, [A], WINDOW, PERPS, 9, clock
    )
    ingest_fills(
        FakeInfo(fills={A: [fill(W0 + 2_000, tid=2)]}),
        store,
        [A],
        WINDOW,
        PERPS,
        9,
        clock,
        reingest=True,
    )
    fields = ParquetRepository(store).divergences(A, W0, W1).get_column("field").to_list()
    assert sorted(fields) == ["row_added", "row_removed"]


@pytest.mark.unit
def test_frozen_fill_rows_are_never_rewritten_and_divergence_is_recorded(
    tmp_path: Path,
) -> None:
    # A janela foi coletada e depois congelada. A reingestão traz tid 2 com outro preço:
    # a divergência é gravada, e o dado fica como estava (design §3.2, "Janela congelada").
    original = [fill(W0 + 1_000, tid=1), fill(W0 + 2_000, tid=2)]
    changed = [fill(W0 + 1_000, tid=1), fill(W0 + 2_000, tid=2, px="101")]
    ingest_fills(
        FakeInfo(fills={A: original}), ParquetStore(tmp_path), [A], WINDOW, PERPS, 9, clock
    )
    frozen = ParquetStore(tmp_path, frozen=[WINDOW])

    report = ingest_fills(
        FakeInfo(fills={A: changed}), frozen, [A], WINDOW, PERPS, 9, clock, reingest=True
    )
    repo = ParquetRepository(frozen)
    assert repo.fills(A, W0, W1).get_column("px").to_list() == [100.5, 100.5]
    assert repo.divergences(A, W0, W1).select("field", "old", "new").rows() == [
        ("px", "100.5", "101.0")
    ]
    assert report.wallets[0].frozen_kept == 1
