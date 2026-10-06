"""Funções puras de medição da verificação de dados (§4.1). Sem rede e sem disco.

Ficam separadas dos scripts para serem testadas com séries construídas à mão
(`tests/unit/test_verify_helpers.py`).

**Regra 2 do prompt 02: nada de desempenho.** A única conta de PnL permitida é a de
RF-VER-01 CA-01.4, em `concordance`, e dela só saem contagens de episódios (nunca um
valor de PnL, de retorno ou de ranking). Esta é a única função que soma `closedPnl`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

#: Campos que a spec usa (RF-VER-01 CA-01.1).
SPEC_FIELDS = (
    "time",
    "coin",
    "px",
    "sz",
    "side",
    "startPosition",
    "dir",
    "crossed",
    "closedPnl",
    "fee",
    "tid",
    "oid",
)

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ─── Números ─────────────────────────────────────────────────────────────────


def parse_float(value: Any) -> float | None:
    """Número finito vindo de string ou número. `None` se não interpretável (bool incluso)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil `q` (0 a 100) com interpolação linear, como o default do numpy."""
    if not values:
        raise ValueError("percentil de série vazia")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    low = math.floor(pos)
    high = math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


# ─── RF-VER-01 CA-01.1: campos presentes e interpretáveis ────────────────────


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive(value: Any) -> bool:
    number = parse_float(value)
    return number is not None and number > 0


def _finite(value: Any) -> bool:
    return parse_float(value) is not None


#: Teste de "interpretável" por campo.
FIELD_CHECKS: dict[str, Callable[[Any], bool]] = {
    "time": lambda v: _is_positive_int(v) and 1e12 < v < 2e12,
    "coin": lambda v: isinstance(v, str) and bool(v),
    "px": _positive,
    "sz": _positive,
    "side": lambda v: v in ("A", "B"),
    "startPosition": _finite,
    "dir": lambda v: isinstance(v, str) and bool(v),
    "crossed": lambda v: isinstance(v, bool),
    "closedPnl": _finite,
    "fee": _finite,
    "tid": _is_positive_int,
    "oid": _is_positive_int,
}


def field_coverage(fills: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Por campo: quantos fills o trazem (não nulo) e quantos o trazem interpretável."""
    present: Counter[str] = Counter()
    ok: Counter[str] = Counter()
    total = 0
    for fill in fills:
        total += 1
        for name in SPEC_FIELDS:
            value = fill.get(name)
            if value is not None:
                present[name] += 1
                if FIELD_CHECKS[name](value):
                    ok[name] += 1
    return {
        "total": total,
        "fields": {name: {"present": present[name], "ok": ok[name]} for name in SPEC_FIELDS},
    }


def unexpected_fields(fills: Iterable[dict[str, Any]]) -> Counter[str]:
    """Campos dos fills que não estão em `SPEC_FIELDS` (para a seção de contradições)."""
    extra: Counter[str] = Counter()
    for fill in fills:
        extra.update(k for k in fill if k not in SPEC_FIELDS)
    return extra


# ─── Classificação de ativos ─────────────────────────────────────────────────


def classify_coin(coin: str, perp_names: frozenset[str]) -> str:
    """`perp` (primeiro dex), `perp_fora_do_meta`, `hip3`, `spot` ou `outcome`.

    HIP-3 vem como `dex:ATIVO`; spot como `@N` ou `BASE/QUOTE`; tokens de resultado
    (`dir` como `Buy`, `Merge Outcome`, `Settlement`) como `#N`. Perpétuo que não está
    mais no `meta` (delistado e removido) é `perp_fora_do_meta`.
    """
    if coin.startswith("#"):
        return "outcome"
    if ":" in coin:
        return "hip3"
    if coin.startswith("@") or "/" in coin:
        return "spot"
    return "perp" if coin in perp_names else "perp_fora_do_meta"


def is_perp(kind: str) -> bool:
    return kind in ("perp", "perp_fora_do_meta")


# ─── RF-ING-03 CA-03.1: continuidade de posição ──────────────────────────────


def signed_size(fill: dict[str, Any]) -> float:
    size = float(fill["sz"])
    return size if fill["side"] == "B" else -size


def continuity_pairs(fills: Sequence[dict[str, Any]], lot: float) -> dict[str, int]:
    """Confere pares consecutivos de um mesmo ativo.

    `startPosition` do segundo deve ser `startPosition` do primeiro mais o `sz` com o
    sinal do lado, dentro de um lote. Devolve pares conferidos, quebras, e quantas
    quebras ocorrem entre fills do mesmo milissegundo (onde a ordem é ambígua).
    """
    pairs = breaks = breaks_same_ms = 0
    for prev, nxt in pairwise(fills):
        pairs += 1
        expected = float(prev["startPosition"]) + signed_size(prev)
        if abs(float(nxt["startPosition"]) - expected) > lot * (1 + 1e-9):
            breaks += 1
            if prev["time"] == nxt["time"]:
                breaks_same_ms += 1
    return {"pairs": pairs, "breaks": breaks, "breaks_same_ms": breaks_same_ms}


# ─── RF-ING-04 / RF-VER-01 CA-01.4: episódios e concordância de closedPnl ────


@dataclass
class Episode:
    fills: list[dict[str, Any]] = field(default_factory=list)
    ended: str = "open"  # flat | inversion | open
    clean: bool = True  # continuidade intacta dentro do episódio


def build_episodes(fills: Sequence[dict[str, Any]], lot: float) -> list[Episode]:
    """Episódios de um ativo: da posição zero de volta a zero (RF-ING-04 CA-04.1).

    Só episódios que *começam* em zero dentro da janela existem (D8): um fill que
    começa com posição aberta, sem episódio corrente, é posição anterior e é ignorado
    até a posição voltar a zero. Inversão de sinal encerra o episódio; a perna nova
    não é reconstruída aqui (não há preço de entrada conhecido para testá-la).
    """
    episodes: list[Episode] = []
    current: Episode | None = None
    position = 0.0
    for fill in fills:
        start = float(fill["startPosition"])
        end = start + signed_size(fill)
        if current is None:
            if abs(start) > lot / 2:
                continue
            current = Episode()
        elif abs(start - position) > lot * (1 + 1e-9):
            current.clean = False
        current.fills.append(fill)
        position = end
        if abs(end) <= lot / 2:
            current.ended = "flat"
            episodes.append(current)
            current = None
        elif start * end < 0:
            current.ended = "inversion"
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)
    return episodes


def reconstruct_gross(fills: Sequence[dict[str, Any]]) -> float:
    """PnL realizado reconstruído de preços e tamanhos, por custo médio, sem taxas.

    Usado só para conferir `closedPnl` (RF-VER-01 CA-01.4); o valor não sai da função
    que o consome. Pressupõe episódio que vai de zero a zero sem inversão.
    """
    position = 0.0
    average = 0.0
    realized = 0.0
    for fill in fills:
        price = float(fill["px"])
        size = float(fill["sz"])
        signed = signed_size(fill)
        if position == 0 or position * signed > 0:
            average = (abs(position) * average + size * price) / (abs(position) + size)
        else:
            closed = min(size, abs(position))
            realized += closed * (price - average) * (1 if position > 0 else -1)
        position += signed
        if abs(position) < 1e-12:
            position = 0.0
    return realized


def _close(a: float, b: float, rel: float, abs_tol: float) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


def concordance(
    episodes: Iterable[Episode], *, rel_tol: float = 1e-6, abs_tol: float = 1e-6
) -> dict[str, int]:
    """Quantos episódios fechados conciliam com `closedPnl` em cada hipótese.

    Hipóteses sobre a soma de `closedPnl` do episódio: `gross` (igual ao PnL
    reconstruído), `net_all` (reconstruído menos todas as taxas do episódio) e
    `net_close` (menos só as taxas dos fills que reduzem posição). Devolve **somente
    contagens**: nenhum valor de PnL sai daqui (regra 2 do prompt 02).

    `fee_matters` conta os episódios em que a taxa total passa de `abs_tol`; só neles
    `gross` e `net_all` são distinguíveis.
    """
    out: Counter[str] = Counter()
    for episode in episodes:
        out["episodes"] += 1
        if episode.ended == "inversion":
            out["excluded_inversion"] += 1
            continue
        if episode.ended == "open":
            out["excluded_open_at_end"] += 1
            continue
        if not episode.clean:
            out["excluded_broken"] += 1
            continue
        reconstructed = reconstruct_gross(episode.fills)
        reported = sum(float(f["closedPnl"]) for f in episode.fills)
        fees_all = sum(float(f["fee"]) for f in episode.fills)
        fees_close = sum(
            float(f["fee"]) for f in episode.fills if float(f["startPosition"]) * signed_size(f) < 0
        )
        out["tested"] += 1
        fee_matters = fees_all > abs_tol
        out["fee_matters"] += fee_matters
        hypotheses = {
            "gross": _close(reported, reconstructed, rel_tol, abs_tol),
            "net_all": _close(reported, reconstructed - fees_all, rel_tol, abs_tol),
            "net_close": _close(reported, reconstructed - fees_close, rel_tol, abs_tol),
        }
        for name, holds in hypotheses.items():
            out[name] += holds
            if fee_matters:
                out[f"{name}_when_fee_matters"] += holds
    return dict(out)


def fill_level_concordance(
    episodes: Iterable[Episode], *, tolerances: Sequence[float] = (1e-6, 1e-3)
) -> dict[str, int]:
    """Conferência de `closedPnl` fill a fill, para diagnosticar a de episódio.

    Em episódios fechados e íntegros, cada fill que *abre ou aumenta* posição deve ter
    `closedPnl` zero (hipótese bruta) ou menos a própria taxa (hipótese líquida); cada fill
    que *reduz* deve ter `closedPnl` igual a `fechado x (px - entrada) x sinal`, ou isso
    menos a própria taxa. Devolve **somente contagens** (regra 2 do prompt 02).
    """
    out: Counter[str] = Counter()
    for episode in episodes:
        if episode.ended != "flat" or not episode.clean:
            continue
        position = 0.0
        average = 0.0
        for fill in episode.fills:
            price = float(fill["px"])
            size = float(fill["sz"])
            signed = signed_size(fill)
            reported = float(fill["closedPnl"])
            fee = float(fill["fee"])
            if position == 0 or position * signed > 0:
                average = (abs(position) * average + size * price) / (abs(position) + size)
                out["open_fills"] += 1
                for tol in tolerances:
                    out[f"open_zero@{tol:g}"] += _close(reported, 0.0, tol, tol)
                    out[f"open_minus_fee@{tol:g}"] += _close(reported, -fee, tol, tol)
            else:
                closed = min(size, abs(position))
                realized = closed * (price - average) * (1 if position > 0 else -1)
                out["close_fills"] += 1
                for tol in tolerances:
                    out[f"close_gross@{tol:g}"] += _close(reported, realized, tol, tol)
                    out[f"close_minus_fee@{tol:g}"] += _close(reported, realized - fee, tol, tol)
            position += signed
            if abs(position) < 1e-12:
                position = 0.0
    return dict(out)


def concordance_by_size(
    episodes: Iterable[Episode], *, tolerances: Sequence[float] = (1e-6, 1e-3)
) -> dict[str, int]:
    """Episódios fechados e íntegros que conciliam (hipótese bruta), por nº de fills.

    Faixas: `2` (abre e fecha), `3-4` e `5+`. Só contagens (regra 2 do prompt 02).
    """
    out: Counter[str] = Counter()
    for episode in episodes:
        if episode.ended != "flat" or not episode.clean:
            continue
        n = len(episode.fills)
        band = "2" if n == 2 else ("3-4" if n <= 4 else "5+")
        out[f"{band}|tested"] += 1
        for tol in tolerances:
            out[f"{band}|gross@{tol:g}"] += concordance([episode], rel_tol=tol, abs_tol=tol).get(
                "gross", 0
            )
    return dict(out)


def continuity_breaks(fills: Sequence[dict[str, Any]], lot: float) -> dict[str, Any]:
    """Diagnóstico das quebras de continuidade de um ativo (contagens e intervalos).

    Para cada par quebrado: o `dir` do fill anterior, se o salto é de ao menos o tamanho
    do fill anterior (um fill inteiro faltando, ou mudança de posição sem fill), se um dos
    dois traz o campo `liquidation`, e o intervalo de tempo entre os dois fills.
    """
    prev_dir: Counter[str] = Counter()
    jump: Counter[str] = Counter()
    liquidation = 0
    gaps: list[float] = []
    for prev, nxt in pairwise(fills):
        expected = float(prev["startPosition"]) + signed_size(prev)
        diff = abs(float(nxt["startPosition"]) - expected)
        if diff <= lot * (1 + 1e-9):
            continue
        prev_dir[str(prev.get("dir"))] += 1
        jump[
            "salto >= tamanho do fill anterior" if diff >= float(prev["sz"]) else "salto menor"
        ] += 1
        liquidation += ("liquidation" in prev) or ("liquidation" in nxt)
        gaps.append((int(nxt["time"]) - int(prev["time"])) / 1000)
    return {
        "prev_dir": dict(prev_dir),
        "jump": dict(jump),
        "with_liquidation_field": liquidation,
        "gaps_s": gaps,
    }


# ─── RF-VER-02: notional por ativo e regra D7 ────────────────────────────────


def notional_by_coin(fills: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Soma de `px * sz` por ativo. É volume negociado, não desempenho."""
    totals: dict[str, float] = {}
    for fill in fills:
        value = float(fill["px"]) * float(fill["sz"])
        totals[fill["coin"]] = totals.get(fill["coin"], 0.0) + value
    return totals


def d7_additions(
    ranked: Sequence[tuple[str, float]],
    universe: Sequence[str],
    has_equivalent: dict[str, bool],
    *,
    target: float = 0.5,
    max_assets: int = 8,
) -> list[dict[str, Any]]:
    """Regra D7: ativos a acrescentar, em ordem decrescente de notional.

    `ranked` traz `(ativo, fração do notional)` já em ordem decrescente. Parte da fração
    acumulada do universo, acrescenta só ativos com perpétuo equivalente na Binance, e
    para ao atingir `target` ou `max_assets` ativos. Não acrescenta nada: só lista.
    """
    cumulative = sum(share for coin, share in ranked if coin in universe)
    count = len(universe)
    chosen: list[dict[str, Any]] = []
    for coin, share in ranked:
        if cumulative >= target or count >= max_assets:
            break
        if coin in universe:
            continue
        if not has_equivalent.get(coin, False):
            continue
        cumulative += share
        count += 1
        chosen.append({"coin": coin, "share": share, "cumulative_after": cumulative})
    return chosen
