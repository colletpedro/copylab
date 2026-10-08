"""Pool de candidatas (T-060; RF-SEL-07 CA-07.1 a CA-07.3), com fixtures de papel.

Oito endereços, ``0x11…1`` a ``0x88…8`` (o dígito repetido 40 vezes), e a semente de §7.2,
20261005. Os 12 primeiros dígitos hexadecimais do SHA-256 de ``20261005:pool:<endereço>``,
calculados uma vez e escritos aqui para a conta ser auditável sem rodar o código:

    0x1111… 4c3532e1041e     0x5555… 6a5b8a33e68e
    0x2222… 2383552fb630     0x6666… acefa8660845
    0x3333… 3a663de4f893     0x7777… 130676c27502
    0x4444… 71ae744f92b7     0x8888… a5cff75d13f5

Em ordem crescente de hash: 7 (13…), 2 (23…), 3 (3a…), 1 (4c…), 5 (6a…), 4 (71…), 8 (a5…),
6 (ac…).

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
``copylab.selection.pool``:

- F2 exclusivo (``>`` no lugar de ``>=``): falharam
  ``test_pool_sample_is_seeded_over_sorted_f2_addresses`` e o teste dos blocos (o endereço
  com exatamente US$ 30.000 saiu).
- Texto do hash sem a semente (``pool:{address}``): falharam os mesmos dois, com outra
  ordem.
- ``pool_growth`` com ``>`` no lugar de ``>=``: falharam
  ``test_pool_grows_in_blocks_until_20_eligibles_or_exhausted`` e
  ``test_pool_growth_depends_only_on_eligible_count`` (20 elegíveis ampliavam).

``test_universe_is_reformed_when_pool_grows`` (CA-07.2) depende do universo e entra com
T-061.
"""

import polars as pl
import pytest

from copylab.exceptions import DataError
from copylab.selection.pool import PoolGrowth, pool_block, pool_growth, pool_order, sample_pool

SEED = 20261005
MIN_VALUE = 30_000.0


def addr(digit: str) -> str:
    return "0x" + digit * 40


def board(values: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {"address": [addr(d) for d in values], "account_value": list(values.values())},
        schema={"address": pl.String, "account_value": pl.Float64},
    )


#: 1 a 8 passam em F2, exceto o 6 (US$ 29.999,99). O 3 tem exatamente US$ 30.000: o limiar
#: é inclusivo (design §3.6). A ordem das linhas é embaralhada de propósito.
BOARD = board(
    {
        "8": 90_000.0,
        "3": 30_000.0,
        "6": 29_999.99,
        "1": 31_000.0,
        "5": 1_000_000.0,
        "7": 45_000.0,
        "2": 50_000.0,
        "4": 30_000.01,
    }
)
#: A ordem de hash do cabeçalho, sem o 6.
EXPECTED_ORDER = [addr(d) for d in "7231548"]


@pytest.mark.unit
def test_pool_sample_is_seeded_over_sorted_f2_addresses() -> None:
    assert pool_order(BOARD, MIN_VALUE, SEED) == EXPECTED_ORDER
    # A ordem das linhas do snapshot não muda nada.
    assert pool_order(BOARD.reverse(), MIN_VALUE, SEED) == EXPECTED_ORDER
    # Outra semente, outra ordem.
    assert pool_order(BOARD, MIN_VALUE, SEED + 1) != EXPECTED_ORDER


@pytest.mark.unit
def test_pool_blocks_are_consecutive_slices_of_the_same_order() -> None:
    # Blocos de 3: [7, 2, 3], [1, 5, 4], [8]; o bloco 3 está vazio.
    assert pool_block(BOARD, MIN_VALUE, 0, 3, SEED) == [addr(d) for d in "723"]
    assert pool_block(BOARD, MIN_VALUE, 1, 3, SEED) == [addr(d) for d in "154"]
    assert pool_block(BOARD, MIN_VALUE, 2, 3, SEED) == [addr("8")]
    assert pool_block(BOARD, MIN_VALUE, 3, 3, SEED) == []
    assert sample_pool(BOARD, MIN_VALUE, 2, 3, SEED) == [addr(d) for d in "723154"]


@pytest.mark.unit
def test_pool_grows_in_blocks_until_20_eligibles_or_exhausted() -> None:
    # Pool de 7 endereços em blocos de 3 (3 blocos: o último com 1). Mínimo de 20.
    assert pool_growth(19, 1, 7, 3, 20) == PoolGrowth("grow", 1)
    assert pool_growth(19, 2, 7, 3, 20) == PoolGrowth("grow", 2)
    assert pool_growth(19, 3, 7, 3, 20) == PoolGrowth("exhausted", None)
    assert pool_growth(20, 1, 7, 3, 20) == PoolGrowth("enough", None)  # inclusivo
    assert pool_growth(25, 3, 7, 3, 20) == PoolGrowth("enough", None)


@pytest.mark.unit
def test_pool_growth_depends_only_on_eligible_count() -> None:
    # A função recebe só contagens: não há como passar desempenho. Para o mesmo tamanho de
    # pool e de bloco, a decisão muda exatamente quando a contagem cruza o mínimo.
    decisions = {n: pool_growth(n, 1, 9_000, 3_000, 20).action for n in range(0, 40)}
    assert {n for n, action in decisions.items() if action == "grow"} == set(range(20))
    assert {n for n, action in decisions.items() if action == "enough"} == set(range(20, 40))


@pytest.mark.unit
def test_pool_refuses_repeated_address_and_invalid_blocks() -> None:
    repeated = pl.concat([BOARD, BOARD.head(1)])
    with pytest.raises(DataError, match="repetido"):
        pool_order(repeated, MIN_VALUE, SEED)
    with pytest.raises(DataError):
        sample_pool(BOARD, MIN_VALUE, -1, 3, SEED)
    with pytest.raises(DataError):
        pool_block(BOARD, MIN_VALUE, 0, 0, SEED)
