"""Livro-razão do líder: posições, eventos e quebras de continuidade (T-030, design §3.5).

Fixtures de papel (RNF-03): sequências de fills escritas à mão, com posição, evento e
episódio esperados calculados no próprio teste, em comentário. Nenhum dado real.

Convenções das fixtures: o primeiro dex tem lote 0,01 (`LOTS`), salvo onde o teste diz
outro. Tamanhos e preços são frações de 2 (0,5; 0,25) onde a conta precisa ser exata em
ponto flutuante, e a comparação usa `pytest.approx` onde não é (RNF-08).

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.leader.ledger` (as mutações de cada teste estão na docstring dele). Os episódios estão em
`test_leader_episodes.py`.
"""

import random
from typing import Any

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.ingestion.fills import HIP3 as INGESTION_HIP3
from copylab.ingestion.fills import PERP as INGESTION_PERP
from copylab.leader import (
    HIP3,
    PERP,
    Break,
    build_events,
    continuity_breaks,
    ignored_fills,
)
from copylab.storage.tables import SCHEMAS
from copylab.timeutil import Ms

LOTS = {"BTC": 0.01, "ETH": 0.01}


def fill(
    t: int,
    coin: str,
    side: str,
    sz: float,
    px: float,
    start: float,
    *,
    pnl: float = 0.0,
    crossed: bool = True,
    twap_id: int | None = None,
) -> dict[str, Any]:
    """Um fill. `seq` é atribuído por `table`, na ordem em que os fills são dados."""
    return {
        "time_ms": t,
        "coin": coin,
        "kind": "hip3" if ":" in coin else "perp",
        "px": px,
        "sz": sz,
        "side": side,
        "start_position": start,
        "dir": None,
        "crossed": crossed,
        "closed_pnl": pnl,
        "fee": 0.0,
        "tid": 1,
        "oid": 1,
        "twap_id": twap_id,
        "liquidated_user": None,
    }


def table(*rows: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame([{"seq": i, **row} for i, row in enumerate(rows)], schema=SCHEMAS["fills"])


# ─── Constantes e contrato ───────────────────────────────────────────────────


@pytest.mark.unit
def test_kind_constants_match_what_ingestion_writes() -> None:
    """O pacote não importa `ingestion`; este teste garante que os dois falam a mesma língua."""
    assert (PERP, HIP3) == (INGESTION_PERP, INGESTION_HIP3)


@pytest.mark.unit
def test_perp_without_lot_and_table_without_columns_are_data_errors() -> None:
    with pytest.raises(DataError, match="SOL"):
        build_events(table(fill(1_000, "SOL", "B", 1.0, 10.0, 0.0)), LOTS)
    with pytest.raises(DataError, match="colunas"):
        build_events(pl.DataFrame({"coin": ["BTC"]}), LOTS)


@pytest.mark.unit
def test_256_fills_in_one_millisecond_become_one_event() -> None:
    """Uma ordem do líder dividida em 256 fills é uma decisão do seguidor (design §3.5).

    BTC, t = 5.000: 256 compras de 0,5 a 100 + i (i de 0 a 255), cada uma com o
    `start_position` da anterior (0; 0,5; 1,0; ...). Mais uma compra de ETH no mesmo
    milissegundo, que é outro evento.
      posição final de BTC: 256 x 0,5 = 128; partiu de zero.
      notional: soma de 0,5 x (100 + i) = 0,5 x (25.600 + 255 x 256 / 2) = 0,5 x 58.240
        = 29.120. Preço do último fill: 100 + 255 = 355.
    Eventos em ordem de ativo no empate de instante: BTC, ETH.

    Mutação registrada: tratar cada fill como um evento (`if group:` no lugar de comparar o
    instante com o do grupo, em `build_events`) dá 257 eventos, e o teste cai.
    """
    rows = [fill(5_000, "BTC", "B", 0.5, 100.0 + i, 0.5 * i) for i in range(256)]
    rows.insert(100, fill(5_000, "ETH", "B", 1.0, 2_000.0, 0.0))
    events = build_events(table(*rows), LOTS)
    assert [(e.coin, e.n_fills) for e in events] == [("BTC", 256), ("ETH", 1)]
    btc = events[0]
    assert (btc.t, btc.kind, btc.prev_position, btc.position) == (Ms(5_000), PERP, 0.0, 128.0)
    assert (btc.touched_zero, btc.px, btc.unobserved, btc.n_fills) == (True, 355.0, False, 256)
    assert btc.notional == pytest.approx(29_120.0)


@pytest.mark.unit
def test_position_going_to_zero_and_to_three_in_one_millisecond_touches_zero() -> None:
    """10 a zero e a 3 no mesmo milissegundo: um evento, dois episódios (design §3.5).

    t = 1.000: compra de 10 a 99, de zero a 10. t = 2.000: venda de 10 a 100 (10 a zero) e
    compra de 3 a 101 (zero a 3).
    Evento de t = 2.000: prev_position 10, position 3, touched_zero verdadeiro (zero no meio),
    notional 10 x 100 + 3 x 101 = 1.303, preço do último fill 101, 2 fills. Os dois episódios
    estão em `test_leader_episodes.py`.

    Mutação registrada: calcular `touched_zero` só pelas pontas do evento (`prev_position == 0
    or position == 0`) no lugar de por fill dá falso para 10 -> 0 -> 3, e o teste cai.
    """
    data = table(
        fill(1_000, "BTC", "B", 10.0, 99.0, 0.0),
        fill(2_000, "BTC", "A", 10.0, 100.0, 10.0),
        fill(2_000, "BTC", "B", 3.0, 101.0, 0.0),
    )
    first, second = build_events(data, LOTS)
    assert (first.prev_position, first.position, first.touched_zero) == (0.0, 10.0, True)
    assert (second.prev_position, second.position, second.touched_zero) == (10.0, 3.0, True)
    assert second.notional == pytest.approx(1_303.0)
    assert (second.px, second.n_fills) == (101.0, 2)


@pytest.mark.unit
def test_event_that_only_resizes_a_position_does_not_touch_zero() -> None:
    """Aumentar e reduzir sem passar por zero: 2 -> 5 -> 4. touched_zero falso nos dois."""
    data = table(
        fill(1_000, "BTC", "B", 2.0, 100.0, 0.0),
        fill(2_000, "BTC", "B", 3.0, 100.0, 2.0),
        fill(3_000, "BTC", "A", 1.0, 100.0, 5.0),
    )
    flags = [e.touched_zero for e in build_events(data, LOTS)]
    assert flags == [True, False, False]  # só o primeiro parte de zero


@pytest.mark.unit
def test_sign_inversion_in_a_single_fill_touches_zero_and_flips_the_position() -> None:
    """Compra de 4 (0 a 4) e venda de 10 com start 4 (4 a -6) no mesmo ativo: o evento do
    segundo fill tem prev_position 4, position -6 e touched_zero verdadeiro (cruzou o zero). O
    notional é do fill inteiro, 10 x 110 = 1.100: a divisão em 4 e 6 é do episódio, não do
    evento."""
    data = table(
        fill(1_000, "BTC", "B", 4.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 10.0, 110.0, 4.0),
    )
    cross = build_events(data, LOTS)[1]
    assert (cross.prev_position, cross.position, cross.touched_zero) == (4.0, -6.0, True)
    assert cross.notional == pytest.approx(1_100.0)


@pytest.mark.unit
def test_position_already_open_at_window_start_is_not_an_unobserved_change() -> None:
    """RF-SIM-02 CA-02.3. Primeiro fill de BTC: venda de 2 a 100 com start 5 (de 5 a 3). Depois
    venda de 3 a 101 com start 3 (de 3 a zero).
    Primeiro evento: prev_position 5, position 3, sem tocar zero, sem mudança não observada:
    nada se tinha antes, e a posição aberta é só a declarada. Segundo: chega a zero."""
    data = table(
        fill(1_000, "BTC", "A", 2.0, 100.0, 5.0),
        fill(2_000, "BTC", "A", 3.0, 101.0, 3.0),
    )
    first, second = build_events(data, LOTS)
    assert (first.prev_position, first.position) == (5.0, 3.0)
    assert not first.touched_zero
    assert not first.unobserved
    assert second.touched_zero  # chega a zero
    assert continuity_breaks(data, LOTS) == []


@pytest.mark.unit
def test_missing_fill_is_a_continuity_break_and_the_declared_position_wins() -> None:
    """RF-ING-03 CA-03.1. BTC: compra de 5 a 100 (de 0 a 5). O fill intermediário, venda de
    2 (de 5 a 3), não veio. Depois, venda de 3 a 101 com start 3.

    Esperado 5, declarado 3: diferença 2, acima de um lote (0,01). Quebra em t = 3.000, com o
    fill anterior em 1.000. A posição passa a ser a declarada: o evento do segundo fill tem
    prev_position 3 (e não 5), position 0 e `unobserved` verdadeiro.
    O episódio dele está em `test_leader_episodes.py`.

    Mutação registrada: tolerância de `lot * 1000` no lugar de um lote (em `walk`) faz o teste
    cair (nenhuma quebra encontrada), junto com outros seis que dependem da quebra.
    """
    data = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(3_000, "BTC", "A", 3.0, 101.0, 3.0),
    )
    assert continuity_breaks(data, LOTS) == [
        Break(
            t=Ms(3_000),
            prev_t=Ms(1_000),
            coin="BTC",
            kind=PERP,
            expected=5.0,
            declared=3.0,
        )
    ]
    second = build_events(data, LOTS)[1]
    assert (second.prev_position, second.position, second.unobserved) == (3.0, 0.0, True)


@pytest.mark.unit
def test_continuity_tolerates_one_lot_and_no_more() -> None:
    """Lote 1,0 (BTC com 0 casas). Compra de 5 (de 0 a 5); o próximo fill declara o start:
    4,0: diferença 1,0 = um lote, dentro da tolerância, sem quebra;
    3,99: diferença 1,01, acima, quebra;
    5,0: diferença zero, sem quebra.
    """
    lots = {"BTC": 1.0}

    def breaks(declared: float) -> int:
        data = table(
            fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
            fill(2_000, "BTC", "A", 1.0, 100.0, declared),
        )
        return len(continuity_breaks(data, lots))

    assert (breaks(4.0), breaks(3.99), breaks(5.0)) == (0, 1, 0)


@pytest.mark.unit
def test_the_first_fill_of_an_asset_cannot_break_and_assets_are_independent() -> None:
    """O primeiro fill de cada ativo não tem posição anterior. ETH declara start 7 sem nunca
    ter sido visto: não é quebra, e a posição de BTC (outro ativo) não entra na conta."""
    data = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(2_000, "ETH", "B", 1.0, 2_000.0, 7.0),
        fill(3_000, "BTC", "A", 5.0, 100.0, 5.0),
    )
    assert continuity_breaks(data, LOTS) == []


@pytest.mark.unit
def test_floating_point_residue_after_closing_is_zero_in_the_first_dex_and_in_hip3() -> None:
    """Compra de 0,3 e depois venda de 0,3 com start 0,30000000000000004 (a soma 0,1 + 0,2
    em ponto flutuante). A posição depois é 0,3 - 0,30000000000000004 = -5,55e-17.
      Primeiro dex (lote 0,001): módulo abaixo de meio lote, 0,0005: zero.
      HIP-3: módulo abaixo de 1e-9 x 0,3 = 3e-10: zero.
    Nos dois, a posição do evento é 0,0 exato e `touched_zero` é verdadeiro, e a diferença de
    5,55e-17 não é quebra de continuidade. Sem a regra, ficaria posição -5,55e-17. O episódio
    fecha: `test_leader_episodes.py`.

    Mutação registrada: trocar `_is_zero` por `position == 0.0` (sem a regra de meio lote e
    sem a relativa de HIP-3) faz os dois casos caírem: a posição fica -5,55e-17.
    """
    residue = 0.1 + 0.2
    for coin, lots in (("BTC", {"BTC": 0.001}), ("xyz:TSLA", {})):
        data = table(
            fill(1_000, coin, "B", 0.3, 100.0, 0.0),
            fill(2_000, coin, "A", 0.3, 100.0, residue),
        )
        closing = build_events(data, lots)[1]
        assert (closing.position, closing.touched_zero) == (0.0, True), coin
        assert continuity_breaks(data, lots) == [], coin


@pytest.mark.unit
def test_zero_threshold_is_half_a_lot_in_the_first_dex_and_relative_in_hip3() -> None:
    """Primeiro dex, lote 0,001: resíduo 0,0004 (< 0,0005) é zero; 0,0006 não é.
    HIP-3: resíduo 1e-10 (< 1e-9 x 0,3 = 3e-10) é zero; 1e-6 não é (nem tem lote que o salve).
    Venda de 0,3 com start 0,3 + resíduo: a posição depois é o resíduo, com sinal positivo.
    """

    def closes(coin: str, residue: float, lots: dict[str, float]) -> bool:
        data = table(
            fill(1_000, coin, "B", 0.3, 100.0, 0.0),
            fill(2_000, coin, "A", 0.3, 100.0, 0.3 + residue),
        )
        return build_events(data, lots)[1].position == 0.0

    lots = {"BTC": 0.001}
    assert closes("BTC", 0.0004, lots)
    assert not closes("BTC", 0.0006, lots)
    assert closes("xyz:TSLA", 1e-10, {})
    assert not closes("xyz:TSLA", 1e-6, {})


@pytest.mark.unit
def test_hip3_continuity_tolerance_scales_with_position_and_fill() -> None:
    """HIP-3 não tem lote: a tolerância é 1e-9 x o maior entre a posição que se tinha e o
    tamanho do fill (o erro de ponto flutuante cresce com a posição acumulada).

    Posição 1.000.000 (compra de 1e6). O próximo fill, venda de 1 declarando o start:
      1.000.000,0005: diferença 5e-4; tolerância 1e-9 x max(1e6, 1) = 1e-3: sem quebra. Pela
        regra só do fill, a tolerância seria 1e-9 e isto seria uma quebra falsa.
      1.000.000,002: diferença 2e-3 > 1e-3: quebra.
    Posição 1 e fill de 0,001: tolerância 1e-9 x max(1, 0,001) = 1e-9; 1,000000005 difere
    5e-9: quebra. E 1,0000000005 difere 5e-10: sem quebra.

    Mutação registrada: tolerância só pelo tamanho do fill (`_REL * fill.sz`) faz o primeiro
    caso acusar quebra, e o teste cai.
    """

    def breaks(opened: float, declared: float, sz: float) -> int:
        data = table(
            fill(1_000, "xyz:TSLA", "B", opened, 100.0, 0.0),
            fill(2_000, "xyz:TSLA", "A", sz, 100.0, declared),
        )
        return len(continuity_breaks(data, {}))

    assert breaks(1_000_000.0, 1_000_000.0005, 1.0) == 0
    assert breaks(1_000_000.0, 1_000_000.002, 1.0) == 1
    assert breaks(1.0, 1.000000005, 0.001) == 1
    assert breaks(1.0, 1.0000000005, 0.001) == 0


@pytest.mark.unit
def test_hip3_break_is_reported_with_its_kind() -> None:
    """A quebra em HIP-3 sai com `kind` hip3: a seleção a conta e não a usa para excluir a
    carteira (F3 vale só para o universo). O evento do fill que a revela fica `unobserved`."""
    data = table(
        fill(1_000, "xyz:TSLA", "B", 5.0, 100.0, 0.0),
        fill(2_000, "xyz:TSLA", "A", 3.0, 101.0, 3.0),
    )
    (found,) = continuity_breaks(data, {})
    assert (found.kind, found.coin, found.expected, found.declared) == (HIP3, "xyz:TSLA", 5.0, 3.0)
    assert build_events(data, {})[1].unobserved


@pytest.mark.unit
def test_ignored_fills_are_counted() -> None:
    """Perpétuo sem tamanho (HIP-3) e sem posição (primeiro dex) são ignorados e contados: 2.
    Um fill de spot e um de token de resultado, também sem campos, não são perpétuos e não
    entram na conta. Os eventos só veem o fill íntegro."""
    complete = fill(1_000, "BTC", "B", 1.0, 100.0, 0.0)
    no_size = {**fill(2_000, "xyz:TSLA", "B", 1.0, 100.0, 0.0), "sz": None}
    no_position = {**fill(3_000, "BTC", "B", 1.0, 100.0, 1.0), "start_position": None}
    spot = {**fill(4_000, "@107", "B", 1.0, 100.0, 0.0), "kind": "spot", "px": None}
    outcome = {**fill(5_000, "#10", "B", 1.0, 100.0, 0.0), "kind": "outcome", "sz": None}
    data = table(complete, no_size, no_position, spot, outcome)
    assert ignored_fills(data) == 2
    assert [(e.coin, e.t) for e in build_events(data, LOTS)] == [("BTC", Ms(1_000))]


@pytest.mark.unit
def test_same_inputs_give_identical_outputs_whatever_the_row_order() -> None:
    """RNF-01. Os fills chegam embaralhados; a ordem é a de `time_ms` e `seq`. Dois fills do
    mesmo milissegundo com `seq` 1 e 2 se encadeiam nessa ordem (start 0 e depois 2), e a
    posição do evento é 2 + 3 = 5 qualquer que seja a ordem das linhas."""
    rows = [
        {"seq": 0, **fill(1_000, "BTC", "B", 1.0, 100.0, 0.0)},
        {"seq": 1, **fill(2_000, "BTC", "B", 2.0, 100.0, 1.0)},
        {"seq": 2, **fill(2_000, "BTC", "B", 2.0, 100.0, 3.0)},
    ]
    reference = build_events(pl.DataFrame(rows, schema=SCHEMAS["fills"]), LOTS)
    assert reference[1].position == 5.0
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        got = build_events(pl.DataFrame(shuffled, schema=SCHEMAS["fills"]), LOTS)
        assert got == reference
