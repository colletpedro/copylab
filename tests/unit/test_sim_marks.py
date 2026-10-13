"""Marcação sem segundo anterior (design 1.6, §3.7, respostas do Bloco D; ADR-0003).

Preço inventado é pior que erro: `mark` sem nenhum segundo anterior continua `DataError`. Duas
garantias, uma por teste: o laço só marca ativo em que a subconta tem posição (inclusive no instante
inicial), e o erro de uma execução real diz o ativo e o instante, para virar lacuna reportada.

Fixtures de papel (RNF-03), sem dado real. Prova de dente, feita à mão em 2026-10-12 e restaurada
(cada mutação está na docstring do teste que a pega).
"""

import pytest

from copylab.exceptions import DataError
from copylab.leader import LeaderEvent
from copylab.sim.funding import FundingTable
from copylab.sim.loop import SubaccountResult, run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.prices import ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import Ms
from copylab.windows import Window

END = 300_000


def _event(t: int, coin: str, position: float) -> LeaderEvent:
    return LeaderEvent(
        t=Ms(t),
        coin=coin,
        kind="perp",
        prev_position=0.0,
        position=position,
        touched_zero=True,
        px=100.0,
        notional=abs(position) * 100.0,
        unobserved=False,
        n_fills=1,
    )


def _run(events: list[LeaderEvent], first_second: dict[str, int]) -> SubaccountResult:
    """Capital 1.000, N* = 1.000, sem custo nem atraso, funding ligado. Cada ativo vale 100 por
    segundo, a partir do segundo dado: antes disso a série não tem barra nenhuma."""
    bars = {
        coin: [ProxyBar(s, 100.0, 100.0, 100.0) for s in range(first, END // 1_000)]
        for coin, first in first_second.items()
    }
    hours = {Ms(0): 0.0, Ms(3_600_000): 0.0}
    return run_subaccount(
        LeaderTape(events),
        1_000.0,
        frozenset(first_second),
        ProxySource(bars),
        FundingTable({coin: hours for coin in first_second}),
        dict.fromkeys(first_second, 0.01),
        1_000.0,
        Window(Ms(0), Ms(END)),
        Frictions(0, {}, 0.0, True, True),
        Mirror(1.0, 1.0, 10.0, False),
    )


@pytest.mark.unit
def test_loop_never_marks_an_asset_without_position() -> None:
    """Design 1.6, resposta 3 (i). O ativo `late` só tem barras a partir do segundo 200, mas a
    subconta nunca o tem em carteira: o laço não o marca no instante inicial (segundo 0), nas
    amostras, no funding nem na execução de `early`. Se marcasse, `mark("late", 0)` levantaria
    `DataError`. `early` abre 5 a 100: razão
    5 x 100 / 1.000 = 0,5, alvo 0,5 x 1.000 = 500, tamanho 5. Sem custo nem variação de preço, o
    patrimônio fecha em 1.000.

    Mutação registrada: `Engine.marks` passar a marcar todo o universo
    (`coins = set(self._universe)` no lugar dos ativos com posição) faz o teste cair com
    `DataError` de `late` no segundo 0."""
    result = _run([_event(10_000, "early", 5.0)], {"early": 0, "late": 200})
    assert result.final_equity == pytest.approx(1_000.0)
    assert [o.coin for o in result.orders] == ["early"]
    assert result.reconciliation.ok


@pytest.mark.unit
def test_mark_without_prior_second_names_asset_and_instant() -> None:
    """Design 1.6, resposta 3 (ii). A série de `zed` começa no segundo 10, e o evento do líder cai
    exatamente nele: a subconta abre posição na primeira barra e a marcação seguinte, ainda nesse
    segundo, não tem segundo anterior. O `DataError` precisa dizer o ativo (`zed`) e o instante
    (`1970-01-01T00:00:10`), para a CLI poder registrar a lacuna.

    Mutação registrada: trocar a mensagem de `_BoundProxy.mark` por uma sem o ativo e o instante
    (`"Sem preço para marcar."`) faz o teste cair."""
    with pytest.raises(DataError) as caught:
        _run([_event(10_000, "zed", 5.0)], {"zed": 10})
    message = str(caught.value)
    assert "zed" in message
    assert "1970-01-01T00:00:10" in message
