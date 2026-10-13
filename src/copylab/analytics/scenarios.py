"""Grade de cenários, referência de Δ = 0, decomposição do custo de copiar e aviso de cenário
irrealista (RF-SIM-08, RF-SIM-04 CA-04.2, RF-ANA-02 CA-02.2, RF-ANA-03; design §3.8, precisões do
1.6).

Quem simula é de quem chama: estas funções recebem um ``run`` que, dado um cenário ou um
:class:`~copylab.sim.mirror.Frictions`, devolve a carteira. Assim a mesma fonte de preço, a mesma
coorte e o mesmo funding valem em todas as execuções, e nada aqui lê dado.
"""

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, replace
from typing import Literal

from copylab.analytics.portfolio import PortfolioResult
from copylab.exceptions import ConfigError
from copylab.params import Params
from copylab.sim.mirror import Frictions, Mirror

__all__ = [
    "Grid",
    "GridCell",
    "Route",
    "Scenario",
    "ScenarioWarning",
    "Step",
    "StepName",
    "decomposition",
    "decomposition_total",
    "delay_reference",
    "frictions_for",
    "mirror_for",
    "run_grid",
    "scenarios",
    "unrealistic_warnings",
]

Route = Literal["A", "B"]

# ─── Grade (RF-SIM-08) ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Scenario:
    """Um cenário da grade: capital e K, atraso, multiplicador do slippage primário."""

    capital: float
    k: int
    delay_ms: int
    slippage_multiplier: float
    primary: bool


def scenarios(route: Route, params: Params) -> tuple[Scenario, ...]:
    """A grade de §7.2: os nove pares de capital e Δ com o slippage primário e, só na Rota A, a
    sensibilidade de slippage no capital e no Δ primários. Onze cenários na Rota A, nove na B.
    Só o cenário primário (capital, Δ e slippage primários) alimenta o veredito."""
    capital, delay = params.capital, params.delay
    out = [
        Scenario(usd, k, d, 1.0, primary=usd == capital.primary_usd and d == delay.primary_ms)
        for usd, k in zip(capital.grid_usd, capital.grid_k, strict=True)
        for d in delay.grid_ms
    ]
    if route == "A":
        k_primary = params.cohort.k_for(capital.primary_usd)
        out.extend(
            Scenario(capital.primary_usd, k_primary, delay.primary_ms, multiplier, primary=False)
            for multiplier in params.slippage.sensitivity_multipliers
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class GridCell:
    """Um cenário rodado nas duas variantes: cópia completa e só compras. ``None`` é coorte
    vazia."""

    scenario: Scenario
    full: PortfolioResult | None
    long_only: PortfolioResult | None


@dataclass(frozen=True, slots=True)
class Grid:
    route: Route
    cells: tuple[GridCell, ...]

    @property
    def primary(self) -> GridCell:
        """O cenário primário, a única célula que alimenta o veredito (``.full``)."""
        return next(cell for cell in self.cells if cell.scenario.primary)


def run_grid(
    run: Callable[[Scenario, bool], PortfolioResult | None], route: Route, params: Params
) -> Grid:
    """Roda todos os cenários da grade, cada um na cópia completa e na variante só compras.

    ``run(cenário, long_only)`` é de quem chama. Raises:
        ConfigError: se a grade não tem exatamente um cenário primário.
    """
    grid = scenarios(route, params)
    if sum(s.primary for s in grid) != 1:
        raise ConfigError("A grade precisa ter exatamente um cenário primário.")
    return Grid(route, tuple(GridCell(s, run(s, False), run(s, True)) for s in grid))


def frictions_for(
    scenario: Scenario, primary_slippage_bps: Mapping[str, float], params: Params
) -> Frictions:
    """Os atritos de um cenário: o atraso dele, o slippage primário vezes o multiplicador, a taxa
    taker, funding e restrições de tamanho ligados. Na Rota B, ``primary_slippage_bps`` é vazio."""
    return Frictions(
        delay_ms=scenario.delay_ms,
        slippage_bps={c: v * scenario.slippage_multiplier for c, v in primary_slippage_bps.items()},
        fee_bps=params.fees.taker_bps,
        funding=True,
        size_constraints=True,
    )


def mirror_for(params: Params, *, long_only: bool) -> Mirror:
    """A regra de espelhamento dos parâmetros: pico, teto, ordem mínima."""
    return Mirror(
        peak=params.mirror.peak_exposure,
        cap=params.mirror.leverage_cap,
        min_notional=params.mirror.min_order_usd,
        long_only=long_only,
    )


# ─── Referência de Δ = 0 (RF-ANA-02 CA-02.2) ─────────────────────────────────


def delay_reference(
    run: Callable[[Frictions], PortfolioResult], primary: Frictions
) -> PortfolioResult:
    """A mesma coorte e o mesmo cenário com Δ = 0, na mesma fonte de preço (a de ``run``): a
    referência do custo do atraso. Só ``delay_ms`` muda."""
    return run(replace(primary, delay_ms=0))


# ─── Decomposição (RF-ANA-03) ────────────────────────────────────────────────

StepName = Literal["ideal", "delay", "slippage", "fees", "funding", "size_constraints"]


@dataclass(frozen=True, slots=True)
class Step:
    """Um degrau: a simulação completa que liga os fatores até ele."""

    name: StepName
    frictions: Frictions
    result: PortfolioResult
    net_return: float
    delta: float | None  # diferença para o degrau anterior; ``None`` no primeiro
    inert: str | None  # por que o fator não pode mudar nada no cenário primário


def decomposition(run: Callable[[Frictions], PortfolioResult], primary: Frictions) -> list[Step]:
    """Seis simulações, cada uma com um fator a mais do cenário primário, na ordem de RF-ANA-03
    CA-03.1: (1) cópia ideal, sem atraso, custo nem restrição de tamanho; (2) atraso; (3)
    slippage; (4) taxas; (5) funding; (6) lote, ordem mínima e teto, que é o primário.

    ``inert`` diz, para o relatório, por que um degrau não muda nada: o fator é zero ou está
    desligado no cenário primário (na Rota B, o slippage é sempre vazio)."""
    ideal = Frictions(0, {}, 0.0, False, False)
    with_delay = replace(ideal, delay_ms=primary.delay_ms)
    with_slippage = replace(with_delay, slippage_bps=primary.slippage_bps)
    with_fees = replace(with_slippage, fee_bps=primary.fee_bps)
    with_funding = replace(with_fees, funding=primary.funding)
    complete = replace(with_funding, size_constraints=primary.size_constraints)
    plan: tuple[tuple[StepName, Frictions, str | None], ...] = (
        ("ideal", ideal, None),
        ("delay", with_delay, "delay_zero" if primary.delay_ms == 0 else None),
        (
            "slippage",
            with_slippage,
            "no_slippage" if not any(primary.slippage_bps.values()) else None,
        ),
        ("fees", with_fees, "fee_zero" if primary.fee_bps == 0 else None),
        ("funding", with_funding, "funding_off" if not primary.funding else None),
        (
            "size_constraints",
            complete,
            "size_constraints_off" if not primary.size_constraints else None,
        ),
    )
    steps: list[Step] = []
    for name, frictions, inert in plan:
        result = run(frictions)
        net = result.net_return
        delta = None if not steps else net - steps[-1].net_return
        steps.append(Step(name, frictions, result, net, delta, inert))
    return steps


def decomposition_total(steps: list[Step]) -> float:
    """O custo total de copiar: o retorno do último degrau menos o do primeiro (RF-ANA-03
    CA-03.2). A soma das diferenças entre degraus é igual a ele."""
    return steps[-1].net_return - steps[0].net_return


# ─── Aviso de cenário irrealista (RF-SIM-04 CA-04.2) ─────────────────────────

ScenarioWarning = Literal["fee_zero", "slippage_zero"]


def unrealistic_warnings(
    frictions: Frictions, route: Route, universe: Set[str]
) -> tuple[ScenarioWarning, ...]:
    """Os avisos de um cenário: ``fee_zero`` com taxa zero e, só na Rota A, ``slippage_zero`` se
    algum ativo do universo não tem slippage positivo. Na Rota B o livro já é o preço real e o
    mapa de slippage é vazio de propósito."""
    warnings: list[ScenarioWarning] = []
    if frictions.fee_bps == 0:
        warnings.append("fee_zero")
    if route == "A" and any(not frictions.slippage_bps.get(c, 0.0) > 0.0 for c in universe):
        warnings.append("slippage_zero")
    return tuple(warnings)
