"""Orçamento de desempenho da seleção (RNF-04): filtros sobre 3.000 carteiras em menos de 10
minutos, com dado sintético do tamanho do marco M-B: 3.000 carteiras e cerca de 3,6 milhões de
fills (1.200 por carteira). Marcado como integração: não roda na suíte padrão.

Cada carteira tem 600 episódios de um perpétuo do universo (cinco ativos em rodízio), abertos a
mercado e fechados 1 h depois, espalhados pelos 62 dias da janela, com o PnL conciliado. Mede o
que a seleção faz por carteira antes do ranking: fatos (livro-razão, episódios, conferência de
PnL), os dez filtros e a referência de exposição.

Rodar: ``uv run pytest -m integration -s tests/integration/test_selection_performance.py``.
"""

import time

import polars as pl
import pytest
from tests.unit.selection_support import (
    LOTS,
    W56,
    FakeRepository,
    coverage_table,
    real_params,
)

from copylab.ports import BoundedRepository
from copylab.selection.facts import wallet_facts
from copylab.selection.filters import run_funnel
from copylab.selection.reference import reference_exposure
from copylab.storage.tables import FILLS, SCHEMAS
from copylab.timeutil import MS_PER_HOUR

COINS = ("BTC", "ETH", "SOL", "AVAX", "XRP")
EPISODES = 600
BUDGET_SECONDS = 600


def synthetic_fills() -> pl.DataFrame:
    slot = (W56.end - W56.start) // (EPISODES + 1)
    times: list[int] = []
    coins: list[str] = []
    sides: list[str] = []
    px: list[float] = []
    start: list[float] = []
    pnl: list[float] = []
    for i in range(EPISODES):
        opened = W56.start + (i + 1) * slot
        coin = COINS[i % len(COINS)]
        times += [opened, opened + MS_PER_HOUR]
        coins += [coin, coin]
        sides += ["B", "A"]
        px += [100.0, 101.0]
        start += [0.0, 1.0]
        pnl += [0.0, 1.0]
    n = len(times)
    columns = {
        "seq": list(range(n)),
        "time_ms": times,
        "coin": coins,
        "kind": ["perp"] * n,
        "px": px,
        "sz": [1.0] * n,
        "side": sides,
        "start_position": start,
        "dir": [None] * n,
        "crossed": [True] * n,
        "closed_pnl": pnl,
        "fee": [0.0] * n,
        "tid": [1] * n,
        "oid": [1] * n,
        "twap_id": [None] * n,
        "liquidated_user": [None] * n,
    }
    return pl.DataFrame(columns, schema=SCHEMAS[FILLS])


@pytest.mark.integration
def test_performance_budgets() -> None:
    wallets = 3_000
    frame = synthetic_fills()
    addresses = [f"0x{i:040x}" for i in range(wallets)]
    repo = FakeRepository(
        fills=dict.fromkeys(addresses, frame),
        coverage=dict.fromkeys(addresses, coverage_table(W56, "ok")),
    )
    bounded = BoundedRepository(repo, W56.end)
    params = real_params()
    universe = frozenset(COINS)

    began = time.perf_counter()
    facts = [wallet_facts(bounded, address, W56, universe, LOTS, 50_000.0) for address in addresses]
    facts_s = time.perf_counter() - began
    began = time.perf_counter()
    funnel = run_funnel(facts, params, dict.fromkeys(addresses, "user"))
    funnel_s = time.perf_counter() - began
    began = time.perf_counter()
    references = [
        reference_exposure(
            bounded.fills(a, W56.start, W56.end),
            LOTS,
            universe,
            W56,
            params.reference.percentile_pct,
        )
        for a in addresses
    ]
    reference_s = time.perf_counter() - began
    total = facts_s + funnel_s + reference_s
    print(
        f"\nRNF-04: {wallets} carteiras, {wallets * frame.height:,} fills: fatos {facts_s:.1f} s, "
        f"funil {funnel_s:.2f} s, N* {reference_s:.1f} s, total {total:.1f} s "
        f"(orçamento {BUDGET_SECONDS} s)"
    )
    assert len(funnel.survivors) == wallets
    assert all(r is not None for r in references)
    assert total < BUDGET_SECONDS
