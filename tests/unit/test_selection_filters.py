"""Filtros F1 a F10 e o funil (T-063; RF-SEL-02 CA-02.1 a CA-02.3, RF-ING-03 CA-03.2, RF-ING-04
CA-04.2, RF-ING-02 CA-02.5). Fixtures de papel, com os parâmetros reais.

A carteira de base é a de `test_selection_facts.py`: 24 episódios de BTC, 3 por bloco de 7 dias,
2 h cada, abertos a mercado, PnL conciliado, sem liquidação, 100% do notional no universo,
patrimônio de US$ 50.000. Ela passa em F1 a F10. Cada variante abaixo muda uma coisa só e
reprova exatamente um filtro, pela conta do comentário.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez em
``copylab.selection.filters`` (as mutações de cada teste estão na docstring dele).
"""

from typing import Any

import pytest
from tests.unit.selection_support import (
    WALLET,
    at_start,
    facts_of,
    real_params,
    round_trips,
)

from copylab.exceptions import DataError
from copylab.params import Params
from copylab.selection.facts import WalletFacts
from copylab.selection.filters import (
    DEFAULT_ORDER,
    apply_filters,
    run_funnel,
    with_reference,
)
from copylab.selection.reference import Reference
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms

BASE = [3] * 8
Rows = list[dict[str, Any]]


def with_filters(params: Params, **update: Any) -> Params:
    return params.model_copy(update={"filters": params.filters.model_copy(update=update)})


def failing(
    facts: WalletFacts, role: str = "user", params: Params | None = None
) -> tuple[str, ...]:
    return apply_filters(facts, role, params or real_params())


def _without_pnl(rows: Rows) -> Rows:
    """A primeira venda passa a não informar `closed_pnl`."""
    sell = next(r for r in rows if r["side"] == "A")
    return [{**r, "closed_pnl": None} if r is sell else r for r in rows]


#: Variante -> (filtro que reprova, fatos). `status`, `account_value` e `role` entram à parte.
def variants() -> dict[str, tuple[str, WalletFacts, str]]:
    broken = round_trips(BASE, break_at=3)
    return {
        # F1: tipo de conta "vault".
        "F1": ("F1", facts_of(round_trips(BASE)), "vault"),
        # F2: patrimônio logo abaixo de 30.000.
        "F2": ("F2", facts_of(round_trips(BASE), account_value=29_999.99), "user"),
        # F3, quatro maneiras: cobertura que não é `ok`; quebra de continuidade no universo; fill de
        # perpétuo sem preço; PnL que não concilia (venda informa 5,0 onde o custo médio dá 1,0:
        # |1 - 5| / 201 x 10^4 = 199 bps > 10).
        "F3 coverage": (
            "F3",
            facts_of(round_trips(BASE), status="frequência incompatível"),
            "user",
        ),
        "F3 break": ("F3", facts_of(broken), "user"),
        "F3 invalid": ("F3", facts_of([*round_trips(BASE), at_start("ETH", px=None)]), "user"),
        # F3, episódio sem divergência calculável: uma venda sem `closed_pnl` (nenhuma quebra).
        "F3 unreconciled": ("F3", facts_of(_without_pnl(round_trips(BASE))), "user"),
        "F3 pnl": ("F3", facts_of(round_trips(BASE, pnl_error=4.0, error_at=7)), "user"),
        # F4: 19 episódios (< 20), ainda com os 8 blocos ativos.
        "F4": ("F4", facts_of(round_trips([3, 3, 3, 2, 2, 2, 2, 2])), "user"),
        # F5: 20 episódios (F4 passa, é inclusivo) em só 5 blocos (< 6).
        "F5": ("F5", facts_of(round_trips([4, 4, 4, 4, 4, 0, 0, 0])), "user"),
        # F6: duração mediana de 30 min (< 1 h).
        "F6": ("F6", facts_of(round_trips(BASE, duration_ms=MS_PER_HOUR // 2)), "user"),
        # F7: aberturas a mercado em 11 de 24 (45,8% < 50%).
        "F7": ("F7", facts_of(round_trips(BASE, crossed=lambda i: i < 11)), "user"),
        # F8: quatro outros perpétuos abertos o tempo todo: sempre 4 ou 5 abertos (> 3).
        "F8": (
            "F8",
            facts_of([*round_trips(BASE), *(at_start(c) for c in ("ETH", "SOL", "AVAX", "XRP"))]),
            "user",
        ),
        # F9: 4.824 de BTC e 4.825 de ETH: 49,995% no universo (< 50%).
        "F9": ("F9", facts_of([*round_trips(BASE), at_start("ETH", px=4_825.0)]), "user"),
        # F10: um fill de liquidação do próprio endereço.
        "F10": (
            "F10",
            facts_of([*round_trips(BASE), at_start("ETH", px=1.0, liquidated_user=WALLET)]),
            "user",
        ),
    }


@pytest.mark.unit
def test_base_wallet_passes_every_filter() -> None:
    assert failing(facts_of(round_trips(BASE))) == ()
    assert apply_filters(facts_of(round_trips(BASE)), None, real_params()) == ()


@pytest.mark.unit
@pytest.mark.parametrize("name", list(variants()))
def test_wallet_failing_exactly_one_filter_is_removed_by_it(name: str) -> None:
    """RF-SEL-02 CA-02.3: uma carteira construída para falhar em um filtro só é removida por ele, e
    por nenhum outro, e o funil a remove no estágio dele. Um caso por filtro (F3 em quatro).

    F3 `break` e F3 `invalid` e F3 `pnl` também provam RF-ING-03 CA-03.2, RF-ING-02 CA-02.5 e
    RF-ING-04 CA-04.2 pela parte da seleção.

    Mutações (uma por vez): F4 com `>` no lugar de `>=`: a variante F5 (20 episódios) caiu. F3 sem
    a checagem de episódio não conciliado: a variante `F3 unreconciled` caiu. F3 com `<` no lugar de
    `<=` na tolerância: caiu em `test_pnl_tolerance_is_inclusive_and_comes_from_the_file`.
    """
    expected, facts, role = variants()[name]
    assert failing(facts, role) == (expected,)
    funnel = run_funnel([facts], real_params(), {facts.address: role})
    removed = [s.name for s in funnel.stages if s.removed]
    assert removed == [expected]
    assert funnel.survivors == ()


def _pool() -> tuple[list[WalletFacts], dict[str, str]]:
    """Seis carteiras, de endereços 0x1 a 0x6, com os filtros que cada uma reprova:

    0x1 passa; 0x2 reprova F2; 0x3 reprova F4; 0x4 reprova F4 e F7; 0x5 reprova F10; 0x6 é vault.
    """
    from dataclasses import replace

    def make(address: str, rows: Rows, **kw: Any) -> WalletFacts:
        return replace(facts_of(rows, **kw), address=address)

    few = round_trips([3, 3, 3, 2, 2, 2, 2, 2])
    facts = [
        make("0x1", round_trips(BASE)),
        make("0x2", round_trips(BASE), account_value=1.0),
        make("0x3", few),
        make("0x4", round_trips([3, 3, 3, 2, 2, 2, 2, 2], crossed=lambda i: False)),
        make("0x5", [*round_trips(BASE), at_start("ETH", px=1.0, liquidated_user=WALLET)]),
        make("0x6", round_trips(BASE)),
    ]
    roles = {f.address: "user" for f in facts} | {"0x6": "vault"}
    return facts, roles


@pytest.mark.unit
def test_funnel_reports_counts_in_execution_order_and_order_does_not_change_result() -> None:
    """RF-SEL-02 CA-02.1. Ordem padrão F2, F3, ..., F10, F1, sobre as seis carteiras de `_pool`:

        F2   entram 6, sai 0x2                      -> 1
        F3   entram 5, nenhuma                      -> 0
        F4   entram 5, saem 0x3 e 0x4               -> 2
        F5, F6, F7, F8, F9: entram 3, nenhuma sai   -> 0 (0x4 já saiu; saiu em F4 e não em F7)
        F10  entram 3, sai 0x5                      -> 1
        F1   entram 2, sai 0x6                      -> 1
    Sobra 0x1. Na ordem inversa, F1 vem primeiro (entram 6, sai 0x6) e F7 antes de F4: sai 0x4 em
    F7 (entram 4) e 0x3 em F4 (entram 3). Os números por estágio mudam; o conjunto final não.

    Mutação: o estágio com `entered` igual ao total de carteiras (`len(facts)`) em vez das que
    chegaram a ele: o teste caiu em F3.
    """
    facts, roles = _pool()
    params = real_params()
    forward = run_funnel(facts, params, roles)
    assert [(s.name, s.entered, s.removed) for s in forward.stages] == [
        ("F2", 6, 1),
        ("F3", 5, 0),
        ("F4", 5, 2),
        ("F5", 3, 0),
        ("F6", 3, 0),
        ("F7", 3, 0),
        ("F8", 3, 0),
        ("F9", 3, 0),
        ("F10", 3, 1),
        ("F1", 2, 1),
    ]
    assert forward.survivors == ("0x1",)

    backward = run_funnel(facts, params, roles, order=tuple(reversed(DEFAULT_ORDER)))
    assert [(s.name, s.entered, s.removed) for s in backward.stages][:3] == [
        ("F1", 6, 1),
        ("F10", 5, 1),
        ("F9", 4, 0),
    ]
    by_name = {s.name: (s.entered, s.removed) for s in backward.stages}
    assert by_name["F7"] == (4, 1)
    assert by_name["F4"] == (3, 1)
    assert backward.survivors == forward.survivors

    rotated = run_funnel(facts, params, roles, order=(*DEFAULT_ORDER[4:], *DEFAULT_ORDER[:4]))
    assert rotated.survivors == forward.survivors
    # Em qualquer ordem, entra tudo no primeiro estágio e a soma do que sai é o que não sobrou.
    for funnel in (forward, backward, rotated):
        assert funnel.stages[0].entered == 6
        assert sum(s.removed for s in funnel.stages) == 5


@pytest.mark.unit
def test_funnel_needs_role_only_for_wallets_that_reach_f1_and_a_full_order() -> None:
    facts, roles = _pool()
    params = real_params()
    with pytest.raises(DataError, match="sem tipo de conta"):
        run_funnel(facts, params, {a: r for a, r in roles.items() if a != "0x1"})
    with pytest.raises(DataError, match="sem tipo de conta"):
        run_funnel(facts, params, None)
    with pytest.raises(DataError, match="uma vez cada"):
        run_funnel(facts, params, roles, order=("F2", "F3"))
    # Quem não chega a F1 não precisa de tipo de conta: só 0x1 e 0x6 chegam.
    partial = {a: r for a, r in roles.items() if a in ("0x1", "0x6")}
    assert run_funnel(facts, params, partial).survivors == ("0x1",)


@pytest.mark.unit
def test_n_star_stage_removes_wallets_without_reference() -> None:
    """RF-SEL-03 CA-03.2: o estágio `N*` remove quem não tem referência de exposição (ou nem
    consta em `references`)."""
    facts, roles = _pool()
    forward = run_funnel(facts, real_params(), roles)
    assert with_reference(forward, {"0x1": Reference(500.0, 10.0)}).survivors == ("0x1",)
    none = with_reference(forward, {"0x1": None})
    assert none.survivors == ()
    assert (none.stages[-1].name, none.stages[-1].entered, none.stages[-1].removed) == ("N*", 1, 1)
    assert with_reference(forward, {}).survivors == ()


# ─── Limiares: só do arquivo de parâmetros ───────────────────────────────────


def _threshold_cases() -> list[tuple[str, WalletFacts, str, dict[str, dict[str, Any]], bool]]:
    """(filtro, fatos, tipo de conta, {seção: mudança}, passa com o arquivo atual?).

    A carteira está na fronteira do limiar: com o valor do arquivo ela passa (ou reprova), e
    trocando o valor no arquivo ela muda de lado.
    """
    day = MS_PER_DAY
    return [
        ("F1", facts_of(round_trips(BASE)), "vault", {"filters": {"f1_role": "vault"}}, False),
        (
            "F2",
            facts_of(round_trips(BASE), account_value=30_000.0),
            "user",
            {"filters": {"f2_min_account_value_usd": 30_000.01}},
            True,
        ),
        (
            "F3",
            facts_of(round_trips(BASE)),
            "user",
            {"ingestion": {"max_fills_per_wallet": 47}},
            True,
        ),
        (
            "F3",
            facts_of(round_trips(BASE)),
            "user",
            {"ingestion": {"max_fills_per_wallet": 48}},
            True,
        ),
        (
            "F4",
            facts_of(round_trips(BASE)),
            "user",
            {"filters": {"f4_min_closed_episodes": 25}},
            True,
        ),
        ("F5", facts_of(round_trips(BASE)), "user", {"filters": {"f5_min_active_blocks": 9}}, True),
        ("F5", facts_of(round_trips(BASE)), "user", {"filters": {"f5_block_days": 1}}, True),
        (
            "F6",
            facts_of(round_trips(BASE, duration_ms=day)),
            "user",
            {"filters": {"f6_min_median_duration_h": 24.5}},
            True,
        ),
        (
            "F6",
            facts_of(round_trips(BASE, duration_ms=day)),
            "user",
            {"filters": {"f6_max_median_duration_days": 0.99}},
            True,
        ),
        (
            "F7",
            facts_of(round_trips(BASE, crossed=lambda i: i < 12)),
            "user",
            {"filters": {"f7_min_taker_opening_pct": 50.01}},
            True,
        ),
        (
            "F8",
            facts_of(round_trips(BASE)),
            "user",
            {"filters": {"f8_max_median_open_perps": 0}},
            True,
        ),
        (
            "F9",
            facts_of([*round_trips(BASE), at_start("ETH", px=4_824.0)]),
            "user",
            {"filters": {"f9_min_universe_notional_pct": 50.01}},
            True,
        ),
        (
            "F10",
            facts_of([*round_trips(BASE), at_start("ETH", px=1.0, liquidated_user=WALLET)]),
            "user",
            {"filters": {"f10_max_liquidated_fills": 1}},
            False,
        ),
    ]


@pytest.mark.unit
@pytest.mark.parametrize("index", range(13))
def test_thresholds_come_only_from_parameter_file(index: int) -> None:
    """RF-SEL-02 CA-02.2: cada limiar vem do arquivo de parâmetros e de nenhum outro lugar. Para
    cada limiar, uma carteira na fronteira muda de lado quando o valor no arquivo muda.

    Fronteiras (todas inclusivas): F2 30.000,00 contra 30.000,01; F3 48 fills contra o teto de
    48 e de 47; F4 24 episódios contra 25; F5 8 blocos ativos contra 9, e blocos de 1 dia (os
    episódios caem em poucos); F6 duração de 24 h contra o mínimo de 24,5 h e o máximo de 0,99
    dia; F7 12 de 24 aberturas a mercado (50% exatos) contra 50,01%; F8 mediana 1 contra o teto
    0; F9 4.824 de 9.648 (50% exatos) contra 50,01%; F10 uma liquidação contra o teto 0 e 1; F1
    "vault" contra o tipo `f1_role` trocado para "vault". As linhas F3 com teto 48 e F10 com teto
    1 mostram o outro lado: o limiar exato passa.

    Mutação: um limiar escrito como literal no filtro (F4 com `>= 20`): o caso F4 caiu.
    """
    name, facts, role, patch, passes_now = _threshold_cases()[index]
    params = real_params()
    patched = params
    for section, update in patch.items():
        patched = patched.model_copy(
            update={section: getattr(patched, section).model_copy(update=update)}
        )
    before = failing(facts, role, params)
    after = failing(facts, role, patched)
    if (name, patch) == ("F3", {"ingestion": {"max_fills_per_wallet": 48}}):
        assert (before, after) == ((), ())  # 48 fills no teto de 48: passa, inclusive
        return
    assert (name in before) is (not passes_now)
    assert (name in before) != (name in after)


@pytest.mark.unit
def test_pnl_tolerance_is_inclusive_and_comes_from_the_file() -> None:
    """F3: a divergência exata, tomada dos fatos, passa com a tolerância igual a ela e reprova com
    uma tolerância um pouco menor. Venda com 4,0 de excesso: 4 / 201 x 10^4 bps."""
    facts = facts_of(round_trips(BASE, pnl_error=4.0, error_at=7))
    value = facts.max_pnl_divergence_bps
    base = real_params()

    def with_tolerance(bps: float) -> Params:
        return base.model_copy(
            update={
                "reconciliation": base.reconciliation.model_copy(update={"pnl_tolerance_bps": bps})
            }
        )

    assert failing(facts, params=with_tolerance(value)) == ()
    assert failing(facts, params=with_tolerance(value - 1e-6)) == ("F3",)


@pytest.mark.unit
def test_undefined_measure_fails_the_filter_that_needs_it() -> None:
    """Sem episódio fechado a duração mediana é indefinida e F6 reprova; sem notional, F7 e F9."""
    facts = facts_of([])
    failed = failing(facts)
    assert {"F4", "F5", "F6", "F7", "F8", "F9"} <= set(failed)
    assert "F10" not in failed


@pytest.mark.unit
@pytest.mark.parametrize(
    ("facts", "patch"),
    [
        (
            facts_of(round_trips(BASE), account_value=30_000.0),
            {"filters": {"f2_min_account_value_usd": 30_000.0}},
        ),
        (facts_of(round_trips(BASE)), {"ingestion": {"max_fills_per_wallet": 48}}),
        (facts_of(round_trips(BASE)), {"filters": {"f4_min_closed_episodes": 24}}),
        (facts_of(round_trips(BASE)), {"filters": {"f5_min_active_blocks": 8}}),
        (
            facts_of(round_trips(BASE, duration_ms=MS_PER_DAY)),
            {"filters": {"f6_min_median_duration_h": 24.0}},
        ),
        (
            facts_of(round_trips(BASE, duration_ms=MS_PER_DAY)),
            {"filters": {"f6_max_median_duration_days": 1.0}},
        ),
        (
            facts_of(round_trips(BASE, crossed=lambda i: i < 12)),
            {"filters": {"f7_min_taker_opening_pct": 50.0}},
        ),
        (facts_of(round_trips(BASE)), {"filters": {"f8_max_median_open_perps": 1}}),
        (
            facts_of([*round_trips(BASE), at_start("ETH", px=4_824.0)]),
            {"filters": {"f9_min_universe_notional_pct": 50.0}},
        ),
        (
            facts_of([*round_trips(BASE), at_start("ETH", px=1.0, liquidated_user=WALLET)]),
            {"filters": {"f10_max_liquidated_fills": 1}},
        ),
    ],
)
def test_every_threshold_is_inclusive_at_the_boundary(
    facts: WalletFacts, patch: dict[str, dict[str, Any]]
) -> None:
    """Design §3.6: "ao menos" e "até" incluem o valor. A carteira está exatamente no limiar, e o
    limiar do arquivo é posto igual ao valor dela: passa.

    Mutação: F6 com `<` no lugar de `<=` no mínimo: o caso do mínimo de 24 h caiu."""
    params = real_params()
    for section, update in patch.items():
        params = params.model_copy(
            update={section: getattr(params, section).model_copy(update=update)}
        )
    assert failing(facts, params=params) == ()


@pytest.mark.unit
def test_f5_blocks_are_half_open_and_end_at_the_window_end() -> None:
    """F5: com 2 blocos de 7 dias, os blocos são [fim - 14 d, fim - 7 d) e [fim - 7 d, fim). Uma
    abertura em `fim - 14 d` está no primeiro (começo inclusivo) e uma em `fim - 7 d`, no segundo:
    2 blocos ativos. Uma abertura em `fim - 15 d` não está em nenhum.

    Mutações: bloco `(low, low + size]` : o caso das duas aberturas deu 1 e caiu. Blocos deslocados
    de um (`k - 1`): a abertura em `fim - 14 d` saiu e caiu.
    """
    from dataclasses import replace

    base = facts_of(round_trips(BASE))
    end = base.window_end
    params = real_params()
    two = params.model_copy(
        update={
            "filters": params.filters.model_copy(
                update={"f5_blocks": 2, "f5_block_days": 7, "f5_min_active_blocks": 2}
            )
        }
    )
    both = replace(base, open_times=(Ms(end - 14 * MS_PER_DAY), Ms(end - 7 * MS_PER_DAY)))
    assert "F5" not in failing(both, params=two)
    only_old = replace(base, open_times=(Ms(end - 14 * MS_PER_DAY), Ms(end - 15 * MS_PER_DAY)))
    assert "F5" in failing(only_old, params=two)
