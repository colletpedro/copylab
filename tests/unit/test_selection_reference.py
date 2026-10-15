"""Referência de exposição N* (T-064; RF-SEL-03 CA-03.1 e CA-03.2, RF-SEL-01 CA-01.2, ADR-0007).
Fixtures de papel: a janela são os 56 dias de `W56`, com `T0` = início + 1 h, e `H` = 1 hora.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em
``copylab.selection.reference`` (as mutações de cada teste estão na docstring dele).
"""

import pytest
from tests.unit.selection_support import (
    LOTS,
    W56,
    FakeRepository,
    fill_row,
    fills_table,
    real_params,
)

from copylab.exceptions import LookaheadError
from copylab.ports import BoundedRepository
from copylab.selection.reference import Reference, reference_exposure
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms
from copylab.windows import Window

H = MS_PER_HOUR
T0 = W56.start + H
UNIVERSE = frozenset({"BTC", "ETH"})


def n_star(*rows: dict[str, object], pct: int = 95, window: Window = W56) -> Reference | None:
    return reference_exposure(fills_table(*rows), LOTS, UNIVERSE, window, pct)


def ladder() -> list[dict[str, object]]:
    """Compra de 1 a 100 em T0, compra de 1 a 110 em T0 + 10 h (posição 2) e venda de 2 a 120 em
    T0 + 20 h (zera)."""
    return [
        fill_row(T0, "BTC", "B", 1.0, 100.0, 0.0),
        fill_row(T0 + 10 * H, "BTC", "B", 1.0, 110.0, 1.0),
        fill_row(T0 + 20 * H, "BTC", "A", 2.0, 120.0, 2.0),
    ]


@pytest.mark.unit
def test_reference_exposure_is_time_weighted_p95_over_time_in_position() -> None:
    """RF-SEL-03 CA-03.1. Na escada: em [T0, T0 + 10 h) a exposição é 1 x 100 = 100; em
    [T0 + 10 h, T0 + 20 h) é 2 x 110 = 220 (a posição inteira ao preço do último fill); depois,
    zero. Tempo em posição: 20 h. Com p95: o menor valor com 100 x acumulado >= 95 x 20 h; o 100
    acumula 10 h (1.000 < 1.900), o 220 acumula 20 h: N* = 220. Com p50: 1.000 >= 50 x 20 = 1.000,
    inclusivo: N* = 100. Horas em posição: 20.

    Mutações: preço do ativo preso ao primeiro fill (a posição inteira a 100: 2 x 100 = 200): N*
    deu 200, caiu. Tempo sem posição entrando nos pesos (sem o `current > 0`): caiu.
    """
    result = n_star(*ladder())
    assert result == Reference(220.0, 20.0)
    median = n_star(*ladder(), pct=50)
    assert median is not None
    assert median.n_star == 100.0


@pytest.mark.unit
def test_reference_exposure_ignores_flat_time() -> None:
    """ADR-0007: acrescentar tempo sem posição não altera N*. A mesma escada com a janela acabando
    1 h depois da venda, e com a janela de 56 dias: o mesmo N* e as mesmas 20 horas.

    Mutação: contar o tempo sem posição como exposição zero no percentil (sem o `current > 0`): N*
    do p95 passou a depender do tamanho da janela, e o teste caiu (com 56 dias, o p95 cairia em
    zero).
    """
    short = Window(W56.start, Ms(T0 + 21 * H))
    assert n_star(*ladder(), window=short) == n_star(*ladder())
    assert n_star(*ladder(), window=short) == Reference(220.0, 20.0)


@pytest.mark.unit
def test_position_open_at_window_start_is_valued_at_the_price_of_its_first_fill() -> None:
    """A posição que já existia no início da janela vale ao preço do primeiro fill dela. O primeiro
    fill do BTC é uma venda de 1 a 105, 10 h depois do início, declarando posição 1,0: de início da
    janela a esse fill a exposição é 1 x 105 = 105, por 10 h. N* = 105, 10 h.

    Mutação: posição anterior ao primeiro fill tratada como zero: não há tempo em posição e o
    resultado foi `None`; caiu.
    """
    result = n_star(fill_row(W56.start + 10 * H, "BTC", "A", 1.0, 105.0, 1.0, pnl=5.0))
    assert result == Reference(105.0, 10.0)


@pytest.mark.unit
def test_position_open_at_window_end_counts_until_the_end() -> None:
    """Uma compra de 1 a 100 em T0 que não fecha: exposição 100 de T0 até o fim da janela, que são
    56 x 24 - 1 = 1.343 horas."""
    assert n_star(fill_row(T0, "BTC", "B", 1.0, 100.0, 0.0)) == Reference(100.0, 1_343.0)


@pytest.mark.unit
def test_exposure_sums_the_universe_assets_and_ignores_the_rest() -> None:
    """BTC 1 a 100 de T0 a T0 + 10 h; ETH 2 a 50 de T0 + 5 h a T0 + 15 h; SOL (fora do universo)
    aberto o tempo todo. Exposição: [0, 5 h) 100, [5 h, 10 h) 100 + 100 = 200, [10 h, 15 h) 100.
    Pesos: 100 por 10 h, 200 por 5 h; total 15 h. p95: 100 x 10 h = 1.000 < 95 x 15 = 1.425, então
    200. p60: 1.000 >= 60 x 15 = 900, então 100. A SOL não entra, nem como tempo em posição.

    Mutação: somar também os ativos fora do universo: N* deu mais, caiu.
    """
    rows = [
        fill_row(T0, "BTC", "B", 1.0, 100.0, 0.0),
        fill_row(T0, "SOL", "B", 1.0, 9_999.0, 0.0),
        fill_row(T0 + 5 * H, "ETH", "B", 2.0, 50.0, 0.0),
        fill_row(T0 + 10 * H, "BTC", "A", 1.0, 100.0, 1.0, pnl=0.0),
        fill_row(T0 + 15 * H, "ETH", "A", 2.0, 50.0, 2.0, pnl=0.0),
    ]
    assert n_star(*rows) == Reference(200.0, 15.0)
    sixty = n_star(*rows, pct=60)
    assert sixty is not None
    assert sixty.n_star == 100.0


@pytest.mark.unit
def test_wallet_without_reference_exposure_is_ineligible() -> None:
    """RF-SEL-03 CA-03.2: sem posição no universo, N* é indefinido (`None`), e o estágio `N*` do
    funil remove a carteira (ver `test_n_star_stage_removes_wallets_without_reference`)."""
    assert n_star() is None
    assert n_star(fill_row(T0, "SOL", "B", 1.0, 100.0, 0.0)) is None
    assert (
        n_star(fill_row(T0, "BTC", "B", 1.0, 100.0, 0.0), window=Window(W56.start, Ms(T0))) is None
    )


@pytest.mark.unit
def test_percentile_comes_from_the_parameter_file() -> None:
    """O percentil vem de `[reference] percentile_pct`: trocá-lo no arquivo muda N* (design 1.8)."""
    params = real_params()
    assert params.reference.percentile_pct == 95
    other = params.model_copy(
        update={"reference": params.reference.model_copy(update={"percentile_pct": 50})}
    )
    rows = fills_table(*ladder())
    for p, expected in ((params, 220.0), (other, 100.0)):
        result = reference_exposure(rows, LOTS, UNIVERSE, W56, p.reference.percentile_pct)
        assert result is not None
        assert result.n_star == expected


@pytest.mark.unit
def test_reference_exposure_ignores_data_at_or_after_cutoff() -> None:
    """RF-SEL-01 CA-01.2, na parte da referência: alterar tudo a partir do corte não muda N*.

    Os fills lidos pelo `BoundedRepository` (corte = fim da janela). O repositório tem, além da
    escada, uma compra gigante em `fim + 1 dia`; a leitura da janela não a vê, e N* é o da escada.
    Ler com fim depois do corte levanta `LookaheadError`.
    """
    future = fill_row(W56.end + MS_PER_DAY, "BTC", "B", 1_000.0, 100_000.0, 0.0)
    plain = FakeRepository(fills={"0xW": fills_table(*ladder())})
    mutated = FakeRepository(fills={"0xW": fills_table(*ladder(), future)})
    results = []
    for repo in (plain, mutated):
        bounded = BoundedRepository(repo, W56.end)
        fills = bounded.fills("0xW", W56.start, W56.end)
        results.append(reference_exposure(fills, LOTS, UNIVERSE, W56, 95))
    assert results[0] == results[1] == Reference(220.0, 20.0)
    with pytest.raises(LookaheadError):
        BoundedRepository(mutated, W56.end).fills("0xW", W56.start, Ms(W56.end + MS_PER_DAY))
