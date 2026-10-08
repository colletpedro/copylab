"""Leitura das tabelas por janela: a implementação de :class:`copylab.ports.Repository`.

Janelas semiabertas, ``[start, end)`` em ``Ms``, como em todo o sistema. Cada tabela é
lida pelo instante que a define (design §3.2):

- ``fills`` e ``divergences`` por ``time_ms``; ``coverage`` pelas janelas que se
  sobrepõem ao intervalo; ``funding`` por ``hour_ms``; ``proxy`` pelo início do segundo.
- **Tabelas do coletor** (``bbo``, ``book``, ``trades``) pelo instante da corretora,
  ``time_ms``. Elas são particionadas pelo dia UTC de *recebimento*, e o relógio da
  máquina do coletor pode estar adiantado ou atrasado: uma linha da corretora das 23:59:59
  pode ter chegado, pelo relógio local, no dia seguinte. Por isso toda leitura abre também
  a partição do dia anterior ao primeiro e a do dia seguinte ao último, e filtra por
  ``time_ms``. O relógio local nunca decide a que instante um dado pertence (design 1.2
  §3.2). As linhas saem em ordem de ``time_ms``, estável na ordem de recebimento.
- ``gaps``, que tem uma partição por ativo, pelas lacunas que se sobrepõem ao intervalo,
  no relógio da corretora.
- Snapshots (``leaderboard``, ``meta``, ``roles``) pelo instante da coleta, exato.

Ler um intervalo sem nenhuma partição gravada devolve a tabela vazia, com as colunas
dela. Quem precisa de dado e não o encontra decide se isso é falha (RF-CLI-01 CA-01.2).
"""

from collections.abc import Sequence
from typing import Final

import polars as pl

from copylab.exceptions import DataError
from copylab.storage.files import ParquetStore, Partition
from copylab.storage.hashing import content_hash
from copylab.storage.tables import (
    BBO,
    BOOK,
    COVERAGE,
    DIVERGENCES,
    FILLS,
    FUNDING,
    GAPS,
    LEADERBOARD,
    META,
    PROXY,
    RAW_LEADERBOARD,
    ROLES,
    SCHEMAS,
    TRADES,
)
from copylab.timeutil import MS_PER_SECOND, Ms, iso, utc_day

__all__ = ["ParquetRepository"]

#: Tabelas de snapshot: uma partição por instante de coleta.
_SNAPSHOT_TABLES: Final = (RAW_LEADERBOARD, LEADERBOARD, META, ROLES)
#: Nome da coluna que recebe cada parte da partição no hash de conteúdo.
_PARTITION_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    FILLS: ("address",),
    COVERAGE: ("address",),
    DIVERGENCES: ("address",),
    FUNDING: ("coin",),
    PROXY: ("coin", "day"),
    BBO: ("coin", "day"),
    BOOK: ("coin", "day"),
    TRADES: ("coin", "day"),
    GAPS: ("coin",),
}
#: Instante de cada linha, nas tabelas que não são snapshot.
_INSTANT: Final[dict[str, pl.Expr]] = {
    FILLS: pl.col("time_ms"),
    COVERAGE: pl.col("start_ms"),
    DIVERGENCES: pl.col("time_ms"),
    FUNDING: pl.col("hour_ms"),
    PROXY: pl.col("second") * MS_PER_SECOND,
    BBO: pl.col("time_ms"),
    BOOK: pl.col("time_ms"),
    TRADES: pl.col("time_ms"),
    GAPS: pl.col("start_ms"),
}


def _empty(table: str) -> pl.DataFrame:
    return pl.DataFrame(schema=SCHEMAS[table])


class ParquetRepository:
    """Lê as tabelas de um :class:`ParquetStore`. Não grava nada."""

    def __init__(self, store: ParquetStore) -> None:
        self._store = store

    # ─── Snapshots ───────────────────────────────────────────────────────────

    def snapshots(self, table: str) -> list[Ms]:
        """Instantes dos snapshots gravados da tabela, em ordem crescente."""
        if table not in _SNAPSHOT_TABLES:
            raise DataError(f"{table!r} não é tabela de snapshot.")
        return sorted(Ms(int(part[0])) for part in self._store.partitions(table))

    def _snapshot(self, table: str, snapshot: Ms) -> pl.DataFrame:
        partition = (str(snapshot),)
        if not self._store.exists(table, partition):
            raise DataError(
                f"Não há snapshot de {table!r} em {iso(snapshot)} ({snapshot}). "
                f"Gravados: {[int(s) for s in self.snapshots(table)]}."
            )
        return self._store.read(table, partition)

    def raw_leaderboard(self, snapshot: Ms) -> pl.DataFrame:
        """Corpo bruto do leaderboard. Fora do protocolo de leitura de propósito: a seleção
        não o recebe (RF-SEL-01 CA-01.3)."""
        return self._snapshot(RAW_LEADERBOARD, snapshot)

    def leaderboard(self, snapshot: Ms) -> pl.DataFrame:
        return self._snapshot(LEADERBOARD, snapshot)

    def meta(self, snapshot: Ms) -> pl.DataFrame:
        return self._snapshot(META, snapshot)

    def roles(self, snapshot: Ms) -> pl.DataFrame:
        return self._snapshot(ROLES, snapshot)

    # ─── Por endereço ────────────────────────────────────────────────────────

    def _partition(self, table: str, partition: Partition) -> pl.DataFrame:
        if not self._store.exists(table, partition):
            return _empty(table)
        return self._store.read(table, partition)

    def coverage(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        """Janelas ingeridas do endereço que se sobrepõem a ``[start, end)``."""
        frame = self._partition(COVERAGE, (address,))
        return frame.filter((pl.col("start_ms") < end) & (pl.col("end_ms") > start)).sort(
            "start_ms", maintain_order=True
        )

    def fills(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        """Fills do endereço em ``[start, end)``, na ordem de ``time_ms`` e ``seq``."""
        frame = self._partition(FILLS, (address,))
        return frame.filter(pl.col("time_ms").is_between(start, end, closed="left")).sort(
            "time_ms", "seq"
        )

    def divergences(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        """Divergências de reingestão em fills com instante em ``[start, end)``."""
        frame = self._partition(DIVERGENCES, (address,))
        return frame.filter(pl.col("time_ms").is_between(start, end, closed="left"))

    # ─── Por ativo ───────────────────────────────────────────────────────────

    def funding(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        frame = self._partition(FUNDING, (coin,))
        return frame.filter(pl.col("hour_ms").is_between(start, end, closed="left")).sort("hour_ms")

    def _days(self, table: str, coin: str, first: int, last: int) -> pl.DataFrame:
        frames = [
            self._store.read(table, (coin, str(day)))
            for day in range(first, last + 1)
            if self._store.exists(table, (coin, str(day)))
        ]
        return pl.concat(frames) if frames else _empty(table)

    def proxy(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        """Série por segundo; um segundo entra se o seu início está em ``[start, end)``."""
        if end <= start:
            return _empty(PROXY)
        frame = self._days(PROXY, coin, utc_day(start), utc_day(Ms(end - 1)))
        instant = _INSTANT[PROXY]
        return frame.filter(instant.is_between(start, end, closed="left")).sort("second")

    def _exchange_time(self, table: str, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        if end <= start:
            return _empty(table)
        # Partições pelo dia de recebimento: um dia a mais de cada lado (design 1.2 §3.2).
        frame = self._days(table, coin, utc_day(start) - 1, utc_day(Ms(end - 1)) + 1)
        return frame.filter(pl.col("time_ms").is_between(start, end, closed="left")).sort(
            "time_ms", maintain_order=True
        )

    def bbo(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._exchange_time(BBO, coin, start, end)

    def book(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        return self._exchange_time(BOOK, coin, start, end)

    def trades(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        """Negócios gravados pelo coletor. Fora do protocolo de leitura: nenhum pacote de
        lógica os lê ainda."""
        return self._exchange_time(TRADES, coin, start, end)

    def gaps(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        """Lacunas do ativo que se sobrepõem a ``[start, end)``, no relógio da corretora."""
        frame = self._partition(GAPS, (coin,))
        return frame.filter((pl.col("start_ms") < end) & (pl.col("end_ms") > start)).sort(
            "start_ms", "end_ms"
        )

    # ─── Hash ────────────────────────────────────────────────────────────────

    def content_hash(self, table: str, keys: Sequence[str], start: Ms, end: Ms) -> str:
        """Hash de conteúdo (``storage.hashing``) das linhas da tabela com instante em
        ``[start, end)``, em todas as partições.

        As partes da partição entram como colunas (``address``, ``coin``, ``day``) e na
        frente das chaves: linhas iguais de dois endereços não se confundem. Nas tabelas
        de snapshot, o instante é o do snapshot, numa coluna ``snapshot_ms``.
        """
        if table in _SNAPSHOT_TABLES:
            frames = [
                self._store.read(table, (str(s),)).with_columns(snapshot_ms=pl.lit(int(s)))
                for s in self.snapshots(table)
                if start <= s < end
            ]
            prefix: tuple[str, ...] = ("snapshot_ms",)
            schema = {**SCHEMAS[table], "snapshot_ms": pl.Int64}
        elif table in _PARTITION_COLUMNS:
            prefix = _PARTITION_COLUMNS[table]
            frames = [
                self._store.read(table, partition)
                .filter(_INSTANT[table].is_between(start, end, closed="left"))
                .with_columns(
                    pl.lit(value).alias(name) for name, value in zip(prefix, partition, strict=True)
                )
                for partition in self._store.partitions(table)
            ]
            schema = {**SCHEMAS[table], **dict.fromkeys(prefix, pl.String)}
        else:
            raise DataError(f"Tabela desconhecida para hash: {table!r}.")
        frame = pl.concat(frames) if frames else pl.DataFrame(schema=schema)
        return content_hash(frame, [*prefix, *keys])
