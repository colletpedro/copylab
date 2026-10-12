"""Episódios de zero a zero (T-031, design §3.5; RF-ING-04 CA-04.1).

Fixtures de papel, como em `test_leader_ledger.py`: cada episódio esperado está calculado no
comentário do teste. Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.leader.episodes` (as mutações de cada teste estão na docstring dele).
"""

from typing import Any

import polars as pl
import pytest

from copylab.leader import build_episodes, continuity_breaks
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


@pytest.mark.unit
def test_position_going_to_zero_and_to_three_in_one_millisecond_makes_two_episodes() -> None:
    """Os fills de `test_leader_ledger.py` (10 a zero e a 3 no mesmo milissegundo): compra de
    10 a 99 em 1.000 e, em 2.000, venda de 10 a 100 (10 a zero) e compra de 3 a
    101 (zero a 3). Um episódio de [1.000, 2.000] e outro aberto em 2.000 com 3."""
    data = table(
        fill(1_000, "BTC", "B", 10.0, 99.0, 0.0),
        fill(2_000, "BTC", "A", 10.0, 100.0, 10.0),
        fill(2_000, "BTC", "B", 3.0, 101.0, 0.0),
    )
    long, reopened = build_episodes(data, LOTS)
    assert (long.opened, long.closed) == (Ms(1_000), Ms(2_000))
    assert (reopened.opened, reopened.closed) == (Ms(2_000), None)


@pytest.mark.unit
def test_sign_inversion_in_a_single_fill_closes_one_episode_and_opens_another() -> None:
    """RF-ING-04 CA-04.1: inversão de sinal encerra um episódio e abre outro no mesmo instante.

    BTC: compra de 4 a 100 (0 a 4). Depois venda de 10 a 110 com start 4, de 4 a -6, que cruza.
    O tamanho se divide: 4 fecham o comprado, 6 abrem o vendido.
    Episódio 1: aberto em 1.000, fechado em 2.000, lado +1, de zero. Notional negociado
      4 x 100 + 4 x 110 = 840; de abertura 400 (só a compra); 2 fills; seq 0 a 1.
    Episódio 2: aberto em 2.000 no mesmo fill, lado -1, de zero. Negociado 6 x 110 = 660,
      tudo de abertura; 1 fill; seq 1 a 1 (o fill que cruza é o último de um e o primeiro
      do outro). Aberto, sem fechamento.
    O evento do fill que cruza está em `test_leader_ledger.py`.

    Mutação registrada: tratar o fill que cruza como só de fechamento (`current = None` no
    lugar de abrir o episódio com o resto, em `build_episodes`) deixa um episódio só, e o teste
    cai ao separar os dois.
    """
    data = table(
        fill(1_000, "BTC", "B", 4.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 10.0, 110.0, 4.0, crossed=False),
    )
    long, short = build_episodes(data, LOTS)
    assert (long.coin, long.opened, long.closed, long.side) == ("BTC", Ms(1_000), Ms(2_000), 1)
    assert (long.opened_from_flat, long.broken, long.n_fills) == (True, False, 2)
    assert (long.first_seq, long.last_seq) == (0, 1)
    assert (long.traded_notional, long.opening_notional) == pytest.approx((840.0, 400.0))
    assert long.opening_taker_notional == pytest.approx(400.0)
    assert (short.opened, short.closed, short.side) == (Ms(2_000), None, -1)
    assert (short.opened_from_flat, short.broken, short.n_fills) == (True, False, 1)
    assert (short.first_seq, short.last_seq) == (1, 1)
    assert (short.traded_notional, short.opening_notional) == pytest.approx((660.0, 660.0))
    assert short.opening_taker_notional == 0.0  # o fill que cruza não é taker (crossed = falso)


@pytest.mark.unit
def test_position_already_open_at_window_start_is_a_pre_existing_episode() -> None:
    """RF-SIM-02 CA-02.3: a posição aberta antes da janela não é copiada até voltar a zero.

    Primeiro fill de BTC: venda de 2 a 100 com start 5 (de 5 a 3). Depois venda de 3 a 101
    com start 3 (de 3 a zero).
    Episódio: aberto em 1.000 (o primeiro fill visto), `opened_from_flat` falso, lado +1,
      fechado em 2.000. Negociado 2 x 100 + 3 x 101 = 503; nada de abertura; 2 fills.
    """
    data = table(
        fill(1_000, "BTC", "A", 2.0, 100.0, 5.0),
        fill(2_000, "BTC", "A", 3.0, 101.0, 3.0),
    )
    (episode,) = build_episodes(data, LOTS)
    assert not episode.opened_from_flat
    assert (episode.side, episode.opened, episode.closed) == (1, Ms(1_000), Ms(2_000))
    assert episode.traded_notional == pytest.approx(503.0)
    assert episode.opening_notional == 0.0
    assert episode.n_fills == 2


@pytest.mark.unit
def test_episode_with_a_missing_fill_closes_normally_and_is_broken() -> None:
    """Compra de 5 a 100 em 1.000 (0 a 5); o fill de venda de 2 não veio; venda de 3 a 101 em
    3.000 com start 3. O episódio fecha em 3.000 como de costume (de 3 a zero) e fica
    `broken`: faltou um fill nele. Tem os 2 fills que se viram."""
    data = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(3_000, "BTC", "A", 3.0, 101.0, 3.0),
    )
    (episode,) = build_episodes(data, LOTS)
    assert (episode.closed, episode.broken, episode.n_fills) == (Ms(3_000), True, 2)


@pytest.mark.unit
def test_floating_point_residue_after_closing_closes_the_episode() -> None:
    """Compra de 0,3 e venda de 0,3 com start 0,30000000000000004: sobra -5,55e-17. Abaixo de
    meio lote no primeiro dex (lote 0,001) e de 1e-9 x 0,3 em HIP-3, é zero, e o episódio
    fecha. Sem a regra, ficaria um episódio aberto com uma posição fantasma.

    Mutação registrada: trocar `_is_zero` (ledger) por `position == 0.0` deixa o episódio
    aberto nos dois casos, e o teste cai.
    """
    for coin, lots in (("BTC", {"BTC": 0.001}), ("xyz:TSLA", {})):
        data = table(
            fill(1_000, coin, "B", 0.3, 100.0, 0.0),
            fill(2_000, coin, "A", 0.3, 100.0, 0.1 + 0.2),
        )
        (episode,) = build_episodes(data, lots)
        assert episode.closed == Ms(2_000), coin


@pytest.mark.unit
@pytest.mark.parametrize(
    ("declared", "second_side", "closed_first", "second_from_flat", "second_side_of_episode"),
    [
        # Declara zero com um episódio aberto: ele fecha onde se observa o zero, e o fill abre
        # um novo a partir de zero. Compra de 2 a 101 com start 0: de 0 a 2.
        (0.0, "B", True, True, 1),
        # Declara -3 com +5 aberto: lado oposto. Fecha o aberto; o novo existe sem que a
        # abertura tenha sido vista (não é de zero). Venda de 1 a 101 com start -3: de -3 a -4.
        (-3.0, "A", True, False, -1),
        # Declara +3 com +5 aberto: mesmo lado, o episódio continua (só `broken`).
        (3.0, "A", False, True, 1),
    ],
)
def test_broken_episode_is_closed_or_reopened_without_interpolation(
    declared: float,
    second_side: str,
    closed_first: bool,
    second_from_flat: bool,
    second_side_of_episode: int,
) -> None:
    """Design §3.5, "Mudança não observada e episódio". Compra de 5 a 100 em t = 1.000 (de
    0 a 5). Em t = 3.000 um fill declara `declared` como start, que não é o 5 que se tinha.

    Zero declarado, lado oposto: o episódio de 1.000 se fecha em 3.000 (o instante em que o
      declarado é observado, sem interpolar), `broken`, com só o fill de 1.000 (n_fills 1,
      negociado 5 x 100 = 500, last_seq 0). O fill de 3.000 começa outro: `opened_from_flat`
      só se o declarado é zero, e `broken` só se foi criado por mudança não observada.
    Mesmo lado: um episódio só, aberto, `broken`, com os dois fills.

    Mutação registrada: não fechar o episódio quando o declarado é zero (a guarda
    `before != 0.0 and sign(before) != current.side` em `build_episodes`) deixa um episódio
    com os dois fills, e o primeiro caso cai.
    """
    data = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(3_000, "BTC", second_side, 2.0 if second_side == "B" else 1.0, 101.0, declared),
    )
    episodes = build_episodes(data, LOTS)
    if not closed_first:
        (only,) = episodes
        assert (only.broken, only.closed, only.n_fills) == (True, None, 2)
        return
    first, second = episodes
    assert (first.opened, first.closed, first.broken) == (Ms(1_000), Ms(3_000), True)
    assert (first.n_fills, first.last_seq) == (1, 0)
    assert first.traded_notional == pytest.approx(500.0)
    assert (second.opened, second.opened_from_flat, second.side) == (
        Ms(3_000),
        second_from_flat,
        second_side_of_episode,
    )
    assert second.first_seq == 1
    assert second.broken == (not second_from_flat)


@pytest.mark.unit
def test_position_opened_without_being_seen_is_a_broken_pre_existing_episode() -> None:
    """Fechou (de 5 a zero, episódio normal) e o próximo fill declara start 4: a abertura não
    foi vista. Esperado zero, declarado 4: quebra. O novo episódio não é de zero e é
    `broken`; o primeiro fechou normalmente e não é."""
    data = table(
        fill(1_000, "BTC", "B", 5.0, 100.0, 0.0),
        fill(2_000, "BTC", "A", 5.0, 100.0, 5.0),
        fill(3_000, "BTC", "A", 1.0, 100.0, 4.0),
    )
    closed, unseen = build_episodes(data, LOTS)
    assert (closed.broken, closed.closed) == (False, Ms(2_000))
    assert (unseen.opened_from_flat, unseen.broken, unseen.side) == (False, True, 1)
    assert len(continuity_breaks(data, LOTS)) == 1
