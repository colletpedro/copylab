"""Teste de aceitação: a mutação do futuro (T-044, RF-SIM-01 CA-01.2, ADR-0003 e ADR-0008).

Uma ordem do seguidor executada em `tau` só pode depender de eventos do líder com instante até
`tau - delay`. O teste prova isso por falseamento, e o enunciado é pelo relógio da execução: dado
um corte `c`, alterar arbitrariamente

  (i)   todo evento do líder com instante maior que `c`,
  (ii)  todo preço posterior a `c + delay` e à última observação já consumida pelas execuções até
        `c + delay`, e
  (iii) todo funding de hora posterior a `c + delay`,

refazer a simulação, e conferir que o conjunto de ordens executadas até `c + delay` é idêntico. A
alteração também mexe nos instantes (eventos que somem ou aparecem, segundos sem negócio que passam
a ter negócio e vice-versa), porque o laço decide quando acordar por eles.

A fronteira é escrita com cuidado (ADR-0003): a decisão em `t` executa legitimamente com o preço do
segundo de `tau`, e esse preço não é livre para alterar. O livre é o que começa depois da última
observação consumida, medida por `horizon()`, e cujo segundo termina depois de `c + delay`. Um teste
que alterasse cedo demais acusaria lookahead onde há execução correta.

O cenário é semeado, com buracos de preço que atrasam execuções (a ordem executa na primeira
observação, e `exec_t` passa de `nominal_t`): o caso que o ADR-0008 reenunciou.

Prova de dente, feita à mão em 2026-10-12 e restaurada, uma mutação de lookahead por vez (listadas
na docstring do teste, e no HANDOFF).
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from copylab.leader import LeaderEvent
from copylab.sim.cursor import CursorView
from copylab.sim.funding import FundingTable
from copylab.sim.loop import run_subaccount
from copylab.sim.mirror import Frictions, Mirror
from copylab.sim.model import Ladder, Order, Side
from copylab.sim.prices import PriceSource, ProxyBar, ProxySource
from copylab.sim.tape import LeaderTape
from copylab.timeutil import MS_PER_HOUR, MS_PER_SECOND, Ms
from copylab.windows import Window

COINS = ("a", "b", "c")
HOURS = 2
SECONDS = HOURS * 3_600
END = HOURS * MS_PER_HOUR
REFERENCE = 1_000.0


class Recording:
    """`ProxySource` que anota, a cada leitura de preço de execução (a escada, e a pergunta
    `available_from` sobre um instante que já chegou), o instante do cursor, o ativo e o início do
    segundo consumido. O horizonte global de `PriceSource.horizon()` mistura os
    ativos; o teste usa o consumido por ativo, que é mais fino e mais exigente: a barra de outro
    ativo no mesmo segundo ainda não foi lida e pode ser alterada."""

    def __init__(self, bars: dict[str, list[ProxyBar]]) -> None:
        self._proxy = ProxySource(bars)
        self.trace: list[tuple[Ms, str, Ms]] = []

    def bind(self, cursor: CursorView) -> PriceSource:
        inner = self._proxy.bind(cursor)
        trace = self.trace

        class Bound:
            def available_from(self, coin: str, t: Ms) -> Ms | None:
                if t <= cursor.now:  # perguntar por um instante que já chegou lê o resto do segundo
                    trace.append((cursor.now, coin, Ms(t // MS_PER_SECOND * MS_PER_SECOND)))
                return inner.available_from(coin, t)

            def ladder(self, coin: str, t: Ms, side: Side) -> Ladder:
                result = inner.ladder(coin, t, side)
                trace.append((cursor.now, coin, Ms(t // MS_PER_SECOND * MS_PER_SECOND)))
                return result

            def mark(self, coin: str, t: Ms) -> float:
                return inner.mark(coin, t)

            def horizon(self) -> Ms:
                return inner.horizon()

        return Bound()


@dataclass(frozen=True, slots=True)
class World:
    bars: dict[str, list[ProxyBar]]
    events: list[LeaderEvent]
    rates: dict[str, dict[Ms, float]]


def make_bars(
    rng: random.Random, coin: str, seconds: range, price: float, *, gaps: bool
) -> list[ProxyBar]:
    out: list[ProxyBar] = []
    gap_until = -1
    for second in seconds:
        price *= 1.0 + rng.uniform(-0.01, 0.01)
        if gaps and second > 5 and second > gap_until and rng.random() < 0.01:
            gap_until = second + rng.randint(8, 40)  # um buraco de preço: atrasa as execuções
        if second <= gap_until or (gaps and second > 5 and rng.random() < 0.15):
            continue
        out.append(ProxyBar(second, price * 0.998, price * 1.002, price))
    return out


def make_events(rng: random.Random, after: int, count: int) -> list[LeaderEvent]:
    events = []
    for _ in range(count):
        position = rng.choice((-1, 1)) * rng.uniform(0.0, 14.0)
        position = 0.0 if rng.random() < 0.15 else position
        events.append(
            LeaderEvent(
                t=Ms(rng.randint(after + 1, END - 1)),
                coin=rng.choice(COINS),
                kind="perp",
                prev_position=0.0,
                position=position,
                touched_zero=rng.random() < 0.6 or position == 0.0,
                px=100.0 * rng.uniform(0.9, 1.1),
                notional=abs(position) * 100.0,
                unobserved=rng.random() < 0.1,
                n_fills=1,
            )
        )
    return events


def make_world(seed: int) -> World:
    rng = random.Random(seed)
    bars = {c: make_bars(rng, c, range(SECONDS), 100.0, gaps=True) for c in COINS}
    rates = {
        c: {Ms(h * MS_PER_HOUR): rng.uniform(-3e-4, 3e-4) for h in range(HOURS + 2)} for c in COINS
    }
    return World(bars, make_events(rng, 5_000, 30), rates)


def mutate_future(world: World, seed: int, cut: int, delay: int, consumed: dict[str, int]) -> World:
    """Altera arbitrariamente o que só pode ser futuro para as ordens até `cut + delay`."""
    rng = random.Random(seed * 7919 + cut)
    limit = cut + delay
    bars: dict[str, list[ProxyBar]] = {}
    for coin, series in world.bars.items():
        # Livre é a barra que começa depois da última observação consumida do ativo e cujo
        # segundo termina depois de `cut + delay`: começa depois de `max(consumido, limit - 999)`.
        threshold = max(consumed.get(coin, -1), limit - 999)
        first_free = threshold // MS_PER_SECOND + 1
        kept = [b for b in series if b.second * MS_PER_SECOND <= threshold]
        redone = make_bars(
            rng, coin, range(first_free, SECONDS), series[0].last * rng.uniform(0.4, 2.5), gaps=True
        )
        bars[coin] = kept + redone
    events = [e for e in world.events if e.t <= cut] + make_events(rng, cut, 25)
    rates = {
        coin: {h: (r if h <= limit else rng.uniform(-9e-4, 9e-4)) for h, r in hours.items()}
        for coin, hours in world.rates.items()
    }
    return World(bars, events, rates)


def cut_points(world: World, delay: int) -> list[tuple[int, str]]:
    """Os cortes: instantes soltos, um tal que `c + delay` cai na hora cheia de 1 h (funding e
    marcação do instante em jogo) e cortes colados em eventos do líder: logo antes de um evento
    (`t - 1`, que o põe dentro de `(c, c + delay]`) e no instante dele (`t`, quando a execução cai
    em `c + delay`)."""
    cuts = [(int(END * f), "solto") for f in (0.15, 0.35, 0.55, 0.75)]
    cuts.append((MS_PER_HOUR - delay, "hora cheia"))
    ordered = sorted(world.events, key=lambda e: e.t)
    for event in (ordered[4], ordered[11], ordered[19]):
        cuts += [(event.t - 1, "antes do evento"), (event.t, "no evento")]
    return cuts


def simulate(world: World, delay: int, feed: Recording | None = None) -> list[Order]:
    result = run_subaccount(
        LeaderTape(world.events),
        REFERENCE,
        frozenset(COINS),
        feed if feed is not None else ProxySource(world.bars),
        FundingTable(world.rates),
        dict.fromkeys(COINS, 0.01),
        1_000.0,
        Window(Ms(0), Ms(END)),
        Frictions(delay, dict.fromkeys(COINS, 10.0), 5.0, True, True),
        Mirror(1.0, 1.0, 10.0, False),
    )
    return list(result.orders)


def consumed_at(trace: Sequence[tuple[Ms, str, Ms]], limit: int) -> dict[str, int]:
    """Por ativo, o início do segundo mais avançado já consumido pelas execuções até `limit`."""
    seen: dict[str, int] = {}
    for now, coin, second_start in trace:
        if now <= limit:
            seen[coin] = max(seen.get(coin, -1), second_start)
    return seen


@pytest.mark.unit
@pytest.mark.parametrize("delay", [0, 1_000, 5_000])
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_mutating_future_does_not_change_orders_decided_before_cutoff(
    seed: int, delay: int
) -> None:
    """RF-SIM-01 CA-01.2, o teste de aceitação da fase, pelo relógio da execução.

    Para cada cenário semeado e cada corte `c` (`cut_points`: instantes soltos, um tal que `c +
    delay`
    cai na hora cheia de 1 h, e cortes colados em eventos do líder),
    simula o mundo original e o mundo com o futuro alterado, e exige que as ordens com `exec_t <=
    c + delay` sejam idênticas, ordem por ordem, com os mesmos preços, tamanhos, taxas e instantes.
    O teste exige também que a rodada não seja vazia: há ordens antes do corte, há ordens atrasadas
    por falta de preço, e a alteração muda o que vem depois do corte (senão o teste não provaria
    nada).

    Mutações de lookahead registradas, todas feitas à mão e restauradas (as cinco derrubam este
    teste, de 10 a 15 dos 15 cenários cada): (1) o laço lê o evento no instante dele, sem esperar
    o atraso (`bind(view, 0)`, e `wake`, `until(now)` e `last_read` sem `delay`); (2) o preço da
    ordem sai da barra do segundo seguinte (`ladder` lê `index + 1`); (3) a marcação usa o último
    preço do segundo corrente, e não o do anterior (`mark` com `bisect_right`), isto é, marca pelo
    fim do segundo; (4) o funding da hora seguinte é usado na hora corrente (`rate(coin, now + 1
    h)`, sem a guarda); (5) o laço espia o evento seguinte da fita e o põe na visão (leitura da
    fita por baixo do `until`). A sexta, usar o preço do fill do líder como preço do seguidor,
    não é lookahead no tempo (o fill é de `t <= tau - delay`) e não cai aqui: cai em
    `test_follower_price_is_independent_of_leader_fill_price`.

    Duas coisas deixaram o teste mais exigente do que a primeira versão, e a primeira não pegava as
    mutações (1) e (3): os cortes colados em eventos (`c = t - 1` e `c = t`), porque só assim há
    evento dentro de `(c, c + delay]`; e o horizonte por ativo, porque a barra de outro ativo no
    mesmo segundo ainda não foi lida. Com o teste mais fino apareceu um caso legítimo: perguntar a
    `available_from` se um ativo tem negócio no segundo de um instante que já chegou (para decidir
    se uma redução do teto pode ser enviada) lê o resto desse segundo, como a escada, e a fonte
    agora o conta no horizonte.
    """
    world = make_world(seed)
    base_feed = Recording(world.bars)
    base = simulate(world, delay, base_feed)
    cuts = [cut for cut, _ in cut_points(world, delay)]
    for cut in cuts:
        limit = cut + delay
        consumed = consumed_at(base_feed.trace, limit)
        mutated_world = mutate_future(world, seed, cut, delay, consumed)
        mutated = simulate(mutated_world, delay)
        until_base = [o for o in base if o.exec_t <= limit]
        until_mutated = [o for o in mutated if o.exec_t <= limit]
        assert until_mutated == until_base, (seed, delay, cut)


@pytest.mark.unit
def test_the_acceptance_scenarios_are_not_vacuous() -> None:
    """O teste acima só prova alguma coisa se as rodadas têm ordens antes do corte, ordens atrasadas
    por falta de preço e uma alteração que muda o que vem depois. Roda depois do teste de aceitação
    (ordem de arquivo, sem sorteio de ordem: `pytest-randomly` reordena, então este teste refaz as
    contas com os mesmos cenários em vez de ler o contador global)."""
    stats = {"scenarios": 0, "with_orders": 0, "with_delayed": 0, "effective": 0}
    for seed in (1, 2, 3):
        for delay in (0, 5_000):
            world = make_world(seed)
            feed = Recording(world.bars)
            base = simulate(world, delay, feed)
            for cut in (int(END * 0.35), int(END * 0.75)):
                limit = cut + delay
                consumed = consumed_at(feed.trace, limit)
                mutated = simulate(mutate_future(world, seed, cut, delay, consumed), delay)
                stats["scenarios"] += 1
                stats["with_orders"] += any(o.exec_t <= limit for o in base)
                stats["with_delayed"] += any(
                    o.exec_t <= limit and o.exec_t > o.nominal_t for o in base
                )
                stats["effective"] += [o for o in base if o.exec_t > limit] != [
                    o for o in mutated if o.exec_t > limit
                ]
    assert stats["with_orders"] >= 9
    assert stats["with_delayed"] >= 3
    assert stats["effective"] >= 9
