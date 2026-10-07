"""Testes de `copylab.ports`: o repositório limitado pelo corte (RF-SEL-01 CA-01.1).

O repositório interno é falso e só registra as chamadas. O que se prova é a
construção: com corte T, toda leitura cortada com fim > T levanta `LookaheadError`
*antes* de chegar ao repositório interno; fim = T é permitido, porque a janela
`[início, T)` só contém instantes < T; leaderboard, lotes e tipo de conta passam.

Prova de dente de `test_selection_reading_at_or_after_cutoff_raises`, feita à mão em
2026-10-07 e restaurada, uma mutação por vez em `BoundedRepository`:

- `_guard` com `end > self._cutoff + 1` (deixa passar a leitura que inclui o próprio
  T): falharam os 8 casos com fim = T + 1, e `test_content_hash_of_an_unknown_table_is_cut`.
- `fills` sem a chamada a `_guard`: falhou o caso `fills`.
- `content_hash` sem a guarda: falharam o caso `content_hash` e
  `test_content_hash_of_an_unknown_table_is_cut`.
- `_guard` com `>=` no lugar de `>`: não cai neste teste, cai em
  `test_reading_up_to_the_cutoff_is_allowed`, que existe para isso.
"""

from collections.abc import Callable, Sequence

import polars as pl
import pytest

from copylab.exceptions import LookaheadError
from copylab.ports import UNCUT_TABLES, BoundedRepository, Repository
from copylab.timeutil import Ms

#: Corte da Rota A, 2026-09-01T00:00:00Z (ver `test_timeutil.py`).
T = Ms(1_788_220_800_000)
#: Início da janela de seleção da Rota A, 2026-07-01: 62 dias antes do corte.
#: 62 * 86.400.000 = 5.356.800.000; T - 5.356.800.000 = 1.782.864.000.000.
START = Ms(1_782_864_000_000)


class RecordingRepository:
    """Repositório falso: devolve uma tabela com o nome do método e anota a chamada."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def _answer(self, name: str, *args: object) -> pl.DataFrame:
        self.calls.append((name, args))
        return pl.DataFrame({"method": [name]})

    def leaderboard(self, snapshot: Ms) -> pl.DataFrame:
        return self._answer("leaderboard", snapshot)

    def meta(self, snapshot: Ms) -> pl.DataFrame:
        return self._answer("meta", snapshot)

    def roles(self, snapshot: Ms) -> pl.DataFrame:
        return self._answer("roles", snapshot)

    def coverage(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("coverage", address, start, end)

    def fills(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("fills", address, start, end)

    def funding(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("funding", coin, start, end)

    def proxy(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("proxy", coin, start, end)

    def bbo(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("bbo", coin, start, end)

    def book(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("book", coin, start, end)

    def gaps(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._answer("gaps", coin, start, end)

    def content_hash(self, table: str, keys: Sequence[str], start: Ms, end: Ms) -> str:
        self.calls.append(("content_hash", (table, tuple(keys), start, end)))
        return f"hash:{table}"


Read = Callable[[Repository, Ms], object]

#: As oito leituras cortadas, cada uma com janela [START, end).
CUT_READS: dict[str, Read] = {
    "coverage": lambda r, end: r.coverage("0xabc", START, end),
    "fills": lambda r, end: r.fills("0xabc", START, end),
    "funding": lambda r, end: r.funding("BTC", START, end),
    "proxy": lambda r, end: r.proxy("BTC", START, end),
    "bbo": lambda r, end: r.bbo("BTC", START, end),
    "book": lambda r, end: r.book("BTC", START, end),
    "gaps": lambda r, end: r.gaps("BTC", START, end),
    "content_hash": lambda r, end: r.content_hash("fills", ["time_ms", "seq"], START, end),
}


def _bounded() -> tuple[BoundedRepository, RecordingRepository]:
    inner = RecordingRepository()
    return BoundedRepository(inner, T), inner


@pytest.mark.unit
def test_bounded_repository_satisfies_the_read_protocol() -> None:
    """A seleção recebe o repositório limitado onde se espera um `Repository`."""
    bounded, _ = _bounded()
    as_protocol: Repository = bounded
    assert as_protocol.fills("0xabc", START, T)["method"].to_list() == ["fills"]
    assert bounded.cutoff == T


@pytest.mark.unit
@pytest.mark.parametrize("read", CUT_READS.values(), ids=CUT_READS.keys())
def test_selection_reading_at_or_after_cutoff_raises(read: Read) -> None:
    """RF-SEL-01 CA-01.1, na parte do repositório (T-003).

    Fim = T + 1 ms: a janela [START, T + 1) contém o instante T, que já é da
    avaliação. A leitura levanta, e o repositório interno não é chamado.
    """
    bounded, inner = _bounded()
    with pytest.raises(LookaheadError, match=r"passa do corte 2026-09-01T00:00:00\.000Z"):
        read(bounded, Ms(T + 1))
    assert inner.calls == []


@pytest.mark.unit
@pytest.mark.parametrize("read", CUT_READS.values(), ids=CUT_READS.keys())
def test_reading_up_to_the_cutoff_is_allowed(read: Read) -> None:
    """Fim = T: a janela [START, T) só tem instantes < T. A leitura chega ao interno."""
    bounded, inner = _bounded()
    read(bounded, T)
    assert len(inner.calls) == 1
    assert inner.calls[0][1][-1] == T


@pytest.mark.unit
@pytest.mark.parametrize("name", ["leaderboard", "meta", "roles"])
def test_leaderboard_lots_and_account_type_pass_the_cutoff(name: str) -> None:
    """Snapshot de outubro (depois do corte de setembro) é lido sem erro (design §3.2)."""
    october = Ms(T + 40 * 86_400_000)
    bounded, inner = _bounded()
    table = getattr(bounded, name)(october)
    assert table["method"].to_list() == [name]
    assert inner.calls == [(name, (october,))]


@pytest.mark.unit
@pytest.mark.parametrize("table", sorted(UNCUT_TABLES))
def test_content_hash_of_uncut_tables_passes_the_cutoff(table: str) -> None:
    """O congelamento guarda o hash dos três snapshots, que são posteriores ao corte."""
    october = Ms(T + 40 * 86_400_000)
    bounded, _ = _bounded()
    assert bounded.content_hash(table, ["address"], october, Ms(october + 1)) == f"hash:{table}"


@pytest.mark.unit
def test_content_hash_of_an_unknown_table_is_cut() -> None:
    """Tabela que não está na lista de exceções é cortada: o default é o lado seguro."""
    bounded, _ = _bounded()
    with pytest.raises(LookaheadError):
        bounded.content_hash("trades", ["time_ms"], START, Ms(T + 1))


@pytest.mark.unit
def test_uncut_tables_are_exactly_the_three_the_design_declares() -> None:
    assert frozenset({"leaderboard", "meta", "roles"}) == UNCUT_TABLES
