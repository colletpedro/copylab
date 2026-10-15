"""Fatos por carteira (T-063; design 1.7 §3.6, "Fatos por carteira"). Fixtures de papel.

A carteira de base tem 8 blocos de 7 dias com 3 episódios de BTC cada, abertos a mercado: uma
compra de 1 a 100 e, 2 h depois, uma venda de 1 a 101 com ``closed_pnl`` 1,0. Em cada episódio:

- notional negociado 100 + 101 = 201 e notional de abertura 100; 24 episódios, 48 fills;
- duração 2 h = 7.200.000 ms; PnL reconstruído por custo médio 1 x (101 - 100) = 1,0, igual ao
  informado: divergência 0 bps; nenhuma quebra de continuidade (a venda declara posição 1,0);
- um perpétuo aberto durante 2 h de cada 7 dias, então a mediana do número de abertos, sobre o
  tempo em posição, é 1.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em
``copylab.selection.facts`` (as mutações de cada teste estão na docstring dele).
"""

import polars as pl
import pytest
from tests.unit.selection_support import (
    W56,
    WALLET,
    at_start,
    facts_of,
    fill_row,
    round_trips,
)

from copylab.selection.facts import lots_from_meta
from copylab.storage.tables import META, SCHEMAS
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR

BASE = [3] * 8


@pytest.mark.unit
def test_lot_is_ten_to_the_minus_sz_decimals() -> None:
    meta = pl.DataFrame({"coin": ["BTC", "kPEPE"], "sz_decimals": [5, 0]}, schema=SCHEMAS[META])
    assert lots_from_meta(meta) == {"BTC": pytest.approx(1e-5), "kPEPE": 1.0}


@pytest.mark.unit
def test_base_wallet_facts() -> None:
    facts = facts_of(round_trips(BASE))
    assert facts.coverage_ok
    assert facts.n_fills == 48
    assert (facts.invalid_perp_fills, facts.universe_breaks, facts.unreconciled_episodes) == (
        0,
        0,
        0,
    )
    assert facts.max_pnl_divergence_bps == 0.0
    assert facts.closed_episodes == 24
    assert len(facts.open_times) == 24
    assert facts.median_duration_ms == 2 * MS_PER_HOUR
    assert facts.taker_opening_share == 1.0
    assert facts.median_open_perps == 1.0
    assert facts.universe_notional_share == 1.0
    assert facts.liquidated_fills == 0
    assert facts.window_end == W56.end


@pytest.mark.unit
def test_only_universe_episodes_count_and_open_ones_are_not_closed() -> None:
    """F4 e F6 contam só episódios do universo abertos de zero e fechados; F5 e F7 contam também os
    abertos até o fim (design 1.7).

    Três episódios de BTC fechados (duração 2 h) e um quarto aberto até o fim; mais um episódio de
    ETH (fora do universo), fechado. Fechados do universo: 3, mediana 2 h. Aberturas do universo: 4.
    Abertura: 4 x 100 de notional, todos a mercado salvo o aberto, que não é: taker = 300 / 400.

    Mutação: contar o episódio de ETH (sem o filtro do universo): closed_episodes deu 4, caiu.
    Mutação: contar o aberto como fechado: deu 4 e a mediana mudou, caiu.
    """
    rows = round_trips([3])
    rows.append(fill_row(W56.start + 20 * MS_PER_DAY, "BTC", "B", 1.0, 100.0, 0.0, crossed=False))
    rows += [
        fill_row(W56.start + 2 * MS_PER_DAY, "ETH", "B", 1.0, 50.0, 0.0),
        fill_row(W56.start + 3 * MS_PER_DAY, "ETH", "A", 1.0, 51.0, 1.0, pnl=1.0),
    ]
    facts = facts_of(rows)
    assert facts.closed_episodes == 3
    assert len(facts.open_times) == 4
    assert facts.median_duration_ms == 2 * MS_PER_HOUR
    assert facts.taker_opening_share == pytest.approx(300 / 400)


@pytest.mark.unit
def test_continuity_break_and_unreconciled_episode_in_the_universe() -> None:
    """A venda do 4º episódio declara posição 5,0 onde se tinha 1,0: quebra. A posição passa a 5,0
    e a venda a deixa em 4,0; a abertura seguinte declara 0,0: outra quebra. São 2 quebras, e o 4º
    episódio, fechado na abertura seguinte, é `broken`: sem divergência de PnL calculável, conta
    como não conciliado (1).

    Mutação: `unreconciled_episodes` ignorando a divergência `None`: deu 0, caiu. Mutação: contar
    quebras de todos os ativos (sem o filtro do universo): o teste abaixo, com ETH, caiu.
    """
    facts = facts_of(round_trips(BASE, break_at=3))
    assert facts.universe_breaks == 2
    assert facts.unreconciled_episodes == 1
    outside = [
        *round_trips(BASE),
        fill_row(W56.start + MS_PER_HOUR, "ETH", "B", 1.0, 50.0, 0.0),
        fill_row(W56.start + 2 * MS_PER_HOUR, "ETH", "A", 1.0, 51.0, 7.0, pnl=1.0),
    ]
    assert facts_of(outside).universe_breaks == 0


@pytest.mark.unit
def test_pnl_divergence_is_the_largest_over_reconciled_episodes() -> None:
    """Uma venda informa 5,0 de PnL onde o custo médio dá 1,0: divergência |1 - 5| / 201 x 10^4 =
    199,0049... bps (notional negociado do episódio: 100 + 101 = 201)."""
    facts = facts_of(round_trips(BASE, pnl_error=4.0, error_at=7))
    assert facts.max_pnl_divergence_bps == pytest.approx(4.0 / 201 * 10_000)
    assert facts.unreconciled_episodes == 0


@pytest.mark.unit
def test_median_open_perps_is_time_weighted_over_time_in_position() -> None:
    """F8. BTC aberto por 39 dias a partir de 1 h, ETH aberto de 1 h até o fim (56 dias).

    Tempo em posição: de 1 h a 56 dias (ETH sempre aberto). Com 2 abertos: 39 dias; com 1 aberto:
    de 39 dias + 1 h a 56 dias = 17 dias - 1 h. A mediana ponderada inferior é o menor valor com
    100 x acumulado >= 50 x total: com 1 aberto, 17 d - 1 h contra metade de 56 d - 1 h (28 d), não
    basta; com 2, sim. Mediana 2. Sem fill nenhum, `None`. Com ETH aberto e fechado em 1 h, só o
    BTC: mediana 1.

    Mutação: mediana dos valores sem peso (`median(list(weights))`: 1,5): o teste caiu.
    """
    rows = [*round_trips([1], duration_ms=39 * MS_PER_DAY), at_start("ETH")]
    assert facts_of(rows).median_open_perps == 2.0
    flat = facts_of(
        [at_start("ETH"), fill_row(W56.start + 2 * MS_PER_HOUR, "ETH", "A", 1.0, 1.0, 1.0)]
    )
    assert flat.median_open_perps == 1.0
    assert facts_of([]).median_open_perps is None


@pytest.mark.unit
def test_position_already_open_at_window_start_counts_from_the_start() -> None:
    """F8: um ativo cujo primeiro fill declara posição 1,0 está aberto desde o início da janela.

    ETH declara 1,0 no primeiro fill, 10 dias depois do início, e vende 1: aberto de 0 a 10 dias.
    BTC fica aberto 8 dias a partir de 1 h. Com 2 abertos: 8 dias; com 1 aberto: 1 h + o resto até
    o dia 10 (cerca de 2 dias). Tempo em posição: 10 dias; metade, 5 dias: o 1 acumula 2 dias, e a
    mediana é 2. Sem contar o ETH antes do primeiro fill dele, só o BTC conta, e a mediana é 1.

    Mutação: ativo sem posição anterior declarada no início (`setdefault(..., False)`): a mediana
    deu 1, e o teste caiu.
    """
    rows = [fill_row(W56.start + 10 * MS_PER_DAY, "ETH", "A", 1.0, 50.0, 1.0, pnl=1.0)]
    rows += round_trips([1], duration_ms=8 * MS_PER_DAY)
    assert facts_of(rows).median_open_perps == 2.0


@pytest.mark.unit
def test_universe_share_liquidations_and_invalid_fills() -> None:
    """F9: 4.824 de BTC contra 4.824 de ETH: 50% exatos. F10: fill de liquidação do próprio
    endereço (a comparação ignora maiúsculas). F3: fill de perpétuo do primeiro dex sem preço."""
    rows = round_trips(BASE)
    rows.append(at_start("ETH", px=4_824.0, liquidated_user=WALLET.upper()))
    rows.append(at_start("SOL", px=None))  # fill sem preço, de propósito
    facts = facts_of(rows)
    assert facts.universe_notional_share == 0.5
    assert facts.liquidated_fills == 1
    assert facts.invalid_perp_fills == 1


@pytest.mark.unit
def test_wallet_without_fills_has_undefined_measures() -> None:
    facts = facts_of([])
    assert facts.n_fills == 0
    assert facts.closed_episodes == 0
    assert facts.median_duration_ms is None
    assert facts.taker_opening_share is None
    assert facts.universe_notional_share is None
