"""Conferência do proxy contra os fills (T-061; RF-ING-06 CA-06.3 e CA-06.4). Fixtures de papel.

Os números são potências de dois, para a diferença em bps ser exata em ponto flutuante:
com o último do segundo em 128, um fill a 129 dá (129/128 - 1) x 10^4 = 0,0078125 x 10^4 =
78,125 bps, um a 127 dá -78,125 bps, um a 256 dá (2 - 1) x 10^4 = 10.000 bps, e um a 128 dá zero.

Os fills ficam todos no segundo ``S`` (``S`` = meia-noite do dia 20.000 mais 3.600 s), com o
proxy valendo 128 nele, salvo onde o teste diz outra coisa.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em
``copylab.selection.proxycheck`` (as mutações de cada teste estão na docstring dele).
"""

import polars as pl
import pytest
from tests.unit.selection_support import proxy_table

from copylab.selection.proxycheck import check_proxy
from copylab.timeutil import MS_PER_DAY, day_start

D0 = day_start(20_000)
S = (D0 + 3_600_000) // 1_000
LIMITS = {"max_deviation_p95_bps": 78.125, "max_level_bps": 78.125}


def fills(*pairs: tuple[int, float]) -> pl.DataFrame:
    """Fills ``(instante, preço)``."""
    return pl.DataFrame(
        {"time_ms": [t for t, _ in pairs], "px": [p for _, p in pairs]},
        schema={"time_ms": pl.Int64, "px": pl.Float64},
    )


def at(day: int, k: int = 0) -> int:
    """Um instante dentro do segundo ``S`` do dia ``20.000 + day``, ``k`` ms depois do início."""
    return D0 + day * MS_PER_DAY + 3_600_000 + k


def proxy_at(*days: int) -> pl.DataFrame:
    """Proxy a 128 no segundo ``S`` de cada dia dado."""
    return proxy_table([(S + d * MS_PER_DAY // 1_000, 128.0) for d in days])


@pytest.mark.unit
def test_proxy_invalid_on_dispersion_or_level() -> None:
    """RF-ING-06 CA-06.3: p95 do desvio em relação à mediana do dia, e nível pela mediana diária.

    **Dispersão.** Vinte fills no dia 0: 18 a 128 (0 bps), um a 129 (78,125) e um a 256 (10.000).
    Mediana do dia: ordenados, o 10º e o 11º são 0, então 0. Desvios: 18 zeros, 78,125 e 10.000.
    p95 = valor de posto ceil(95 x 20 / 100) = 19, o 19º desvio em ordem: 78,125. Com o limite
    em 78,125 vale (inclusivo); em 78,0 o ativo é inválido. O nível é 0.

    **Nível.** Três fills a 127 no dia 0 (-78,125 cada, mediana -78,125) e três a 128 no dia 1
    (mediana 0). Desvios todos 0. Nível = max(|-78,125|, |0|) = 78,125: válido com limite 78,125;
    inválido com 78,0 (o módulo conta: o maior valor com sinal seria 0).

    Mutações: p95 no máximo (``[-1]``): a dispersão deu 10.000 e o primeiro caso caiu. Nível pelo
    maior valor com sinal (sem ``abs``): o segundo caso aceitou 78,0 e caiu. Limiar exclusivo
    (``<`` no lugar de ``<=``): o limite exato de cada caso deixou de valer, e caiu.
    """
    spread = [(at(0, i), 128.0) for i in range(18)] + [(at(0, 18), 129.0), (at(0, 19), 256.0)]
    dispersed = check_proxy("X", fills(*spread), proxy_at(0), **LIMITS)
    assert dispersed.compared == 20
    assert dispersed.deviation_p95_bps == pytest.approx(78.125)
    assert dispersed.level_bps == pytest.approx(0.0)
    assert dispersed.valid
    tight = check_proxy(
        "X", fills(*spread), proxy_at(0), max_deviation_p95_bps=78.0, max_level_bps=78.125
    )
    assert not tight.valid

    shifted = [(at(0, i), 127.0) for i in range(3)] + [(at(1, i), 128.0) for i in range(3)]
    level = check_proxy("X", fills(*shifted), proxy_at(0, 1), **LIMITS)
    assert level.level_bps == pytest.approx(78.125)
    assert level.deviation_p95_bps == pytest.approx(0.0)
    assert level.valid
    too_high = check_proxy(
        "X", fills(*shifted), proxy_at(0, 1), max_deviation_p95_bps=78.125, max_level_bps=78.0
    )
    assert not too_high.valid


@pytest.mark.unit
def test_proxy_report_includes_daily_median_and_its_range() -> None:
    """RF-ING-06 CA-06.4: mediana diária, número de fills por dia e variação entre dias.

    Dia 0: três fills a 127 (-78,125 bps cada), mediana -78,125. Dia 1: dois fills, a 128 (0) e a
    129 (78,125); mediana de duas observações = média dos dois centrais = 39,0625. Dia 2: um
    fill a 256 (10.000), mediana 10.000. Variação = maior mediana - menor = 10.000 - (-78,125) =
    10.078,125. Nível = 10.000.

    Mutação: mediana inferior (o 1º dos dois centrais) no dia 1: deu 0 e o teste caiu.
    """
    rows = (
        [(at(0, i), 127.0) for i in range(3)]
        + [(at(1, 0), 128.0), (at(1, 1), 129.0)]
        + [(at(2, 0), 256.0)]
    )
    check = check_proxy("X", fills(*rows), proxy_at(0, 1, 2), **LIMITS)
    assert [(d.day, d.n_fills) for d in check.days] == [(20_000, 3), (20_001, 2), (20_002, 1)]
    assert [d.median_bps for d in check.days] == pytest.approx([-78.125, 39.0625, 10_000.0])
    assert check.shift_bps == pytest.approx(10_078.125)
    assert check.level_bps == pytest.approx(10_000.0)
    assert check.compared == 6


@pytest.mark.unit
def test_fill_in_a_second_without_trade_is_skipped_and_counted() -> None:
    """Três fills no segundo ``S`` (proxy a 128), um no segundo seguinte, que não tem negócio, e
    um fill sem preço no segundo ``S``. Comparados: 3. Pulados: 2 (o do segundo sem negócio e o
    sem preço). Os pulados não entram em mediana nem em desvio.

    Mutação: preencher o segundo vazio com o último anterior: ``compared`` deu 4 e caiu.
    """
    rows = pl.DataFrame(
        {
            "time_ms": [at(0, 0), at(0, 1), at(0, 2), at(0, 1_500), at(0, 3)],
            "px": [128.0, 128.0, 129.0, 129.0, None],
        },
        schema={"time_ms": pl.Int64, "px": pl.Float64},
    )
    check = check_proxy("X", rows, proxy_at(0), **LIMITS)
    assert (check.compared, check.skipped) == (3, 2)
    # Diferenças 0, 0 e 78,125: mediana 0; desvios 0, 0 e 78,125; p95 de 3 = posto 3 = 78,125.
    assert check.deviation_p95_bps == pytest.approx(78.125)


@pytest.mark.unit
def test_asset_without_any_comparable_fill_is_invalid() -> None:
    check = check_proxy("X", fills((at(0, 1_500), 128.0)), proxy_at(0), **LIMITS)
    assert (check.compared, check.skipped, check.valid) == (0, 1, False)
    assert check.deviation_p95_bps is None
    assert check.level_bps is None
    assert check.days == ()
