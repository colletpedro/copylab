"""Protocolo de leitura de dados e o repositório limitado pelo corte (design §3.2, ADR-0006).

Livro-razão, seleção, simulador e analytics leem dados só por :class:`Repository`, sem
saber de arquivo nem de diretório. ``copylab.storage`` implementa o protocolo. A escrita
fica numa interface separada, que só ingestão, coletor e CLI recebem.

A seleção só recebe um :class:`BoundedRepository`. É isso que prova RF-SEL-01 CA-01.1 por
construção: qualquer leitura de fills, cobertura, funding, proxy ou livro com fim depois
do corte levanta :class:`~copylab.exceptions.LookaheadError` antes de chegar ao dado.

**O que fica fora do corte.** Leaderboard, tamanhos de lote (``meta``) e tipo de conta
(``roles``) são coletados hoje, depois do corte da Rota A, porque a API não os devolve
para uma data passada, e nenhum dos três traz desempenho. A seleção usa o snapshot mais
recente de cada um, e o instante e o hash dos três vão para o congelamento.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final, Protocol

from copylab.exceptions import LookaheadError
from copylab.timeutil import Ms, iso

if TYPE_CHECKING:
    import polars as pl

__all__ = ["UNCUT_TABLES", "BoundedRepository", "Repository"]

#: Tabelas que o corte não limita (design §3.2, "O que fica fora do corte"). Toda outra
#: tabela é cortada, inclusive uma que ainda não exista: o default é o lado seguro.
UNCUT_TABLES: Final = frozenset({"leaderboard", "meta", "roles"})


class Repository(Protocol):
    """Leitura de dados por janela semiaberta ``[start, end)``, em ``Ms``."""

    def leaderboard(self, snapshot: Ms) -> pl.DataFrame: ...
    def meta(self, snapshot: Ms) -> pl.DataFrame: ...
    def roles(self, snapshot: Ms) -> pl.DataFrame: ...
    def coverage(self, address: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def fills(self, address: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def funding(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def proxy(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def bbo(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def book(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def gaps(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def content_hash(self, table: str, keys: Sequence[str], start: Ms, end: Ms) -> str: ...


class BoundedRepository:
    """Envolve um :class:`Repository` e levanta ``LookaheadError`` em qualquer leitura com
    fim > ``cutoff``.

    Como as janelas são semiabertas, ``end == cutoff`` lê só instantes menores que o
    corte e é permitido; ``end > cutoff`` alcançaria o corte e é recusado antes de o
    repositório interno ser chamado.
    """

    def __init__(self, inner: Repository, cutoff: Ms) -> None:
        self._inner = inner
        self._cutoff = cutoff

    @property
    def cutoff(self) -> Ms:
        return self._cutoff

    def _guard(self, what: str, end: Ms) -> None:
        if end > self._cutoff:
            raise LookaheadError(
                f"Leitura de {what} até {iso(end)} passa do corte {iso(self._cutoff)}: "
                "a seleção só lê instantes anteriores ao corte (RF-SEL-01 CA-01.1)."
            )

    # Fora do corte: snapshots coletados hoje, sem desempenho (design §3.2).

    def leaderboard(self, snapshot: Ms) -> pl.DataFrame:
        return self._inner.leaderboard(snapshot)

    def meta(self, snapshot: Ms) -> pl.DataFrame:
        return self._inner.meta(snapshot)

    def roles(self, snapshot: Ms) -> pl.DataFrame:
        return self._inner.roles(snapshot)

    # Cortados.

    def coverage(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"cobertura de {address}", end)
        return self._inner.coverage(address, start, end)

    def fills(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"fills de {address}", end)
        return self._inner.fills(address, start, end)

    def funding(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"funding de {coin}", end)
        return self._inner.funding(coin, start, end)

    def proxy(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"proxy de {coin}", end)
        return self._inner.proxy(coin, start, end)

    def bbo(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"bbo de {coin}", end)
        return self._inner.bbo(coin, start, end)

    def book(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"livro de {coin}", end)
        return self._inner.book(coin, start, end)

    def gaps(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self._guard(f"lacunas de {coin}", end)
        return self._inner.gaps(coin, start, end)

    def content_hash(self, table: str, keys: Sequence[str], start: Ms, end: Ms) -> str:
        if table not in UNCUT_TABLES:
            self._guard(f"hash de {table}", end)
        return self._inner.content_hash(table, keys, start, end)
