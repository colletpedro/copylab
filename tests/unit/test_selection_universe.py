"""Ativos candidatos e universo por regra (T-061; RF-SEL-08 CA-08.1 a CA-08.3, RF-SEL-07
CA-07.2). Fixtures de papel: a conta de cada número está no comentário.

**Cenário.** A janela são 3 dias UTC, 20.000 a 20.002 (``W``). O pool tem quatro carteiras:

    A  ok                       B  ok
    C  "frequência incompatível"    D  ok (bloco seguinte do pool)

Cada fill tem tamanho 1, então o notional dele é o preço. Os parâmetros são os reais, com
``max_assets = 4`` e ``min_candidate_fills = 3`` para a conta caber no papel.

    ativo  preço  fills  quem                    proxy                       custo
    BTC    1000   3      A                       último = preço              sim
    ETH     500   3      A (1), B (2)            último = preço              não
    SOL     400   3      B                       sem proxy                   sim
    XRP     256   3      A                       um fill a 256 contra 128    sim
    AVAX    128   2      B                       último = preço              sim
    DOGE     64   3      B                       último = preço              sim
    @107   1000   1      A (spot)                -                           -

Notional por ativo: BTC 3.000, ETH 1.500, SOL 1.200, XRP 768, AVAX 256, DOGE 192. A carteira
C tem 5 fills de DOGE a 4.096 (notional 20.480) que NÃO podem contar, porque a cobertura dela
não é ``ok``. A carteira D tem a mesma coisa, mas é ``ok``.

**Condições** com as candidatas A, B e C (C fora da soma). Cumprem (i): todos menos SOL (sem
proxy). Entre os que cumprem (i), por notional: BTC, ETH, XRP, AVAX, DOGE; os 4 primeiros
passam em (ii), e DOGE não. AVAX tem 2 fills (< 3): (iii). XRP tem um desvio de 10.000 bps no
terceiro fill, e o p95 de 3 fills é o 3º: (iv). ETH não tem custo: (v). Só BTC entra.

**Com o pool ampliado** (D entra): DOGE soma 192 + 20.480 = 20.672 de notional e 8 fills. Cumprem
(i) DOGE, BTC, ETH, XRP, AVAX; os 4 primeiros em (ii) são DOGE, BTC, ETH, XRP, e o AVAX sai em
(ii) (antes estava em (iii)). DOGE tem 8 fills e proxy válido (os fills de D têm último igual
ao preço) e custo: entra. Universo: BTC e DOGE.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em
``copylab.selection.universe`` (as mutações de cada teste estão na docstring dele).
"""

from collections.abc import Mapping

import polars as pl
import pytest
from tests.unit.selection_support import (
    FakeRepository,
    coverage_table,
    fill_row,
    fills_table,
    proxy_days_table,
    proxy_table,
    real_params,
)

from copylab.costs import CostEntry
from copylab.exceptions import LookaheadError
from copylab.ingestion.fills import STATUS_INCOMPATIBLE
from copylab.ingestion.fills import STATUS_OK as INGESTION_STATUS_OK
from copylab.params import Params
from copylab.ports import BoundedRepository
from copylab.selection.universe import (
    STATUS_OK,
    Candidates,
    candidate_assets,
    form_universe,
    has_ok_coverage,
)
from copylab.timeutil import MS_PER_DAY, Ms, day_start
from copylab.windows import Window

W = Window(day_start(20_000), day_start(20_003))
POOL = ["0xA", "0xB", "0xC", "0xD"]
COSTS = {
    coin: CostEntry(1.0, (20_000, 20_001, 20_002), "ab" * 32)
    for coin in ("BTC", "SOL", "XRP", "AVAX", "DOGE")
}


def params() -> Params:
    base = real_params()
    return base.model_copy(
        update={
            "universe": base.universe.model_copy(update={"max_assets": 4, "min_candidate_fills": 3})
        }
    )


class Scenario:
    """Monta fills e proxy: o ``k``-ésimo fill cai ``k`` s depois de 01:00 do dia ``k % 3``."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {}
        self.proxy: dict[str, list[tuple[int, float]]] = {}
        self.k = 0
        self.days: dict[str, dict[int, bool]] = {}  # proxy_days sem proxy gravado

    def add(self, wallet: str, coin: str, px: float, last: float | None, n: int = 1) -> None:
        for _ in range(n):
            day = self.k % 3
            t = day_start(20_000 + day) + 3_600_000 + 1_000 * self.k
            kind = "spot" if coin.startswith("@") else "perp"
            self.rows.setdefault(wallet, []).append(fill_row(t, coin, "B", 1.0, px, 0.0, kind=kind))
            if last is not None:
                self.proxy.setdefault(coin, []).append((t // 1_000, last))
            self.k += 1

    def repo(self, statuses: Mapping[str, str]) -> FakeRepository:
        proxy = {}
        for coin, rows in self.proxy.items():
            # Um segundo por dia sem fill, para a condição (i) ver os três dias.
            fillers = [(day_start(20_000 + d) // 1_000 + 5, rows[0][1]) for d in range(3)]
            proxy[coin] = proxy_table([*rows, *fillers])
        days = {
            coin: proxy_days_table(dict.fromkeys(range(20_000, 20_003), True)) for coin in proxy
        }
        days.update({c: proxy_days_table(f) for c, f in self.days.items()})
        return FakeRepository(
            proxy_days=days,
            fills={a: fills_table(*rows) for a, rows in self.rows.items()},
            coverage={a: coverage_table(W, s) for a, s in statuses.items()},
            proxy=proxy,
        )


def scenario() -> FakeRepository:
    s = Scenario()
    s.add("0xA", "BTC", 1000.0, 1000.0, 3)
    s.add("0xA", "ETH", 500.0, 500.0, 1)
    s.add("0xB", "ETH", 500.0, 500.0, 2)
    s.add("0xB", "SOL", 400.0, None, 3)
    s.add("0xA", "XRP", 256.0, 256.0, 2)
    s.add("0xA", "XRP", 256.0, 128.0, 1)
    s.add("0xB", "AVAX", 128.0, 128.0, 2)
    s.add("0xB", "DOGE", 64.0, 64.0, 3)
    s.add("0xA", "@107", 1000.0, None, 1)
    s.add("0xC", "DOGE", 4096.0, 4096.0, 5)
    s.add("0xD", "DOGE", 4096.0, 4096.0, 5)
    return s.repo({"0xA": "ok", "0xB": "ok", "0xC": STATUS_INCOMPATIBLE, "0xD": "ok"})


def bounded(repo: FakeRepository) -> BoundedRepository:
    return BoundedRepository(repo, W.end)


@pytest.mark.unit
def test_ok_status_is_the_one_ingestion_writes() -> None:
    assert STATUS_OK == INGESTION_STATUS_OK


@pytest.mark.unit
def test_only_wallets_with_ok_coverage_of_the_exact_window_count() -> None:
    repo = FakeRepository(
        coverage={
            "ok": coverage_table(W, "ok"),
            "incompat": coverage_table(W, STATUS_INCOMPATIBLE),
            "failed": coverage_table(W, "falha"),
            "shorter": coverage_table(Window(W.start, Ms(W.end - MS_PER_DAY)), "ok"),
        }
    )
    bounded_repo = bounded(repo)
    assert has_ok_coverage(bounded_repo, "ok", W)
    for address in ("incompat", "failed", "shorter", "never-ingested"):
        assert not has_ok_coverage(bounded_repo, address, W), address


@pytest.mark.unit
def test_candidates_sum_only_ok_wallets_in_notional_order() -> None:
    """Carteiras A e B (C é incompatível e fica fora). Notional e fills pela tabela do
    cabeçalho; total = perpétuos (3.000 + 1.500 + 1.200 + 768 + 256 + 192 = 6.916) + spot 1.000
    = 7.916.

    Mutação: contar toda carteira do pool, sem olhar a cobertura: DOGE somou 20.672, foi para o
    topo, e o teste caiu.
    """
    candidates = candidate_assets(bounded(scenario()), POOL[:3], W, params())
    assert candidates.wallets == 2
    assert [(a.coin, a.notional, a.n_fills) for a in candidates.assets] == [
        ("BTC", 3000.0, 3),
        ("ETH", 1500.0, 3),
        ("SOL", 1200.0, 3),
        ("XRP", 768.0, 3),
        ("AVAX", 256.0, 2),
        ("DOGE", 192.0, 3),
    ]
    assert candidates.perp_notional == pytest.approx(6_916.0)
    assert candidates.total_notional == pytest.approx(7_916.0)
    by_coin = {a.coin: a for a in candidates.assets}
    assert not by_coin["SOL"].meets_i
    assert by_coin["SOL"].proxy is None
    assert by_coin["BTC"].meets_i
    assert by_coin["BTC"].proxy is not None
    assert by_coin["BTC"].proxy.valid
    assert by_coin["XRP"].proxy is not None
    assert not by_coin["XRP"].proxy.valid


@pytest.mark.unit
def test_universe_requires_all_five_conditions() -> None:
    """RF-SEL-08 CA-08.1: cada ativo falha numa condição só, e a primeira que falha é a
    registrada. Pela conta do cabeçalho: SOL em (i), DOGE em (ii), AVAX em (iii), XRP em (iv),
    ETH em (v); BTC entra.

    Mutações: (ii) tomando os 4 primeiros entre todos, e não entre os que cumprem (i): SOL
    ocupou uma vaga, AVAX caiu para (ii) e o teste caiu. (iii) com `<=` no lugar de `<`: os
    ativos de exatamente 3 fills saíram e o teste caiu. (iv) ignorada: XRP entrou, caiu. (v)
    ignorada: ETH entrou, caiu.
    """
    candidates = candidate_assets(bounded(scenario()), POOL[:3], W, params())
    universe = form_universe(candidates, COSTS, params())
    assert {d.asset.coin: d.excluded_by for d in universe.decisions} == {
        "BTC": None,
        "ETH": "v",
        "SOL": "i",
        "XRP": "iv",
        "AVAX": "iii",
        "DOGE": "ii",
    }
    assert universe.coins == frozenset({"BTC"})


@pytest.mark.unit
def test_condition_ii_counts_only_assets_meeting_condition_i() -> None:
    """Com ``max_assets = 5``, as cinco vagas vão para BTC, ETH, XRP, AVAX e DOGE (SOL não cumpre
    (i)). DOGE passa a (iii) 3 fills, (iv) válido e (v) custo: entra. Se SOL tomasse uma vaga, DOGE
    seria o 6º e ficaria em (ii)."""
    base = params()
    five = base.model_copy(update={"universe": base.universe.model_copy(update={"max_assets": 5})})
    candidates = candidate_assets(bounded(scenario()), POOL[:3], W, five)
    universe = form_universe(candidates, COSTS, five)
    assert universe.coins == frozenset({"BTC", "DOGE"})


@pytest.mark.unit
def test_universe_report_names_excluding_condition_and_coverage() -> None:
    """RF-SEL-08 CA-08.3: o universo diz a condição de cada ativo e a cobertura do notional.

    Universo = BTC, notional 3.000. Cobertura sobre todos os fills das candidatas: 3.000 / 7.916
    = 0,378979... Sobre os perpétuos do primeiro dex: 3.000 / 6.916 = 0,433777...

    Mutação: total sem os fills de spot na conta de "todos os fills": a primeira cobertura saiu
    igual à segunda e o teste caiu.
    """
    candidates = candidate_assets(bounded(scenario()), POOL[:3], W, params())
    universe = form_universe(candidates, COSTS, params())
    assert universe.notional == pytest.approx(3_000.0)
    assert universe.coverage_of_all == pytest.approx(3_000 / 7_916)
    assert universe.coverage_of_perps == pytest.approx(3_000 / 6_916)
    assert universe.coverage_of_all != pytest.approx(universe.coverage_of_perps)
    empty = form_universe(Candidates(0, (), 0.0, 0.0), COSTS, params())
    assert empty.coins == frozenset()
    assert empty.coverage_of_all is None
    assert empty.coverage_of_perps is None


@pytest.mark.unit
def test_universe_is_reformed_when_pool_grows() -> None:
    """RF-SEL-07 CA-07.2: com o pool ampliado, o universo é refeito do zero sobre o pool inteiro.

    Pela conta do cabeçalho: com A, B e C o universo é {BTC}, DOGE está em (ii) e AVAX em (iii).
    Com D, DOGE sobe a 20.672 de notional e 8 fills, toma uma vaga de (ii), e entra. AVAX,
    que perdeu a vaga, passa a (ii). O universo é {BTC, DOGE}.

    Mutação: ordenar por nome e não por notional: o teste caiu.
    """
    repo = bounded(scenario())
    before = form_universe(candidate_assets(repo, POOL[:3], W, params()), COSTS, params())
    after = form_universe(candidate_assets(repo, POOL, W, params()), COSTS, params())
    assert before.coins == frozenset({"BTC"})
    assert after.coins == frozenset({"BTC", "DOGE"})
    by_coin = {d.asset.coin: d.excluded_by for d in after.decisions}
    assert by_coin["AVAX"] == "ii"
    assert {d.asset.coin: d.excluded_by for d in before.decisions}["AVAX"] == "iii"
    # Mesmo pool, mesma resposta: o universo só depende das candidatas, dos custos e dos parâmetros.
    again = form_universe(candidate_assets(repo, POOL, W, params()), COSTS, params())
    assert again == after


@pytest.mark.unit
def test_universe_asset_without_proxy_on_every_day_fails_condition_i() -> None:
    """A condição (i) pede `proxy_days` com `found` em todos os dias da janela. BTC só com os
    dias 0 e 1 falha em (i), mesmo com o resto em ordem.

    Mutações: `_has_every_day` devolvendo "há algum dia" (`bool(there)`): caiu. Sem o filtro de
    `found`: caiu em `test_condition_i_comes_from_proxy_days_even_without_downloaded_proxy`."""
    s = Scenario()
    s.add("0xA", "BTC", 1000.0, 1000.0, 3)
    repo = s.repo({"0xA": "ok"})
    full = candidate_assets(bounded(repo), ["0xA"], W, params())
    assert full.assets[0].meets_i
    days = repo.proxy_days_by_coin["BTC"].filter(pl.col("day") < 20_002)
    trimmed = FakeRepository(
        fills=repo.fills_by_address,
        coverage=repo.coverage_by_address,
        proxy=repo.proxy_by_coin,
        proxy_days={"BTC": days},
    )
    partial = candidate_assets(bounded(trimmed), ["0xA"], W, params())
    assert not partial.assets[0].meets_i
    assert partial.assets[0].proxy is None
    universe = form_universe(partial, COSTS, params())
    assert universe.decisions[0].excluded_by == "i"


@pytest.mark.unit
def test_condition_i_comes_from_proxy_days_even_without_downloaded_proxy() -> None:
    """Design 1.8: o ativo cujo proxy não foi baixado (poucos fills) cumpre (i) pela tabela
    `proxy_days`, e ocupa vaga de (ii).

    Mesmo cenário, com SOL tendo `found = true` nos três dias e nenhum proxy gravado. Cumprem (i):
    BTC, ETH, SOL, XRP, AVAX e DOGE; os 4 primeiros em (ii) são BTC, ETH, SOL e XRP, então AVAX
    sai em (ii) (antes, em (iii)). SOL tem 3 fills e custo, mas sem proxy gravado não passa em
    (iv): conferência ausente é proxy inválido. Com `found = false` num dia, SOL volta a (i).

    Mutação: ler (i) da presença de linhas em `proxy`: SOL voltou a (i), caiu.
    """
    s = Scenario()
    s.add("0xA", "BTC", 1000.0, 1000.0, 3)
    s.add("0xA", "ETH", 500.0, 500.0, 3)
    s.add("0xB", "SOL", 400.0, None, 3)
    s.add("0xA", "XRP", 256.0, 256.0, 3)
    s.add("0xB", "AVAX", 128.0, 128.0, 3)
    s.add("0xB", "DOGE", 64.0, 64.0, 3)
    s.days["SOL"] = dict.fromkeys(range(20_000, 20_003), True)
    universe = form_universe(
        candidate_assets(bounded(s.repo({"0xA": "ok", "0xB": "ok"})), ["0xA", "0xB"], W, params()),
        COSTS,
        params(),
    )
    by_coin = {d.asset.coin: d.excluded_by for d in universe.decisions}
    assert by_coin == {
        "BTC": None,
        "ETH": "v",
        "SOL": "iv",
        "XRP": None,
        "AVAX": "ii",
        "DOGE": "ii",
    }
    s.days["SOL"][20_001] = False
    again = form_universe(
        candidate_assets(bounded(s.repo({"0xA": "ok", "0xB": "ok"})), ["0xA", "0xB"], W, params()),
        COSTS,
        params(),
    )
    assert {d.asset.coin: d.excluded_by for d in again.decisions}["SOL"] == "i"


@pytest.mark.unit
def test_selection_reading_at_or_after_cutoff_raises_in_candidates() -> None:
    """RF-SEL-01 CA-01.1: uma janela que passa do corte levanta ``LookaheadError`` antes de ler
    fills ou proxy (o repositório falso não registra nenhuma leitura de fills)."""
    repo = scenario()
    cut = BoundedRepository(repo, Ms(W.end - 1))
    with pytest.raises(LookaheadError):
        candidate_assets(cut, POOL, W, params())
    assert [r for r in repo.reads if r[0] in ("fills", "proxy")] == []


@pytest.mark.unit
def test_no_candidates_gives_an_empty_universe() -> None:
    repo = FakeRepository()
    candidates = candidate_assets(bounded(repo), ["0xZ"], W, params())
    assert candidates == Candidates(0, (), 0.0, 0.0)
