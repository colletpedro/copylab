"""Pool de candidatas (T-060; RF-SEL-07, design §3.6).

As candidatas são os endereços que passam em F2 (patrimônio no snapshot de ao menos o
mínimo, limiar inclusivo), postos na ordem do SHA-256 do texto ``semente:pool:endereço``.
O bloco ``n`` é a fatia ``[tamanho·n, tamanho·(n+1))`` dessa ordem: ampliar o pool é tomar o
bloco seguinte da mesma sequência, e o resultado não depende de gerador de números
aleatórios nem da versão de nenhuma biblioteca (design §6, decisão 23). A ordem pode ser
conferida à mão.

A decisão de ampliar depende só da contagem de elegíveis, que não usa desempenho
(RF-SEL-07 CA-07.3): :func:`pool_growth` recebe números, e nada mais.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal

import polars as pl

from copylab.exceptions import DataError

__all__ = ["PoolGrowth", "pool_block", "pool_growth", "pool_order", "sample_pool"]


def _key(seed: int, address: str) -> tuple[str, str]:
    return hashlib.sha256(f"{seed}:pool:{address}".encode()).hexdigest(), address


def pool_order(leaderboard: pl.DataFrame, min_account_value: float, seed: int) -> list[str]:
    """Endereços que passam em F2, na ordem do sorteio.

    Os endereços são ordenados antes (RF-SEL-07 CA-07.1); a ordem do sorteio é a do hash,
    com o endereço como desempate.

    Raises:
        DataError: endereço repetido no snapshot.
    """
    passing = (
        leaderboard.filter(pl.col("account_value") >= min_account_value)
        .get_column("address")
        .sort()
        .to_list()
    )
    if len(set(passing)) != len(passing):
        raise DataError("Snapshot do leaderboard com endereço repetido.")
    return sorted(passing, key=lambda address: _key(seed, address))


def sample_pool(
    leaderboard: pl.DataFrame, min_account_value: float, blocks: int, block_size: int, seed: int
) -> list[str]:
    """Os ``blocks`` primeiros blocos do pool, em ordem do sorteio."""
    if blocks < 0 or block_size <= 0:
        raise DataError(f"Pool com {blocks} blocos de {block_size}.")
    return pool_order(leaderboard, min_account_value, seed)[: blocks * block_size]


def pool_block(
    leaderboard: pl.DataFrame, min_account_value: float, block: int, block_size: int, seed: int
) -> list[str]:
    """O bloco ``block`` (a partir de 0) do pool; vazio se o pool acabou antes dele."""
    if block < 0 or block_size <= 0:
        raise DataError(f"Bloco {block} de tamanho {block_size}.")
    order = pool_order(leaderboard, min_account_value, seed)
    return order[block * block_size : (block + 1) * block_size]


@dataclass(frozen=True, slots=True)
class PoolGrowth:
    """O que fazer com o pool depois de contar os elegíveis.

    ``enough``: há elegíveis bastantes. ``grow``: ingerir e incluir o bloco ``next_block``.
    ``exhausted``: o pool acabou com menos elegíveis que o mínimo.
    """

    action: Literal["enough", "grow", "exhausted"]
    next_block: int | None


def pool_growth(
    eligible: int, blocks_used: int, pool_size: int, block_size: int, min_eligible: int
) -> PoolGrowth:
    """Decide a ampliação do pool (RF-SEL-07 CA-07.2) só pela contagem de elegíveis.

    Com ``min_eligible`` ou mais elegíveis, para. Com menos, amplia para o bloco seguinte se
    ele tem algum endereço; senão, o pool acabou.
    """
    if eligible >= min_eligible:
        return PoolGrowth("enough", None)
    if blocks_used * block_size < pool_size:
        return PoolGrowth("grow", blocks_used)
    return PoolGrowth("exhausted", None)
