"""Arquivo de custos e meio-spread ponderado pelo tempo (T-062, design 1.7 §3.9;
RF-COL-05 CA-05.2). Fixtures de papel: nenhum dado real.

Convenção: o dia ``D`` é o dia UTC 20.000 (``D0 = 20.000 * 86.400.000 ms``), e os instantes das
fixtures são relativos a ``D0``. O meio-spread é ``(venda - compra) / (venda + compra) * 10^4``
bps. Com compra + venda = 200, os três pares abaixo dão valores exatos em ponto flutuante:

    compra 99,5   venda 100,5   -> 1 / 200     * 10^4 = 50   bps
    compra 99,75  venda 100,25  -> 0,5 / 200   * 10^4 = 25   bps
    compra 99,875 venda 100,125 -> 0,25 / 200  * 10^4 = 12,5 bps

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em `copylab.costs`
(as mutações de cada teste estão na docstring dele).
"""

import json
from collections.abc import Sequence

import polars as pl
import pytest

from copylab.costs import (
    DEFAULT_COSTS_PATH,
    CostEntry,
    add_new,
    dump_costs,
    half_spread_bps,
    parse_costs,
)
from copylab.exceptions import ConfigError, DataError
from copylab.timeutil import MS_PER_DAY, day_start

DAY = 20_000
D0 = day_start(DAY)
HS = {50.0: (99.5, 100.5), 25.0: (99.75, 100.25), 12.5: (99.875, 100.125)}
HASH = "ab" * 32


def bbo(*rows: tuple[int, float]) -> pl.DataFrame:
    """Observações ``(instante relativo a D0, meio-spread em bps)`` como a tabela do coletor."""
    return pl.DataFrame(
        {
            "time_ms": [D0 + t for t, _ in rows],
            "bid_px": [HS[v][0] for _, v in rows],
            "ask_px": [HS[v][1] for _, v in rows],
        },
        schema={"time_ms": pl.Int64, "bid_px": pl.Float64, "ask_px": pl.Float64},
    )


def gaps(*spans: tuple[int, int]) -> list[tuple[int, int]]:
    return [(D0 + a, D0 + b) for a, b in spans]


# ─── Meio-spread ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_half_spread_median_is_time_weighted() -> None:
    """RF-COL-05 CA-05.2: a mediana é pelo tempo, e não pela contagem de observações.

    Observações no dia D: 50 bps em 0, 12,5 bps em 80.000.000 e 25 bps em 80.001.000; o dia
    acaba em 86.400.000. Pesos: 80.000.000 ms, 1.000 ms e 6.399.000 ms; total 86.400.000.
    Em ordem de valor: 12,5 (1.000), 25 (6.400.000 acumulados), 50 (86.400.000). A mediana
    ponderada é o menor valor com 100 x acumulado >= 50 x total, isto é, acumulado >= 43.200.000:
    só o 50. A mediana sem pesos dos três valores seria 25.

    Mutação: peso 1 por observação (em vez do tempo): devolveu 25, o teste caiu.
    """
    result = half_spread_bps(bbo((0, 50.0), (80_000_000, 12.5), (80_001_000, 25.0)), [], [DAY])
    assert result.value_bps == pytest.approx(50.0)


@pytest.mark.unit
def test_last_observation_weighs_until_the_end_of_the_day() -> None:
    """A última observação do dia pesa até a meia-noite seguinte.

    A (50 bps) em 0 e B (12,5 bps) em 40.000.000; o dia acaba em 86.400.000. A pesa 40.000.000 e
    B pesa 46.400.000. O 12,5 tem 46.400.000 >= 43.200.000 (metade do total) e vence. Sem contar
    o fim do dia, só A teria peso, e o resultado seria 50.

    Mutação: último intervalo com peso zero: devolveu 50, o teste caiu.
    """
    assert half_spread_bps(
        bbo((0, 50.0), (40_000_000, 12.5)), [], [DAY]
    ).value_bps == pytest.approx(12.5)


@pytest.mark.unit
def test_time_inside_a_gap_does_not_count() -> None:
    """Sem contar tempo dentro de lacuna (RF-COL-05 CA-05.2).

    Duas observações no dia D: X (50 bps) em 0 e Y (12,5 bps) em 40.000.000; o dia acaba em
    86.400.000. X pesa o intervalo [0, 40M) e Y pesa [40M, 86,4M), menos o que cai em lacuna.
    Como há dois valores, o 12,5 vence só se o peso de Y é pelo menos o de X (100 x peso(Y) >=
    50 x total); senão, é o 50.

    a) sem lacuna: X = 40M, Y = 46,4M -> 12,5.
    b) lacuna [35M, 52M): X perde 5M (35M) e Y perde 12M (34,4M) -> Y < X -> 50.
    c) lacuna [32M, 52M): X perde 8M (32M) e Y perde 12M (34,4M) -> Y >= X -> 12,5.
    d) lacunas [35M, 45M) e [40M, 52M) se sobrepõem e valem a união [35M, 52M): o mesmo que b.
       X = 35M, Y = 34,4M -> 50. Sem unir, a segunda lacuna contaria o trecho [40M, 45M) duas
       vezes: X perderia 10M (30M) e Y, 12M (34,4M), e daria 12,5.
    e) lacuna [50M, 86,4M): X = 40M, Y perde 36,4M (10M) -> 50.

    Mutações: lacunas ignoradas (`merged = []`): caiu em (b). Lacunas sem unir: caiu em (d).
    Lacuna contada inteira assim que começa, sem o pedaço que já passou: caiu em (b).
    """
    rows = bbo((0, 50.0), (40_000_000, 12.5))
    m = 1_000_000
    assert half_spread_bps(rows, [], [DAY]).value_bps == pytest.approx(12.5)
    assert half_spread_bps(rows, gaps((35 * m, 52 * m)), [DAY]).value_bps == pytest.approx(50.0)
    assert half_spread_bps(rows, gaps((32 * m, 52 * m)), [DAY]).value_bps == pytest.approx(12.5)
    assert half_spread_bps(rows, gaps((35 * m, 45 * m), (40 * m, 52 * m)), [DAY]).value_bps == (
        pytest.approx(50.0)
    )
    assert half_spread_bps(rows, gaps((50 * m, 86_400_000)), [DAY]).value_bps == pytest.approx(50.0)


@pytest.mark.unit
def test_gap_spanning_the_start_or_end_of_the_day_is_clipped_to_the_day() -> None:
    """Uma lacuna que começa antes do dia ou termina depois dele só conta a parte do dia.

    Observações X (50) em 0 e Y (12,5) em 40M, como acima. Lacuna [-10M, 50M): X perde os 40M
    do seu intervalo inteiro (peso 0) e Y perde [40M, 50M) = 10M (36,4M): só Y conta, 12,5.
    Lacuna [50M, 200M) (acaba depois do dia): Y perde [50M, 86,4M) = 36,4M (10M), X = 40M -> 50.
    """
    rows = bbo((0, 50.0), (40_000_000, 12.5))
    m = 1_000_000
    before = [(D0 - 10 * m, D0 + 50 * m)]
    after = [(D0 + 50 * m, D0 + 200 * m)]
    assert half_spread_bps(rows, before, [DAY]).value_bps == pytest.approx(12.5)
    assert half_spread_bps(rows, after, [DAY]).value_bps == pytest.approx(50.0)


@pytest.mark.unit
def test_only_the_given_days_enter() -> None:
    """Dias D, D+1 e D+2 com uma observação cada: 50, 25 e 12,5 bps, desde a meia-noite.

    Com ``days = [D, D+2]``, cada dia pesa 86.400.000 e há dois valores (12,5 e 50): o menor
    com 100 x acumulado >= 50 x 172.800.000 é o 12,5 (86.400.000 >= 86.400.000, inclusivo). O
    dia D+1 fica de fora; com ele seriam três valores de peso igual e a mediana seria 25.

    Mutação: filtro do dia sem o limite superior (`>= start`): devolveu 25, o teste caiu.
    """
    day = MS_PER_DAY
    rows = bbo((0, 50.0), (day, 25.0), (2 * day, 12.5))
    assert half_spread_bps(rows, [], [DAY, DAY + 2]).value_bps == pytest.approx(12.5)
    assert half_spread_bps(rows, [], [DAY, DAY + 1, DAY + 2]).value_bps == pytest.approx(25.0)


@pytest.mark.unit
def test_locked_book_is_zero_spread_and_invalid_quotes_are_skipped_and_counted() -> None:
    """Design 1.8: compra igual à venda vale (zero); cotação inválida é pulada e contada.

    Fila: A (12,5 bps) em 0, uma cotação inválida em 20M, C (50 bps) em 60M; o dia acaba em
    86,4M. A pesa [0, 20M) = 20M e C pesa [60M, 86,4M) = 26,4M; o tempo [20M, 60M) é da cotação
    inválida e não pesa. Total 46,4M, metade 23,2M: o 12,5 acumula 20M, e a mediana é 50. Se a
    cotação inválida fosse apagada antes da conta, A pesaria até 60M (40M) e a mediana seria 12,5.
    Vale para os cinco tipos de cotação inválida; cada um conta 1.

    Mutação: apagar a linha inválida antes de calcular os pesos: o teste caiu.
    """
    locked = pl.DataFrame(
        {"time_ms": [D0], "bid_px": [100.0], "ask_px": [100.0]},
        schema={"time_ms": pl.Int64, "bid_px": pl.Float64, "ask_px": pl.Float64},
    )
    result = half_spread_bps(locked, [], [DAY])
    assert (result.value_bps, result.skipped) == (0.0, 0)
    for bid, ask in ((101.0, 100.0), (0.0, 100.0), (-1.0, 100.0), (100.0, None), (None, 100.0)):
        rows = pl.DataFrame(
            {
                "time_ms": [D0, D0 + 20_000_000, D0 + 60_000_000],
                "bid_px": [99.875, bid, 99.5],
                "ask_px": [100.125, ask, 100.5],
            },
            schema={"time_ms": pl.Int64, "bid_px": pl.Float64, "ask_px": pl.Float64},
        )
        result = half_spread_bps(rows, [], [DAY])
        assert result.value_bps == pytest.approx(50.0), (bid, ask)
        assert result.skipped == 1


@pytest.mark.unit
def test_no_observation_or_no_time_outside_gaps_is_a_data_error() -> None:
    with pytest.raises(DataError, match="Nenhuma observação"):
        half_spread_bps(bbo((0, 50.0)), [], [DAY + 1])
    with pytest.raises(DataError, match="fora de lacuna"):
        half_spread_bps(bbo((0, 50.0)), gaps((0, MS_PER_DAY)), [DAY])


# ─── Arquivo ─────────────────────────────────────────────────────────────────


def entry(value: float = 1.5, days: Sequence[int] = (DAY, DAY + 1, DAY + 2)) -> CostEntry:
    return CostEntry(value, tuple(days), HASH)


@pytest.mark.unit
def test_cost_file_round_trips_with_ordered_keys_and_dates() -> None:
    costs = {"ETH": entry(2.0), "BTC": entry(0.25)}
    text = dump_costs(costs)
    # 20.000 = dia 2024-10-04 (conta: 2024-01-01 é o dia 19.723; mais 31+29+31+30+31+30+31+31+30
    # = 274 até 10-01; 19.723 + 274 = 19.997; mais 3 dias = 20.000 -> 2024-10-04).
    assert '"2024-10-04"' in text
    assert text.index('"BTC"') < text.index('"ETH"')
    assert text.endswith("\n")
    assert parse_costs(text) == costs
    assert dump_costs(parse_costs(text)) == text


def one(**override: object) -> str:
    """Um arquivo com BTC válido, com campos trocados por ``override`` (``None`` tira o campo)."""
    entry: dict[str, object] = {
        "half_spread_bps": 1.0,
        "days": ["2024-10-04"],
        "data_hash": HASH,
        "skipped_observations": 0,
    }
    entry.update(override)
    return json.dumps({"BTC": {k: v for k, v in entry.items() if v is not None}})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[]", "objeto"),
        ("{", "JSON"),
        ('{"BTC": 1}', "chaves"),
        (one(skipped_observations=-1), "skipped_observations"),
        (one(skipped_observations=None), "chaves"),
        (one(half_spread_bps=-1.0), "não neg"),
        (one(half_spread_bps=True), "não neg"),
        (one(days=[]), "lista não vazia"),
        (one(days=["2024-10-05", "2024-10-04"]), "fora de ordem"),
        (one(days=["2024-10-04", "2024-10-04"]), "repetido"),
        (one(data_hash="x"), "sha256"),
        (one(days=["04/10/2024"]), "Data"),
        (one()[:-1] + ', "BTC": 2}', "repetida"),
    ],
)
def test_malformed_cost_file_is_config_error(text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_costs(text)


@pytest.mark.unit
def test_add_new_keeps_existing_values_and_refuses_to_change_one() -> None:
    """RF-COL-05 CA-05.2: o valor gravado nunca muda; só entram ativos que faltam.

    Mutação: sem a checagem de choque (`clash = []`): a tentativa de mudar BTC passou, o teste
    caiu.
    """
    existing = {"BTC": entry(0.25)}
    merged = add_new(existing, {"ETH": entry(2.0)})
    assert merged == {"BTC": entry(0.25), "ETH": entry(2.0)}
    assert existing == {"BTC": entry(0.25)}  # o argumento não é alterado
    with pytest.raises(ConfigError, match="já estão gravados"):
        add_new(existing, {"BTC": entry(9.0)})
    with pytest.raises(ConfigError, match="já estão gravados"):
        add_new(existing, {"BTC": entry(0.25)})  # nem igual: quem mede de novo errou o fluxo


@pytest.mark.unit
def test_default_path_is_the_preregistration_file() -> None:
    assert str(DEFAULT_COSTS_PATH) == "preregistro/custos.json"
