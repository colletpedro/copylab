"""Diagnóstico das quebras de continuidade (T-032, design §3.5; RF-ING-03 CA-03.4).

Fixtures de papel: as idades, as janelas de vizinhança e as contagens esperadas estão
calculadas no comentário de cada teste. Nenhum dado real.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação por vez em
`copylab.leader.diagnostics` (cada uma está na docstring do teste que a pega).
"""

from typing import Any

import polars as pl
import pytest

from copylab.exceptions import ConfigError, DataError
from copylab.leader import Break, break_report, continuity_breaks
from copylab.storage.tables import SCHEMAS
from copylab.timeutil import Ms

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


def twap_table(*rows: tuple[str, int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "coin": [r[0] for r in rows],
            "time_ms": [r[1] for r in rows],
            "twap_id": [1] * len(rows),
        },
        schema={"coin": pl.String, "time_ms": pl.Int64, "twap_id": pl.Int64},
    )


def brk(coin: str, prev_t: int, t: int) -> Break:
    return Break(Ms(t), Ms(prev_t), coin, "perp", 5.0, 3.0)


@pytest.mark.unit
def test_break_report_groups_by_age_and_twap_neighbourhood() -> None:
    """RF-ING-03 CA-03.4. Coleta em 1.000.000; faixas [0, 200.000), [200.000, 600.000),
    [600.000, ∞); vizinhança de 5.000.
      b1 BTC t = 900.000: idade 100.000, faixa 0.
      b2 BTC t = 500.000 (fill anterior 400.000): idade 500.000, faixa 1.
      b3 ETH t = 300.000 (anterior 290.000): idade 700.000, faixa 2.
      b4 ETH t = 800.000 (anterior 799.000): idade 200.000, que é o limite: faixa 1 (a faixa
        é fechada à esquerda).
    Fills de TWAP: BTC em 395.000 = 400.000 - 5.000, dentro da janela de b2 [395.000, 505.000]
    (a borda conta); ETH em 805.000 = 800.000 + 5.000, dentro da janela de b4 [794.000,
    805.000]; ETH em 306.000, fora da de b3 [285.000, 305.000]; ETH em 890.000, que é de
    outro ativo e não conta para b1 (BTC), cuja janela é [875.000, 905.000].
    Esperado: faixa 0: 1 quebra, 0 com TWAP. Faixa 1: 2 e 2. Faixa 2: 1 e 0. Total 4 e 2.

    Mutação registrada: ignorar o ativo na vizinhança (os TWAP de todos os ativos juntos, em
    `break_report`) faz b1 contar o TWAP de ETH em 890.000, e o teste cai; trocar
    `bisect_right` por `bisect_left` na faixa move b4 (idade no limite) para a faixa 0, e
    também cai.
    """
    report = break_report(
        [
            brk("BTC", 880_000, 900_000),
            brk("BTC", 400_000, 500_000),
            brk("ETH", 290_000, 300_000),
            brk("ETH", 799_000, 800_000),
        ],
        twap_table(("BTC", 395_000), ("ETH", 805_000), ("ETH", 306_000), ("ETH", 890_000)),
        Ms(1_000_000),
        neighbourhood_ms=5_000,
        age_edges_ms=[200_000, 600_000],
    )
    assert [(b.age_from_ms, b.age_to_ms, b.breaks, b.with_twap) for b in report.by_age] == [
        (0, 200_000, 1, 0),
        (200_000, 600_000, 2, 2),
        (600_000, None, 1, 0),
    ]
    assert (report.total, report.with_twap) == (4, 2)


@pytest.mark.unit
def test_break_report_over_breaks_found_in_real_shaped_fills() -> None:
    """Das quebras que `continuity_breaks` acha. BTC: compra de 5 em 1.000 (fill de TWAP),
    e venda de 3 em 3.000 com start 3: quebra com fill anterior em 1.000. Coleta em 10.000,
    idade 7.000, e uma faixa só a partir de 5.000: a quebra cai na faixa [5.000, ∞).
    Vizinhança 0: a janela é [1.000, 3.000], e o fill de TWAP em 1.000 está nela: com TWAP.
    Sem `twap_id` no fill, sem TWAP."""
    for twap, expected in ((7, 1), (None, 0)):
        data = table(
            fill(1_000, "BTC", "B", 5.0, 100.0, 0.0, twap_id=twap),
            fill(3_000, "BTC", "A", 3.0, 101.0, 3.0),
        )
        report = break_report(
            continuity_breaks(data, LOTS),
            data,
            Ms(10_000),
            neighbourhood_ms=0,
            age_edges_ms=[5_000],
        )
        assert [(b.breaks, b.with_twap) for b in report.by_age] == [(0, 0), (1, expected)]


@pytest.mark.unit
def test_break_report_refuses_bad_arguments() -> None:
    twap = twap_table(("BTC", 1))
    found = [brk("BTC", 1, 2)]
    for edges in ([600, 200], [0, 5], [5, 5]):
        with pytest.raises(ConfigError, match="faixas"):
            break_report(found, twap, Ms(10), neighbourhood_ms=0, age_edges_ms=edges)
    with pytest.raises(ConfigError, match="vizinhança"):
        break_report(found, twap, Ms(10), neighbourhood_ms=-1, age_edges_ms=[5])
    with pytest.raises(DataError, match="posterior"):
        break_report(found, twap, Ms(1), neighbourhood_ms=0, age_edges_ms=[5])
    with pytest.raises(DataError, match="twap_id"):
        break_report(found, pl.DataFrame({"coin": ["BTC"], "time_ms": [1]}), Ms(10),
                     neighbourhood_ms=0, age_edges_ms=[5])  # fmt: skip
