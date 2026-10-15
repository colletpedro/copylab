"""Auxiliares dos testes de seleção: um `Repository` em memória e construtores de fills.

Nada aqui é dado real. O repositório falso implementa o protocolo de `copylab.ports` com
tabelas montadas à mão; `BoundedRepository` o envolve nos testes, como a CLI faz com o de
verdade.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

from copylab.params import Params, load_params
from copylab.storage.tables import COVERAGE, FILLS, PROXY, PROXY_DAYS, SCHEMAS
from copylab.timeutil import Ms
from copylab.windows import Window

REPO_ROOT = Path(__file__).resolve().parents[2]


def real_params() -> Params:
    """Os parâmetros pré-registrados do repositório (os limiares reais de F1 a F10)."""
    return load_params(REPO_ROOT / "preregistro" / "parametros.toml")


def fill_row(
    t: int,
    coin: str,
    side: str,
    sz: float,
    px: float,
    start: float,
    *,
    pnl: float = 0.0,
    crossed: bool | None = True,
    kind: str | None = None,
    liquidated_user: str | None = None,
) -> dict[str, Any]:
    """Um fill. ``seq`` é atribuído por :func:`fills_table`, na ordem em que os fills são dados."""
    return {
        "time_ms": t,
        "coin": coin,
        "kind": kind or ("hip3" if ":" in coin else "perp"),
        "px": px,
        "sz": sz,
        "side": side,
        "start_position": start,
        "dir": None,
        "crossed": crossed,
        "closed_pnl": pnl,
        "fee": 0.0,
        "tid": 1,
        "oid": 1,
        "twap_id": None,
        "liquidated_user": liquidated_user,
    }


def fills_table(*rows: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame([{"seq": i, **row} for i, row in enumerate(rows)], schema=SCHEMAS[FILLS])


def proxy_days_table(found: Mapping[int, bool]) -> pl.DataFrame:
    """``proxy_days`` a partir de pares ``(dia, existe)``."""
    return pl.DataFrame(
        [{"day": d, "found": f} for d, f in found.items()], schema=SCHEMAS[PROXY_DAYS]
    )


def proxy_table(rows: Sequence[tuple[int, float]]) -> pl.DataFrame:
    """Proxy a partir de pares ``(segundo, último preço)``; mínimo e máximo valem o último."""
    return pl.DataFrame(
        [{"second": s, "low": last, "high": last, "last": last, "n_trades": 1} for s, last in rows],
        schema=SCHEMAS[PROXY],
    )


def coverage_table(window: Window, status: str) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "start_ms": window.start,
                "end_ms": window.end,
                "ingested_at_ms": 0,
                "n_fills": 0,
                "status": status,
                "content_hash": "",
            }
        ],
        schema=SCHEMAS[COVERAGE],
    )


class FakeRepository:
    """Implementa `copylab.ports.Repository` com dicionários. Tudo que o teste não preencheu
    volta vazio, e o que a seleção não deve ler levanta."""

    def __init__(
        self,
        *,
        fills: Mapping[str, pl.DataFrame] | None = None,
        coverage: Mapping[str, pl.DataFrame] | None = None,
        proxy: Mapping[str, pl.DataFrame] | None = None,
        proxy_days: Mapping[str, pl.DataFrame] | None = None,
        roles: Mapping[Ms, pl.DataFrame] | None = None,
    ) -> None:
        self.fills_by_address = dict(fills or {})
        self.coverage_by_address = dict(coverage or {})
        self.proxy_by_coin = dict(proxy or {})
        self.proxy_days_by_coin = dict(proxy_days or {})
        self.roles_by_snapshot = dict(roles or {})
        self.reads: list[tuple[str, str, int, int]] = []

    def leaderboard(self, snapshot: Ms) -> pl.DataFrame:
        raise NotImplementedError

    def meta(self, snapshot: Ms) -> pl.DataFrame:
        raise NotImplementedError

    def roles(self, snapshot: Ms) -> pl.DataFrame:
        return self.roles_by_snapshot[snapshot]

    def coverage(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        self.reads.append(("coverage", address, start, end))
        frame = self.coverage_by_address.get(address, pl.DataFrame(schema=SCHEMAS[COVERAGE]))
        return frame.filter((pl.col("start_ms") < end) & (pl.col("end_ms") > start))

    def fills(self, address: str, start: Ms, end: Ms) -> pl.DataFrame:
        self.reads.append(("fills", address, start, end))
        frame = self.fills_by_address.get(address, pl.DataFrame(schema=SCHEMAS[FILLS]))
        return frame.filter(pl.col("time_ms").is_between(start, end, closed="left")).sort(
            "time_ms", "seq"
        )

    def funding(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        raise NotImplementedError

    def proxy(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self.reads.append(("proxy", coin, start, end))
        frame = self.proxy_by_coin.get(coin, pl.DataFrame(schema=SCHEMAS[PROXY]))
        return frame.filter((pl.col("second") * 1_000).is_between(start, end, closed="left"))

    def proxy_days(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        self.reads.append(("proxy_days", coin, start, end))
        frame = self.proxy_days_by_coin.get(coin, pl.DataFrame(schema=SCHEMAS[PROXY_DAYS]))
        return frame.filter((pl.col("day") * 86_400_000).is_between(start, end, closed="left"))

    def bbo(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        raise NotImplementedError

    def book(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        raise NotImplementedError

    def gaps(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame:
        raise NotImplementedError

    def content_hash(self, table: str, keys: Sequence[str], start: Ms, end: Ms) -> str:
        raise NotImplementedError
