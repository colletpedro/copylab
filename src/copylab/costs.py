"""Arquivo de custos: o meio-spread mediano por ativo (RF-COL-05 CA-05.2, design 1.7 §3.9).

``preregistro/custos.json`` guarda, por ativo, o valor medido, os dias usados e o hash dos
dados. Cada ativo é medido uma vez: o arquivo só ganha ativos, nunca muda um valor gravado
(:func:`add_new` recusa). Quem lê e grava o arquivo é a CLI; aqui há o modelo, o texto e a
conta.

**A conta.** Cada observação de melhor compra e venda tem meio-spread
``(venda - compra) / (venda + compra) * 10^4`` bps, que é ``(venda - compra) / (2 * ponto
médio)``. O peso é o tempo até a observação seguinte do mesmo dia (a última vai até o fim do
dia), menos a parte desse intervalo que cai em lacuna. O valor é a mediana ponderada inferior
(``copylab.stats``), sem interpolação.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from copylab.exceptions import ConfigError, DataError
from copylab.stats import weighted_percentile
from copylab.timeutil import MS_PER_DAY, Ms, day_start, iso, parse_utc_date, utc_day

__all__ = [
    "DEFAULT_COSTS_PATH",
    "CostEntry",
    "HalfSpread",
    "add_new",
    "dump_costs",
    "half_spread_bps",
    "parse_costs",
]

#: Caminho do arquivo, relativo à raiz do repositório.
DEFAULT_COSTS_PATH: Final = Path("preregistro/custos.json")

_BPS: Final = 10_000.0
_MEDIAN_PCT: Final = 50
_HASH: Final = re.compile(r"[0-9a-f]{64}")
_KEYS: Final = frozenset({"half_spread_bps", "days", "data_hash", "skipped_observations"})


@dataclass(frozen=True, slots=True)
class CostEntry:
    """O custo medido de um ativo."""

    half_spread_bps: float
    days: tuple[int, ...]  # dias UTC usados, em ordem (``utc_day``)
    data_hash: str  # sha256 hexadecimal dos dados lidos
    skipped_observations: int = 0  # cotações inválidas, puladas (design 1.8)


# ─── Arquivo ─────────────────────────────────────────────────────────────────


def _entry(coin: str, raw: object) -> CostEntry:
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise ConfigError(f"Custo de {coin}: esperava um objeto com as chaves {sorted(_KEYS)}.")
    value, days, data_hash = raw["half_spread_bps"], raw["days"], raw["data_hash"]
    skipped = raw["skipped_observations"]
    if isinstance(skipped, bool) or not isinstance(skipped, int) or skipped < 0:
        raise ConfigError(
            f"Custo de {coin}: skipped_observations {skipped!r} não é um inteiro não negativo."
        )
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= value < 1e9:
        raise ConfigError(
            f"Custo de {coin}: half_spread_bps {value!r} não é um número não negativo."
        )
    if not isinstance(days, list) or not days or not all(isinstance(d, str) for d in days):
        raise ConfigError(f"Custo de {coin}: days precisa ser uma lista não vazia de datas.")
    parsed = tuple(utc_day(parse_utc_date(d)) for d in days)
    if list(parsed) != sorted(set(parsed)):
        raise ConfigError(f"Custo de {coin}: days fora de ordem ou com dia repetido: {days}.")
    if not isinstance(data_hash, str) or _HASH.fullmatch(data_hash) is None:
        raise ConfigError(f"Custo de {coin}: data_hash {data_hash!r} não é um sha256.")
    return CostEntry(float(value), parsed, data_hash, skipped)


def parse_costs(text: str) -> dict[str, CostEntry]:
    """Lê o texto do arquivo de custos.

    Raises:
        ConfigError: JSON inválido, ativo repetido, ou entrada malformada.
    """

    def no_repeats(pairs: list[tuple[str, object]]) -> dict[str, object]:
        keys = [k for k, _ in pairs]
        repeated = sorted({k for k in keys if keys.count(k) > 1})
        if repeated:
            raise ConfigError(f"Arquivo de custos com chave repetida: {repeated}.")
        return dict(pairs)

    try:
        raw = json.loads(text, object_pairs_hook=no_repeats)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Arquivo de custos não é JSON válido: {exc}.") from exc
    if not isinstance(raw, dict):
        raise ConfigError("Arquivo de custos precisa ser um objeto ativo -> custo.")
    return {coin: _entry(coin, entry) for coin, entry in raw.items()}


def dump_costs(costs: Mapping[str, CostEntry]) -> str:
    """O texto do arquivo: chaves em ordem, dias como datas, e uma quebra de linha no fim."""
    raw = {
        coin: {
            "half_spread_bps": entry.half_spread_bps,
            "days": [iso(day_start(d))[:10] for d in entry.days],
            "data_hash": entry.data_hash,
            "skipped_observations": entry.skipped_observations,
        }
        for coin, entry in costs.items()
    }
    return json.dumps(raw, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def add_new(
    existing: Mapping[str, CostEntry], measured: Mapping[str, CostEntry]
) -> dict[str, CostEntry]:
    """O arquivo com os ativos medidos acrescentados. Um valor gravado nunca muda.

    Raises:
        ConfigError: ``measured`` traz um ativo que já está em ``existing``, igual ou não.
    """
    clash = sorted(set(existing) & set(measured))
    if clash:
        raise ConfigError(
            f"Os custos de {clash} já estão gravados e não mudam (RF-COL-05 CA-05.2)."
        )
    return {**existing, **measured}


# ─── Meio-spread ponderado pelo tempo ────────────────────────────────────────


def _merged(gaps: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Lacunas em ordem, com as que se tocam ou se sobrepõem unidas."""
    out: list[list[int]] = []
    for start, end in sorted(gaps):
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def _gap_measure(instants: pl.Series, gaps: Sequence[tuple[int, int]]) -> pl.Series:
    """Tempo total de lacuna até cada instante: ``G(x)``, a medida das lacunas até ``x``.

    ``gaps`` já unidas e em ordem. Para ``x``, vale o tempo das lacunas anteriores à última
    que começa até ``x``, mais o pedaço dessa que já passou.
    """
    if not gaps:
        return pl.Series(values=[0] * len(instants), dtype=pl.Int64)
    before = 0
    rows = []
    for start, end in gaps:
        rows.append((start, end - start, before))
        before += end - start
    table = pl.DataFrame(
        rows, schema={"gap_start": pl.Int64, "gap_len": pl.Int64, "before": pl.Int64}, orient="row"
    )
    frame = pl.DataFrame({"x": instants}).with_row_index("i").sort("x")
    joined = frame.join_asof(table, left_on="x", right_on="gap_start", strategy="backward")
    inside = pl.min_horizontal(
        pl.max_horizontal(pl.col("x") - pl.col("gap_start"), pl.lit(0)), pl.col("gap_len")
    )
    measure = joined.with_columns((pl.col("before") + inside).fill_null(0).alias("g")).sort("i")
    return measure.get_column("g")


def _invalid_quote() -> pl.Expr:
    """Cotação sem preço, com preço não positivo ou não finito, ou com compra acima da venda.
    Compra igual à venda é válida (meio-spread zero)."""
    bid, ask = pl.col("bid_px"), pl.col("ask_px")
    return (
        bid.is_null()
        | ask.is_null()
        | (bid <= 0)
        | (ask <= 0)
        | (bid > ask)
        | ~bid.is_finite()
        | ~ask.is_finite()
    ).fill_null(value=True)


@dataclass(frozen=True, slots=True)
class HalfSpread:
    """O meio-spread mediano e quantas cotações inválidas ficaram de fora."""

    value_bps: float
    skipped: int


def half_spread_bps(
    bbo: pl.DataFrame, gaps: Iterable[tuple[int, int]], days: Sequence[int]
) -> HalfSpread:
    """Mediana ponderada pelo tempo do meio-spread, em bps, nos dias UTC ``days``.

    ``bbo`` traz ``time_ms``, ``bid_px`` e ``ask_px`` (a tabela do coletor); ``gaps`` são as
    lacunas ``(início, fim)`` no relógio da corretora. Só as observações cujo ``time_ms`` cai
    nos dias dados entram. Cotação inválida é pulada e contada (design 1.8): o tempo dela não pesa
    e não passa para a vizinha.

    Raises:
        DataError: nenhuma observação válida, ou nenhum tempo observado fora de lacuna.
    """
    merged = _merged(gaps)
    values: list[pl.DataFrame] = []
    skipped = 0
    for day in days:
        start, end = day_start(day), Ms(day_start(day) + MS_PER_DAY)
        rows = (
            bbo.filter(pl.col("time_ms").is_between(start, end, closed="left"))
            .select("time_ms", "bid_px", "ask_px")
            .sort("time_ms", maintain_order=True)
        )
        if rows.height == 0:
            continue
        times = rows.get_column("time_ms")
        following = pl.concat([times.slice(1), pl.Series([end], dtype=pl.Int64)])
        elapsed = following - times
        in_gap = _gap_measure(following, merged) - _gap_measure(times, merged)
        weight = elapsed - in_gap
        half_spread = (
            (rows.get_column("ask_px") - rows.get_column("bid_px"))
            / (rows.get_column("ask_px") + rows.get_column("bid_px"))
            * _BPS
        )
        invalid = rows.select(_invalid_quote().alias("bad")).get_column("bad")
        skipped += int(invalid.sum())
        frame = pl.DataFrame({"value": half_spread, "weight": weight}).filter(~invalid)
        values.append(frame)
    if not values:
        raise DataError("Nenhuma observação de melhor compra e venda nos dias dados.")
    grouped = pl.concat(values).group_by("value").agg(pl.col("weight").sum())
    result = weighted_percentile(((float(v), int(w)) for v, w in grouped.iter_rows()), _MEDIAN_PCT)
    if result is None:
        raise DataError("Nenhum tempo observado fora de lacuna nos dias dados.")
    return HalfSpread(result, skipped)
