"""Testes das ferramentas de medição de `scripts/verify/` (`common.py` e `analysis.py`).

A verificação de dados mede e reporta; se a régua estiver torta, o relatório mente. Por
isso as funções puras têm fixtures de papel, com a conta feita no comentário.

Os módulos são carregados por caminho (`importlib`), e não importados, de propósito: o
adendo ao prompt 02 deixa `scripts/verify/` fora do portão do `mypy`, e um `import`
faria o `mypy` segui-los e checá-los em modo estrito.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_VERIFY_DIR = Path(__file__).resolve().parents[2] / "scripts" / "verify"


def _load(name: str) -> ModuleType:
    if str(_VERIFY_DIR) not in sys.path:
        sys.path.insert(0, str(_VERIFY_DIR))
    spec = importlib.util.spec_from_file_location(f"verify_{name}", _VERIFY_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # `@dataclass` resolve anotações por sys.modules
    spec.loader.exec_module(module)
    return module


common = _load("common")
analysis = _load("analysis")


def _fill(
    side: str,
    sz: float,
    px: float,
    start: float,
    *,
    time: int = 1_700_000_000_000,
    closed_pnl: float = 0.0,
    fee: float = 0.0,
    coin: str = "BTC",
) -> dict[str, Any]:
    return {
        "coin": coin,
        "side": side,
        "sz": str(sz),
        "px": str(px),
        "startPosition": str(start),
        "time": time,
        "closedPnl": str(closed_pnl),
        "fee": str(fee),
        "dir": "x",
        "crossed": True,
        "tid": 1,
        "oid": 1,
    }


# ─── RateBudget ──────────────────────────────────────────────────────────────


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.unit
def test_budget_never_exceeds_limit_in_any_sliding_window() -> None:
    """Conta: limite 100, janela 60 s, 50 pedidos de peso 30.

    Cabem 3 por janela (3 x 30 = 90; um quarto daria 120 > 100). Se a regra falhasse,
    algum instante t teria soma de pesos em (t - 60, t] acima de 100.
    """
    clock = _FakeClock()
    budget = common.RateBudget(100, 60.0, clock=clock, sleep=clock.sleep)
    log: list[tuple[float, float]] = []
    for _ in range(50):
        budget.acquire(30)
        log.append((clock.now, 30))
    for t, _ in log:
        in_window = sum(w for (u, w) in log if t - 60.0 < u <= t)
        assert in_window <= 100
    assert budget.peak <= 100
    assert budget.waited_s > 0


@pytest.mark.unit
def test_budget_settle_refunds_unused_weight() -> None:
    """Reservar 120 e gastar 21 devolve 99 à janela: dois pedidos de 120 não cabem em
    150, mas reservar, acertar para 21 e reservar de novo cabe sem esperar."""
    clock = _FakeClock()
    budget = common.RateBudget(150, 60.0, clock=clock, sleep=clock.sleep)
    first = budget.acquire(120)
    budget.settle(first, 21)
    budget.acquire(120)
    assert clock.now == 0.0
    assert budget.total_weight == pytest.approx(141.0)


@pytest.mark.unit
def test_budget_penalize_blocks_until_the_window_drains() -> None:
    """Depois de um 429, a janela é tratada como cheia por 60 s."""
    clock = _FakeClock()
    budget = common.RateBudget(100, 60.0, clock=clock, sleep=clock.sleep)
    budget.penalize()
    budget.acquire(10)
    assert clock.now >= 60.0


@pytest.mark.unit
def test_budget_rejects_a_request_larger_than_the_limit() -> None:
    with pytest.raises(ValueError, match="maior que o orçamento"):
        common.RateBudget(100).acquire(101)


@pytest.mark.unit
def test_budget_default_is_below_the_documented_api_limit() -> None:
    assert common.BUDGET_WEIGHT_PER_MIN < common.API_WEIGHT_LIMIT_PER_MIN
    assert common.RateBudget().limit == common.BUDGET_WEIGHT_PER_MIN


@pytest.mark.unit
@pytest.mark.parametrize(
    ("items", "weight"),
    [(0, 20), (1, 21), (20, 21), (21, 22), (2000, 120)],
)
def test_fills_weight_is_20_plus_one_per_20_items(items: int, weight: int) -> None:
    assert common.fills_weight(items) == weight


@pytest.mark.unit
def test_window_constants_are_midnight_utc_of_the_spec_dates() -> None:
    # 2026-07-01 00:00 UTC = 1782864000 s; a janela tem 62 dias (jul 31 + ago 31).
    assert common.WINDOW_START_MS == 1_782_864_000_000
    assert (common.CUTOFF_MS - common.WINDOW_START_MS) == 62 * 86_400_000


# ─── Campos, classificação, números ──────────────────────────────────────────


@pytest.mark.unit
def test_field_coverage_counts_present_and_interpretable() -> None:
    """Dois fills: o segundo sem `tid` e com `side` inválido.

    `tid`: presente 1, ok 1. `side`: presente 2, ok 1. `px`: 2 e 2.
    """
    good = _fill("B", 1, 100, 0)
    bad = _fill("A", 1, 100, 0)
    del bad["tid"]
    bad["side"] = "X"
    cov = analysis.field_coverage([good, bad])
    assert cov["total"] == 2
    assert cov["fields"]["tid"] == {"present": 1, "ok": 1}
    assert cov["fields"]["side"] == {"present": 2, "ok": 1}
    assert cov["fields"]["px"] == {"present": 2, "ok": 2}


@pytest.mark.unit
def test_field_checks_reject_uninterpretable_values() -> None:
    checks = analysis.FIELD_CHECKS
    assert checks["px"]("100.5") and not checks["px"]("abc") and not checks["px"]("0")
    assert checks["startPosition"]("0.0") and not checks["startPosition"]("nan")
    assert checks["crossed"](True) and not checks["crossed"]("true")
    assert checks["tid"](5) and not checks["tid"](True) and not checks["tid"]("5")
    assert checks["time"](1_700_000_000_000) and not checks["time"](1_700_000_000)


@pytest.mark.unit
def test_classify_coin() -> None:
    perps = frozenset({"BTC", "ETH"})
    assert analysis.classify_coin("BTC", perps) == "perp"
    assert analysis.classify_coin("MATIC", perps) == "perp_fora_do_meta"
    assert analysis.classify_coin("xyz:GOLD", perps) == "hip3"
    assert analysis.classify_coin("@107", perps) == "spot"
    assert analysis.classify_coin("PURR/USDC", perps) == "spot"
    assert analysis.classify_coin("#5101", perps) == "outcome"


@pytest.mark.unit
def test_percentile_matches_linear_interpolation() -> None:
    # [1, 2, 3, 4]: posição de q=50 é 1,5 -> 2 + 0,5 x (3 - 2) = 2,5.
    # q=95: posição 2,85 -> 3 + 0,85 x (4 - 3) = 3,85.
    assert analysis.percentile([4, 1, 3, 2], 50) == pytest.approx(2.5)
    assert analysis.percentile([4, 1, 3, 2], 95) == pytest.approx(3.85)
    assert analysis.percentile([7], 95) == pytest.approx(7.0)


# ─── Continuidade (RF-ING-03 CA-03.1) ────────────────────────────────────────


@pytest.mark.unit
def test_continuity_detects_a_missing_fill_and_separates_same_ms_breaks() -> None:
    """Lote 0,01. f1 compra 1 a partir de 0 (esperado 1); f2 começa em 1, compra 1
    (esperado 2); f3 começa em 2,5 -> quebra (|2,5 - 2| = 0,5 > 0,01); f4 começa em 3,5
    (esperado 3,5 depois de comprar 1) -> ok; f5, no mesmo ms de f4, começa em 9 ->
    quebra, e conta como quebra de mesmo milissegundo.
    """
    fills = [
        _fill("B", 1, 100, 0.0, time=1),
        _fill("B", 1, 100, 1.0, time=2),
        _fill("B", 1, 100, 2.5, time=3),
        _fill("B", 1, 100, 3.5, time=4),
        _fill("B", 1, 100, 9.0, time=4),
    ]
    assert analysis.continuity_pairs(fills, 0.01) == {
        "pairs": 4,
        "breaks": 2,
        "breaks_same_ms": 1,
    }


@pytest.mark.unit
def test_continuity_tolerates_one_lot_of_rounding() -> None:
    fills = [_fill("B", 1, 100, 0.0), _fill("B", 1, 100, 1.01)]
    assert analysis.continuity_pairs(fills, 0.01)["breaks"] == 0
    assert analysis.continuity_pairs(fills, 0.001)["breaks"] == 1


# ─── Episódios e concordância (RF-VER-01 CA-01.4) ────────────────────────────


def _long_episode(pnls: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Compra 2 a 100, compra 2 a 110, vende 1 a 120, vende 3 a 108; taxa 0,1 em cada.

    Custo médio: (2 x 100 + 2 x 110) / 4 = 105. Realizado: 1 x (120 - 105) = 15 no
    terceiro fill e 3 x (108 - 105) = 9 no quarto. Bruto = 24. Taxa total = 0,4; taxa só
    dos fills que reduzem = 0,2. Logo: líquido de tudo = 23,6; líquido só da saída = 23,8.
    """
    p1, p2, p3, p4 = pnls
    return [
        _fill("B", 2, 100, 0.0, closed_pnl=p1, fee=0.1, time=1),
        _fill("B", 2, 110, 2.0, closed_pnl=p2, fee=0.1, time=2),
        _fill("A", 1, 120, 4.0, closed_pnl=p3, fee=0.1, time=3),
        _fill("A", 3, 108, 3.0, closed_pnl=p4, fee=0.1, time=4),
    ]


@pytest.mark.unit
def test_reconstruct_gross_by_average_cost() -> None:
    assert analysis.reconstruct_gross(_long_episode((0, 0, 0, 0))) == pytest.approx(24.0)


@pytest.mark.unit
def test_reconstruct_gross_for_a_short() -> None:
    """Vende 2 a 100 e recompra 2 a 90: ganha 2 x (100 - 90) = 20."""
    fills = [_fill("A", 2, 100, 0.0), _fill("B", 2, 90, -2.0)]
    assert analysis.reconstruct_gross(fills) == pytest.approx(20.0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("pnls", "winner"),
    [
        ((0.0, 0.0, 15.0, 9.0), "gross"),  # soma 24
        ((-0.1, -0.1, 14.9, 8.9), "net_all"),  # soma 23,6
        ((0.0, 0.0, 14.9, 8.9), "net_close"),  # soma 23,8
    ],
)
def test_concordance_identifies_which_hypothesis_holds(
    pnls: tuple[float, float, float, float], winner: str
) -> None:
    episodes = analysis.build_episodes(_long_episode(pnls), 0.001)
    out = analysis.concordance(episodes)
    assert out["tested"] == 1
    for name in ("gross", "net_all", "net_close"):
        assert out.get(name, 0) == (1 if name == winner else 0), (name, out)


@pytest.mark.unit
def test_concordance_output_carries_only_counts_never_pnl_values() -> None:
    """Regra 2 do prompt 02: a saída de `concordance` são contagens inteiras."""
    out = analysis.concordance(analysis.build_episodes(_long_episode((0, 0, 15, 9)), 0.001))
    assert all(isinstance(v, int) for v in out.values())


@pytest.mark.unit
def test_episodes_ignore_preexisting_position_and_flag_inversion() -> None:
    """Posição anterior à janela (fill que começa em 1,5) é ignorada até zerar.

    Depois: compra 1 a partir de 0 e fecha (episódio flat); depois vende 3 a partir de
    1 -> termina em -2 (inversão, excluída do teste de PnL).
    """
    fills = [
        _fill("A", 1.5, 100, 1.5, time=1),  # zera a posição antiga: não é episódio
        _fill("B", 1, 100, 0.0, time=2),
        _fill("A", 1, 110, 1.0, time=3),  # flat
        _fill("B", 1, 100, 0.0, time=4),
        _fill("A", 3, 100, 1.0, time=5),  # 1 -> -2: inversão
    ]
    episodes = analysis.build_episodes(fills, 0.001)
    assert [e.ended for e in episodes] == ["flat", "inversion"]
    out = analysis.concordance(episodes)
    assert out["tested"] == 1
    assert out["excluded_inversion"] == 1


@pytest.mark.unit
def test_episode_with_broken_continuity_is_excluded_not_tested() -> None:
    fills = [_fill("B", 1, 100, 0.0, time=1), _fill("A", 1, 110, 5.0, time=2)]
    episodes = analysis.build_episodes(fills, 0.001)
    assert analysis.concordance(episodes).get("tested", 0) == 0


# ─── Notional e regra D7 ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_notional_by_coin_sums_price_times_size() -> None:
    fills = [_fill("B", 2, 100, 0), _fill("A", 1, 110, 0), _fill("B", 3, 10, 0, coin="ETH")]
    assert analysis.notional_by_coin(fills) == pytest.approx({"BTC": 310.0, "ETH": 30.0})


@pytest.mark.unit
def test_d7_adds_in_descending_order_skipping_assets_without_binance_perp() -> None:
    """Universo BTC+ETH+SOL = 0,20 + 0,10 + 0,05 = 0,35. Candidatos em ordem:
    XRP 0,10 (tem equivalente) -> 0,45; DOGE 0,08 (não tem) -> pulado; ABC 0,07 ->
    0,52 >= 0,5, para. ZZZ não entra."""
    ranked = [
        ("BTC", 0.20),
        ("ETH", 0.10),
        ("XRP", 0.10),
        ("DOGE", 0.08),
        ("ABC", 0.07),
        ("SOL", 0.05),
        ("ZZZ", 0.04),
    ]
    equivalent = {"XRP": True, "DOGE": False, "ABC": True, "ZZZ": True}
    chosen = analysis.d7_additions(ranked, ("BTC", "ETH", "SOL"), equivalent)
    assert [c["coin"] for c in chosen] == ["XRP", "ABC"]
    assert chosen[-1]["cumulative_after"] == pytest.approx(0.52)


@pytest.mark.unit
def test_d7_stops_at_eight_assets_even_below_the_target() -> None:
    ranked = [("BTC", 0.01), ("ETH", 0.01), ("SOL", 0.01)] + [(f"A{i}", 0.01) for i in range(10)]
    equivalent = {f"A{i}": True for i in range(10)}
    chosen = analysis.d7_additions(ranked, ("BTC", "ETH", "SOL"), equivalent)
    assert len(chosen) == 5  # 3 do universo + 5 = 8


@pytest.mark.unit
def test_d7_adds_nothing_when_the_universe_already_reaches_the_target() -> None:
    ranked = [("BTC", 0.40), ("ETH", 0.15), ("XRP", 0.10)]
    assert analysis.d7_additions(ranked, ("BTC", "ETH", "SOL"), {"XRP": True}) == []


# ─── Paginação de fills ──────────────────────────────────────────────────────


class _FakeFillsClient:
    """Imita `userFillsByTime`: ascendente, `startTime` inclusivo, no máximo `page` itens."""

    def __init__(self, fills: list[dict[str, Any]], page: int) -> None:
        self._fills = fills
        self._page = page
        self.calls = 0

    def user_fills(
        self, address: str, start_ms: int, end_ms: int, *, aggregate: bool
    ) -> list[dict[str, Any]]:
        self.calls += 1
        hit = [f for f in self._fills if start_ms <= f["time"] <= end_ms]
        return hit[: self._page]


def _at(time: int, tid: int = 0) -> dict[str, Any]:
    return {"time": time, "tid": tid, "oid": tid, "hash": f"h{tid}", "px": "1", "sz": "1"}


@pytest.mark.unit
def test_pagination_handles_a_millisecond_tie_on_the_page_boundary() -> None:
    """Tempos [1, 2, 2, 3, 4] com páginas de 3.

    Página 1: [1, 2a, 2b]; recomeça em 2 e repete 2a e 2b (descartados pelo
    multiconjunto da fronteira); página 2: [2a, 2b, 3] traz 3; página 3 (a partir de 3):
    [3, 4] traz 4. Total 5, sem perder nem duplicar ninguém.
    """
    fills = [_at(1, 1), _at(2, 2), _at(2, 3), _at(3, 4), _at(4, 5)]
    got = common.collect_fills(_FakeFillsClient(fills, 3), "0x0", 0, 10)
    assert got.count == 5
    assert [f["tid"] for f in got.fills] == [1, 2, 3, 4, 5]
    assert got.first_time == 1


@pytest.mark.unit
def test_pagination_keeps_genuinely_identical_fills() -> None:
    """Dois fills idênticos no mesmo milissegundo são dois fills, não um duplicado."""
    twin = _at(2, 7)
    fills = [_at(1, 1), dict(twin), dict(twin), _at(3, 4)]
    got = common.collect_fills(_FakeFillsClient(fills, 3), "0x0", 0, 10)
    assert got.count == 4


@pytest.mark.unit
def test_pagination_count_only_returns_no_content() -> None:
    fills = [_at(t, t) for t in range(1, 8)]
    got = common.collect_fills(_FakeFillsClient(fills, 3), "0x0", 0, 10, keep=False)
    assert got.count == 7
    assert got.fills == []


@pytest.mark.unit
def test_pagination_stops_early_once_the_count_passes_the_limit() -> None:
    """20 fills, páginas de 5, limite 7.

    Página 1: 5 fills. Página 2 recomeça no 5 (repetido) e traz 6 a 9: total 9 > 7, para
    ali, sem pagar as outras duas páginas.
    """
    fills = [_at(t, t) for t in range(1, 21)]
    client = _FakeFillsClient(fills, 5)
    got = common.collect_fills(client, "0x0", 0, 100, keep=False, stop_after=7)
    assert got.capped is True
    assert got.count == 9
    assert client.calls == 2


@pytest.mark.unit
def test_pagination_respects_the_end_of_the_interval() -> None:
    fills = [_at(t, t) for t in range(1, 21)]
    got = common.collect_fills(_FakeFillsClient(fills, 5), "0x0", 5, 9)
    assert [f["time"] for f in got.fills] == [5, 6, 7, 8, 9]


@pytest.mark.unit
def test_pagination_keeps_fills_of_one_millisecond_split_across_pages() -> None:
    """[1, 2a, 2b, 2c] com páginas de 3: a página 1 corta o milissegundo 2 no meio.

    Página 1: [1, 2a, 2b]. Página 2 recomeça em 2: [2a, 2b, 2c]; 2a e 2b já foram contados
    (multiconjunto da fronteira) e 2c é novo. Total 4. Quem descartasse toda chave do
    milissegundo da fronteira perderia o 2c.
    """
    fills = [_at(1, 1), _at(2, 2), _at(2, 3), _at(2, 4)]
    got = common.collect_fills(_FakeFillsClient(fills, 3), "0x0", 0, 10)
    assert got.count == 4


@pytest.mark.unit
def test_concordance_by_size_buckets_episodes_by_number_of_fills() -> None:
    """Um episódio de 2 fills (compra 1 a 100, vende 1 a 110: realizado 10) e o de 4 fills
    do fixture acima (realizado 24). Com `closedPnl` correto em ambos, cada faixa concilia."""
    two = [
        _fill("B", 1, 100, 0.0, time=1),
        _fill("A", 1, 110, 1.0, closed_pnl=10.0, time=2),
    ]
    four = _long_episode((0.0, 0.0, 15.0, 9.0))
    episodes = analysis.build_episodes(two + four, 0.001)
    out = analysis.concordance_by_size(episodes)
    assert out["2|tested"] == 1
    assert out["2|gross@1e-06"] == 1
    assert out["3-4|tested"] == 1
    assert out["3-4|gross@1e-06"] == 1


@pytest.mark.unit
def test_continuity_breaks_reports_direction_jump_and_gap() -> None:
    """f1 compra 1 a partir de 0 (esperado 1) e f2 começa em 5: salto de 4, maior que o
    tamanho do fill anterior (1), 10 s depois, com `liquidation` no segundo."""
    f1 = _fill("B", 1, 100, 0.0, time=1_000)
    f2 = _fill("B", 1, 100, 5.0, time=11_000)
    f2["liquidation"] = {"method": "market"}
    out = analysis.continuity_breaks([f1, f2], 0.001)
    assert out["prev_dir"] == {"x": 1}
    assert out["jump"] == {"salto >= tamanho do fill anterior": 1}
    assert out["with_liquidation_field"] == 1
    assert out["gaps_s"] == [10.0]


@pytest.mark.unit
def test_pagination_records_where_each_page_joins_the_next() -> None:
    """Tempos [1..5] com páginas de 2: página 1 [1, 2]; página 2 (a partir de 2) traz o 3;
    página 3 (a partir de 3) traz o 4; página 4 traz o 5. Os fills novos de cada página a
    partir da segunda começam nos índices 2, 3 e 4."""
    fills = [_at(t, t) for t in range(1, 6)]
    got = common.collect_fills(_FakeFillsClient(fills, 2), "0x0", 0, 10)
    assert got.boundaries == [2, 3, 4]


@pytest.mark.unit
def test_pnl_divergence_is_a_ratio_to_the_traded_notional() -> None:
    """Episódio do fixture: PnL reconstruído 24; com `closedPnl` somando 23,9 a diferença é 0,1.
    Notional = 2 x 100 + 2 x 110 + 1 x 120 + 3 x 108 = 864. Razão = 0,1 / 864 x 1e4 = 1,1574 bps.
    Com `closedPnl` somando 24 a razão é zero."""
    off = analysis.build_episodes(_long_episode((0.0, 0.0, 15.0, 8.9)), 0.001)
    exact = analysis.build_episodes(_long_episode((0.0, 0.0, 15.0, 9.0)), 0.001)
    ((n, bps),) = analysis.pnl_divergence_bps(off)
    assert n == 4
    assert bps == pytest.approx(0.1 / 864 * 1e4)
    assert analysis.pnl_divergence_bps(exact)[0][1] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_pnl_divergence_skips_open_and_inverted_episodes() -> None:
    inverted = [_fill("B", 1, 100, 0.0, time=1), _fill("A", 3, 100, 1.0, time=2)]
    assert analysis.pnl_divergence_bps(analysis.build_episodes(inverted, 0.001)) == []


@pytest.mark.unit
def test_ratio_summary_and_size_band() -> None:
    summary = analysis.ratio_summary([0.0, 0.5, 1.0, 2.0, 10.0])
    assert summary["n"] == 5
    assert summary["median"] == pytest.approx(1.0)
    assert summary["max"] == pytest.approx(10.0)
    assert summary["above"] == 2  # 2,0 e 10,0; 1,0 não passa de 1
    assert summary["fraction_above"] == pytest.approx(0.4)
    assert [analysis.size_band(n) for n in (2, 3, 4, 5, 9)] == ["2", "3-4", "3-4", "5+", "5+"]


@pytest.mark.unit
def test_continuity_break_pairs_returns_the_series_indexes() -> None:
    fills = [
        _fill("B", 1, 100, 0.0),
        _fill("B", 1, 100, 1.0),
        _fill("B", 1, 100, 9.0),
        _fill("B", 1, 100, 10.0),
    ]
    assert analysis.continuity_break_pairs(fills, 0.001) == [(1, 2)]


@pytest.mark.unit
def test_straddle_by_span_compares_broken_and_intact_pairs_of_the_same_span() -> None:
    """Três fills de BTC consecutivos na carteira (posições 0, 1 e 2; lote 0,001) e uma
    fronteira de página no índice 2. O par (1, 2) atravessa a fronteira (1 < 2 <= 2) e o par
    (0, 1) não. Ambos têm vão 1 e são íntegros; marcado o segundo como quebrado, a faixa "1"
    passa a ter 1 par íntegro (0 atravessando) e 1 quebrado (atravessando)."""
    v05 = _load("v05_complement")
    fills = [
        _fill("B", 1, 100, 0.0, time=1),
        _fill("B", 1, 100, 1.0, time=2),
        _fill("B", 1, 100, 2.0, time=3),
    ]
    rec = {"address": "0xa", "fills": fills}
    assets = {"BTC": {"szDecimals": 3, "isDelisted": False}}
    marks = {"0xa": [2]}
    intact = v05.straddle_by_span([rec], assets, marks, set())
    assert intact["1"]["intact"] == {"pairs": 2, "crossing": 1}
    mixed = v05.straddle_by_span([rec], assets, marks, {("0xa", "BTC", 2)})
    assert mixed["1"]["intact"] == {"pairs": 1, "crossing": 0}
    assert mixed["1"]["broken"] == {"pairs": 1, "crossing": 1}
    assert [v05.span_band(d) for d in (1, 2, 10, 11, 100, 101, 1000, 1001)] == [
        "1", "2 a 10", "2 a 10", "11 a 100", "11 a 100", "101 a 1000", "101 a 1000", "mais de 1000",
    ]  # fmt: skip


@pytest.mark.unit
def test_pagination_max_pages_stops_and_flags_a_full_last_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 fills em páginas de 5: com `max_pages=2` pára depois da segunda página, cheia, e
    avisa que pode haver mais; com 6 fills (a segunda página sai curta) não há o que avisar."""
    monkeypatch.setattr(common, "PAGE_MAX", 5)  # "página cheia" passa a ser 5 itens
    many = [_at(t, t) for t in range(1, 21)]
    cut = common.collect_fills(_FakeFillsClient(many, 5), "0x0", 0, 100, max_pages=2)
    assert cut.pages == 2
    assert cut.truncated is True
    few = [_at(t, t) for t in range(1, 7)]
    short = common.collect_fills(_FakeFillsClient(few, 5), "0x0", 0, 100, max_pages=2)
    assert short.count == 6
    assert short.truncated is False


@pytest.mark.unit
def test_requery_does_not_count_the_repeated_boundary_fill_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressão de um defeito da primeira versão da reconsulta (RF-VER-05 CA-05.1).

    Fills em base+1, base+2, base+3 (dois, o `3a` e o `3b`) e base+4, páginas de 3. Página 1:
    [1, 2, 3a]; a página 2 recomeça de forma inclusiva em base+3 e traz [3a, 3b, 4]. Somar as
    páginas sem deduplicar devolveria o `3a` duas vezes, e ele seria contado como fill que
    faltava na coleta. Com a deduplicação de fronteira, nada falta.
    """
    v05 = _load("v05_complement")
    monkeypatch.setattr(common, "PAGE_MAX", 3)
    base = common.WINDOW_START_MS + 10_000_000
    fills = [
        _at(base + 1, 1),
        _at(base + 2, 2),
        _at(base + 3, 3),
        _at(base + 3, 4),
        _at(base + 4, 5),
    ]
    rec = {"address": "0xa", "fills": fills}
    brk = {"address": "0xa", "coin": "BTC", "t_a": base + 1, "t_b": base + 4}
    out = v05.requery(_FakeFillsClient(fills, 3), rec, brk)
    assert out["returned"] == 5
    assert out["missing_from_stored"] == 0
    assert out["pages"] == 2
