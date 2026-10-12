"""Conferência de PnL por custo médio (T-031, design §3.5; RF-ING-04 CA-04.2).

Fixtures de papel, como em `test_leader_ledger.py`: a reconstrução esperada e a divergência
em bps estão calculadas no comentário de cada teste. Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez (cada uma está
na docstring do teste que a pega).
"""

from typing import Any

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.leader import (
    build_episodes,
    pnl_divergence_bps,
    pnl_violations,
)
from copylab.storage.tables import SCHEMAS

LOTS = {"BTC": 0.01}


def fill(
    t: int,
    coin: str,
    side: str,
    sz: float,
    px: float,
    start: float,
    *,
    pnl: float | None = 0.0,
    twap_id: int | None = None,
) -> dict[str, Any]:
    return {
        "time_ms": t,
        "coin": coin,
        "kind": "hip3" if ":" in coin else "perp",
        "px": px,
        "sz": sz,
        "side": side,
        "start_position": start,
        "dir": None,
        "crossed": True,
        "closed_pnl": pnl,
        "fee": 0.0,
        "tid": 1,
        "oid": 1,
        "twap_id": twap_id,
        "liquidated_user": None,
    }


def table(*rows: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame([{"seq": i, **row} for i, row in enumerate(rows)], schema=SCHEMAS["fills"])


# ─── Reconstrução por custo médio ────────────────────────────────────────────


@pytest.mark.unit
def test_average_cost_reconstruction_matches_reported_pnl_with_partial_closes() -> None:
    """Compra de 10 a 100 e de 10 a 110 (custo médio 105, posição 20); venda de 5 a 120 e de
    15 a 102.
      1ª venda: 5 x (120 - 105) = 75. 2ª venda: 15 x (102 - 105) = -45. Realizado: 30.
      `closed_pnl` informado: 75 e -45, soma 30.
      Notional negociado: 1.000 + 1.100 + 600 + 1.530 = 4.230.
    Divergência: |30 - 30| / 4.230 = 0 bps. Vale também para um episódio vendido: venda de 5
    a 100 e recompra de 5 a 90 realiza 5 x (90 - 100) x (-1) = 50.
    """
    data = table(
        fill(1_000, "BTC", "B", 10.0, 100.0, 0.0),
        fill(2_000, "BTC", "B", 10.0, 110.0, 10.0),
        fill(3_000, "BTC", "A", 5.0, 120.0, 20.0, pnl=75.0),
        fill(4_000, "BTC", "A", 15.0, 102.0, 15.0, pnl=-45.0),
    )
    (episode,) = build_episodes(data, LOTS)
    assert episode.traded_notional == pytest.approx(4_230.0)
    assert pnl_divergence_bps(data, episode) == pytest.approx(0.0, abs=1e-9)

    short = table(
        fill(1_000, "BTC", "A", 5.0, 100.0, 0.0),
        fill(2_000, "BTC", "B", 5.0, 90.0, -5.0, pnl=50.0),
    )
    (short_episode,) = build_episodes(short, LOTS)
    assert pnl_divergence_bps(short, short_episode) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_pnl_divergence_just_below_and_just_above_the_tolerance() -> None:
    """RF-ING-04 CA-04.2, tolerância de 10 bps. Compra de 10 a 100 e venda de 10 a 101:
    realizado 10 x (101 - 100) = 10; notional negociado 1.000 + 1.010 = 2.010.
      `closed_pnl` informado 12,00: |12,00 - 10| / 2.010 x 10.000 = 9,9502 bps, abaixo.
      `closed_pnl` informado 12,02: 2,02 / 2.010 x 10.000 = 10,0498 bps, acima.
    Só o segundo é violação. O limite é um máximo: a tolerância em si não viola.

    Mutação registrada: dividir pela metade do notional negociado (`/ (traded_notional / 2)`)
    leva o caso de baixo a 19,9 bps e o faz virar violação; trocar `>` por `<` em
    `pnl_violations` inverte os dois. Nos dois casos o teste cai.
    """
    found = {}
    for reported in (12.00, 12.02):
        data = table(
            fill(1_000, "BTC", "B", 10.0, 100.0, 0.0),
            fill(2_000, "BTC", "A", 10.0, 101.0, 10.0, pnl=reported),
        )
        episodes = build_episodes(data, LOTS)
        found[reported] = (
            pnl_divergence_bps(data, episodes[0]),
            [d for _, d in pnl_violations(data, episodes, 10.0)],
        )
    below, above = found[12.00], found[12.02]
    assert below[0] == pytest.approx(9.9502, abs=1e-4)
    assert below[1] == []
    assert above[0] == pytest.approx(10.0498, abs=1e-4)
    assert above[1] == pytest.approx([10.0498], abs=1e-4)


@pytest.mark.unit
def test_closed_pnl_of_a_crossing_fill_belongs_to_the_episode_that_closes() -> None:
    """RF-ING-04 CA-04.1 e design §3.5. Compra de 4 a 100 (0 a 4). Venda de 10 a 110 com
    start 4 (4 a -6): fecha 4 e abre 6 vendidos; `closed_pnl` 40 = 4 x (110 - 100). Recompra
    de 6 a 105 com start -6: fecha o vendido, `closed_pnl` 30 = 6 x (110 - 105).
    Episódio 1 (seq 0 a 1): realizado 40, informado 40 (o do fill que cruza), divergência 0.
    Episódio 2 (seq 1 a 2): abriu 6 a 110 e fechou a 105, realizado 6 x (105 - 110) x (-1) =
      30; informado só o do último fill, 30; divergência 0. O 40 do fill que cruza não conta
      aqui: se contasse, o informado seria 70, e a divergência 40 / 1.290 x 10.000 = 310 bps.
    Notional negociado do episódio 2: 6 x 110 + 6 x 105 = 1.290.

    Mutação registrada: somar o `closed_pnl` do fill que cruza também no episódio que abre
    (`if True:` no lugar de `if not inherited:` em `_divergence`) dá 310 bps no episódio 2, e
    o teste cai.
    """
    data = table(
        fill(1_000, "BTC", "B", 4.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 10.0, 110.0, 4.0, pnl=40.0),
        fill(3_000, "BTC", "B", 6.0, 105.0, -6.0, pnl=30.0),
    )
    first, second = build_episodes(data, LOTS)
    assert (first.first_seq, first.last_seq, second.first_seq, second.last_seq) == (0, 1, 1, 2)
    assert second.traded_notional == pytest.approx(1_290.0)
    assert pnl_divergence_bps(data, first) == pytest.approx(0.0, abs=1e-9)
    assert pnl_divergence_bps(data, second) == pytest.approx(0.0, abs=1e-9)
    assert pnl_violations(data, [first, second], 10.0) == []


@pytest.mark.unit
def test_pnl_check_skips_episodes_open_at_window_start() -> None:
    """RF-ING-04 CA-04.2: episódio que já estava aberto no início da janela não tem custo de
    entrada conhecido e fica fora. Também ficam fora o que não fechou, o `broken` (faltam
    fills) e o que tem `closed_pnl` ilegível. Em todos, a divergência é `None`, e não zero.

    Pré-existente: venda de 5 com start 5 (de 5 a zero) e `closed_pnl` absurdo de 9.999: se
    fosse conferido, divergiria. Aberto: só a compra. `broken`: o fill que declara 3 quando
    se tinha 5. Ilegível: `closed_pnl` nulo na venda.

    Mutação registrada: tirar `not episode.opened_from_flat` da guarda de `_divergence` faz o
    pré-existente divergir (milhares de bps) e o teste cai.
    """
    pre_existing = table(fill(1_000, "BTC", "A", 5.0, 100.0, 5.0, pnl=9_999.0))
    still_open = table(fill(1_000, "BTC", "B", 5.0, 100.0, 0.0))
    broken = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 3.0, 101.0, 3.0, pnl=3.0),
    )
    unreadable = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 5.0, 101.0, 5.0, pnl=None),
    )
    for data in (pre_existing, still_open, broken, unreadable):
        (episode,) = build_episodes(data, LOTS)
        assert pnl_divergence_bps(data, episode) is None
        assert pnl_violations(data, [episode], 10.0) == []
    assert not build_episodes(pre_existing, LOTS)[0].opened_from_flat
    assert build_episodes(still_open, LOTS)[0].closed is None
    assert build_episodes(broken, LOTS)[0].broken


@pytest.mark.unit
def test_episode_that_does_not_match_the_fills_is_a_data_error() -> None:
    """Um episódio de outra tabela: o `seq` dele não está nos fills dados, ou o número de
    fills entre o primeiro e o último não bate."""
    data = table(
        fill(1_000, "BTC", "B", 1.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 1.0, 101.0, 1.0, pnl=1.0),
    )
    (episode,) = build_episodes(data, LOTS)
    with pytest.raises(DataError, match="não corresponde"):
        pnl_divergence_bps(data.filter(pl.col("seq") == 0), episode)
    three = table(
        fill(1_000, "BTC", "B", 1.0, 100.0, 0.0),
        fill(1_500, "BTC", "B", 1.0, 100.0, 1.0),
        fill(2_000, "BTC", "A", 2.0, 101.0, 2.0, pnl=2.0),
    )
    (long,) = build_episodes(three, LOTS)
    other_asset_between = table(
        fill(1_000, "BTC", "B", 1.0, 100.0, 0.0),
        fill(1_500, "ETH", "B", 1.0, 2_000.0, 0.0),
        fill(2_000, "BTC", "A", 2.0, 101.0, 2.0, pnl=2.0),
    )
    # seq 0 e 2 existem, mas só há 2 fills de BTC entre eles, e o episódio tem 3.
    with pytest.raises(DataError, match="tem 3 fills"):
        pnl_divergence_bps(other_asset_between, long)
