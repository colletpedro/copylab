"""Infraestrutura compartilhada pelos scripts de verificação de dados (§4.1).

Código exploratório, fora de `src/`: mede e reporta, não decide nada e não altera
spec. Tem type hints e passa no ruff, mas não entra no `mypy` nem na cobertura
(ver HANDOFF.md).

Regras que este módulo faz valer (prompt 02):

- **Somente leitura.** Só `POST /info` e o `GET` do leaderboard. Nenhuma chave, nenhuma
  assinatura, nenhum endpoint de ordem (RNF-09; o teste de arquitetura varre este
  diretório).
- **Orçamento de peso.** `RateBudget` mantém o peso gasto numa janela deslizante de 60 s
  abaixo de `BUDGET_WEIGHT_PER_MIN`, que fica propositalmente abaixo do teto de 1.200.
- **Janela de avaliação é só contada.** `fetch_wallet` guarda o conteúdo apenas dos
  fills com `WINDOW_START_MS <= time < CUTOFF_MS`. De antes da janela guarda a contagem
  e o instante do mais antigo; de depois, só a contagem.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import subprocess
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from copylab.exceptions import DataError
from copylab.logging import configure_logging, get_logger

#: Semente de toda amostragem (§7.2: coortes de controle usam a mesma). Registrada no relatório.
SEED = 20261005

REPO_ROOT = Path(__file__).resolve().parents[2]


def utc_ms(year: int, month: int, day: int) -> int:
    """Meia-noite UTC do dia, em milissegundos."""
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


#: Janela de seleção da Rota A (§7.2): [2026-07-01, 2026-09-01) UTC. O corte T é o fim.
WINDOW_START_MS = utc_ms(2026, 7, 1)
CUTOFF_MS = utc_ms(2026, 9, 1)

#: Universo proposto (§7.2) e o símbolo equivalente na Binance (perpétuo USD-M).
UNIVERSE = ("BTC", "ETH", "SOL")
BINANCE_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
WS_URL = "wss://api.hyperliquid.xyz/ws"
BINANCE_BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"

#: Teto documentado: 1.200 de peso por minuto por IP. Ficamos 200 abaixo (folga de ~17%).
API_WEIGHT_LIMIT_PER_MIN = 1200
BUDGET_WEIGHT_PER_MIN = 1000

PAGE_MAX = 2000  # fills por resposta de userFillsByTime (documentado)
RETENTION_CAP = 10_000  # só os 10.000 fills mais recentes por carteira (documentado)

#: Orçamento de disco da fase (RNF-10), em bytes.
DISK_BUDGET_BYTES = 30 * 1024**3

USER_AGENT = "copylab-verify/0.1 (read-only)"


# ─── Contexto de execução ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Ctx:
    """Tamanhos e destino de uma execução. `--smoke` reduz tudo e isola a saída."""

    smoke: bool
    root: Path
    n_v01: int
    n_v02: int
    ws_minutes: float
    n_days: int

    def path(self, *parts: str) -> Path:
        target = self.root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target


def make_ctx(smoke: bool) -> Ctx:
    base = REPO_ROOT / "data" / "verify"
    if smoke:
        return Ctx(True, base / "_smoke", n_v01=3, n_v02=3, ws_minutes=2.0, n_days=1)
    return Ctx(False, base, n_v01=20, n_v02=100, ws_minutes=60.0, n_days=5)


def sample_days(n_days: int) -> list[str]:
    """Dias (AAAA-MM-DD, UTC) sorteados da janela de seleção com a semente fixa.

    Compartilhado por RF-VER-02 (existência dos símbolos na Binance) e RF-VER-03 (o que
    se baixa), para os dois olharem os mesmos dias.
    """
    n_window = (CUTOFF_MS - WINDOW_START_MS) // 86_400_000
    picks = sorted(random.Random(SEED).sample(range(n_window), n_days))
    return [day_of(WINDOW_START_MS + i * 86_400_000) for i in picks]


# ─── Utilitários ─────────────────────────────────────────────────────────────


def setup_logging() -> Any:
    configure_logging("INFO", json_logs=False)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # uma linha por requisição é ruído
    return get_logger("verify")


def now_ms() -> int:
    return int(time.time() * 1000)


def write_json(path: Path, obj: Any) -> None:
    """Grava de forma atômica, para uma queda no meio não deixar arquivo pela metade."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_of(ms: int) -> str:
    """Dia UTC (AAAA-MM-DD) de um instante em milissegundos."""
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


def code_version() -> str:
    """Hash curto do commit, com `+dirty` se há alteração local em arquivo versionado."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconhecida"
    return f"{head}+dirty" if dirty else head


class Progress:
    """Progresso legível por humano e por máquina (`progress.json`), para a execução longa."""

    def __init__(self, ctx: Ctx, step: str, total: int) -> None:
        self._ctx = ctx
        self._log = get_logger("verify")
        self.step = step
        self.total = total
        self.done = 0
        self._t0 = time.monotonic()

    def tick(self, note: str = "", **extra: Any) -> None:
        self.done += 1
        elapsed = time.monotonic() - self._t0
        eta = elapsed / self.done * (self.total - self.done) if self.done else None
        payload = {
            "step": self.step,
            "done": self.done,
            "total": self.total,
            "elapsed_s": round(elapsed),
            "eta_s": None if eta is None else round(eta),
            "updated_at": iso(now_ms()),
            "note": note,
            **extra,
        }
        write_json(self._ctx.path("progress.json"), payload)
        self._log.info("progress", **payload)


# ─── Orçamento de peso ───────────────────────────────────────────────────────


class _Entry:
    __slots__ = ("t", "weight")

    def __init__(self, t: float, weight: float) -> None:
        self.t = t
        self.weight = weight


class RateBudget:
    """Janela deslizante de `window_s` segundos com teto de `limit` de peso.

    `acquire` reserva o peso *máximo* possível da requisição e bloqueia até caber;
    `settle` troca a reserva pelo peso real depois da resposta. Assim o gasto em
    qualquer janela de 60 s nunca passa de `limit`, mesmo com respostas de tamanho
    desconhecido até chegarem. `peak` guarda o maior gasto visto, para o relatório.
    """

    def __init__(
        self,
        limit: float = BUDGET_WEIGHT_PER_MIN,
        window_s: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self._entries: deque[_Entry] = deque()
        self.total_weight = 0.0
        self.peak = 0.0
        self.waited_s = 0.0

    def _used(self, now: float) -> float:
        while self._entries and self._entries[0].t <= now - self.window_s:
            self._entries.popleft()
        return sum(e.weight for e in self._entries)

    def acquire(self, weight: float) -> _Entry:
        if weight > self.limit:
            raise ValueError(f"peso {weight} maior que o orçamento {self.limit}")
        while True:
            now = self._clock()
            used = self._used(now)
            if used + weight <= self.limit:
                break
            wait = self._entries[0].t + self.window_s - now + 0.05
            self.waited_s += wait
            self._sleep(wait)
        entry = _Entry(now, weight)
        self._entries.append(entry)
        self.total_weight += weight
        self.peak = max(self.peak, used + weight)
        return entry

    def settle(self, entry: _Entry, actual_weight: float) -> None:
        self.total_weight += actual_weight - entry.weight
        entry.weight = actual_weight

    def penalize(self) -> None:
        """Depois de um 429, assume a janela cheia: nada sai até ela esvaziar."""
        self._entries.append(_Entry(self._clock(), self.limit))


# ─── Cliente da API de informação ────────────────────────────────────────────


def fills_weight(n_items: int) -> int:
    """20 de base mais 1 a cada 20 itens devolvidos (arredondando para cima)."""
    return 20 + math.ceil(n_items / 20)


class HlClient:
    """`POST /info`, somente leitura, com orçamento de peso e recuo exponencial.

    Em 429, em erro 5xx ou de transporte, espera e repete; esgotadas as tentativas,
    levanta `DataError`. Os contadores em `stats` vão para o relatório.
    """

    def __init__(
        self,
        budget: RateBudget,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 6,
    ) -> None:
        self.budget = budget
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(60.0, connect=15.0), headers={"User-Agent": USER_AGENT}
        )
        self._sleep = sleep
        self._max_retries = max_retries
        self.stats: Counter[str] = Counter()
        self._log = get_logger("verify.client")

    def info(self, body: dict[str, Any], *, reserve: int) -> tuple[Any, int]:
        """Devolve `(json, peso real)`. `reserve` é o peso máximo possível da chamada."""
        last_error = ""
        for attempt in range(self._max_retries + 1):
            entry = self.budget.acquire(reserve)
            backoff = min(60.0, 2.0 ** (attempt + 1))
            try:
                resp = self._http.post(INFO_URL, json=body)
            except httpx.TransportError as exc:
                self.budget.settle(entry, reserve)
                last_error = f"transporte: {type(exc).__name__}"
                self.stats["retries_transport"] += 1
                self._sleep(backoff)
                continue
            if resp.status_code == 429:
                self.stats["http_429"] += 1
                self.budget.penalize()
                self._log.warning("limite excedido (429); esperando", attempt=attempt)
                last_error = "429"
                self._sleep(backoff)
                continue
            if resp.status_code >= 500:
                self.budget.settle(entry, reserve)
                self.stats["retries_5xx"] += 1
                last_error = f"HTTP {resp.status_code}"
                self._sleep(backoff)
                continue
            if resp.status_code != 200:
                self.budget.settle(entry, reserve)
                raise DataError(f"HTTP {resp.status_code} em {body.get('type')}: {resp.text[:200]}")
            try:
                payload = resp.json()
            except ValueError as exc:
                self.budget.settle(entry, reserve)
                raise DataError(f"resposta não-JSON em {body.get('type')}") from exc
            is_fills = body.get("type") == "userFillsByTime"
            weight = fills_weight(len(payload)) if is_fills else reserve
            self.budget.settle(entry, weight)
            self.stats["requests"] += 1
            self.stats["weight"] += weight
            return payload, weight
        raise DataError(f"tentativas esgotadas em {body.get('type')}: {last_error}")

    def user_role(self, address: str) -> Any:
        payload, _ = self.info({"type": "userRole", "user": address}, reserve=60)
        return payload

    def meta(self) -> Any:
        payload, _ = self.info({"type": "meta"}, reserve=20)
        return payload

    def user_fills(self, address: str, start_ms: int, end_ms: int, *, aggregate: bool) -> list[Any]:
        body = {
            "type": "userFillsByTime",
            "user": address,
            "startTime": start_ms,
            "endTime": end_ms,
            "aggregateByTime": aggregate,
        }
        payload, _ = self.info(body, reserve=fills_weight(PAGE_MAX))
        if not isinstance(payload, list):
            raise DataError(f"userFillsByTime não devolveu lista: {str(payload)[:120]}")
        return payload


def _fill_key(fill: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(fill.get(k) for k in ("tid", "oid", "time", "hash", "px", "sz", "coin", "side"))


@dataclass
class Collected:
    fills: list[dict[str, Any]]
    count: int
    pages: int
    #: Instante do fill mais antigo da primeira página (as respostas vêm em ordem ascendente).
    first_time: int | None = None
    #: `True` se a contagem parou cedo porque passou de `stop_after`.
    capped: bool = False


def collect_fills(
    client: HlClient,
    address: str,
    start_ms: int,
    end_ms: int,
    *,
    aggregate: bool = False,
    keep: bool = True,
    stop_after: int | None = None,
) -> Collected:
    """Pagina `userFillsByTime` para frente até esgotar o intervalo.

    A resposta vem em ordem ascendente de tempo (confirmado em dado real, ao contrário do
    que a documentação sugere). `startTime` é inclusivo, então cada página reinicia no
    instante do último fill e repete os fills desse milissegundo; eles são descartados por
    *multiconjunto* de chaves, de modo que fills genuinamente idênticos não se fundem. A
    paginação termina quando uma página não traz nada novo.

    Com `keep=False` o conteúdo é descartado e só a contagem sai. É o único modo permitido
    para fills a partir do corte T (regra 3 do prompt 02). Com `stop_after`, para assim
    que a contagem passa desse valor (`capped=True`): serve para provar que uma carteira
    devolve mais de 10.000 fills sem pagar para paginar o resto.
    """
    kept: list[dict[str, Any]] = []
    cursor = start_ms
    boundary: Counter[tuple[Any, ...]] = Counter()
    count = pages = 0
    first_time: int | None = None
    while True:
        page = client.user_fills(address, cursor, end_ms, aggregate=aggregate)
        pages += 1
        if pages == 1 and page:
            first_time = min(int(f["time"]) for f in page)
        remaining = Counter(boundary)
        fresh: list[dict[str, Any]] = []
        for fill in page:
            key = _fill_key(fill)
            if int(fill["time"]) == cursor and remaining[key] > 0:
                remaining[key] -= 1
                continue
            fresh.append(fill)
        if not fresh:
            break
        count += len(fresh)
        if keep:
            kept.extend(fresh)
        cursor = max(int(f["time"]) for f in page)
        boundary = Counter(_fill_key(f) for f in page if int(f["time"]) == cursor)
        if stop_after is not None and count > stop_after:
            return Collected(kept, count, pages, first_time, capped=True)
    return Collected(kept, count, pages, first_time)


def fetch_wallet(ctx: Ctx, client: HlClient, address: str) -> dict[str, Any]:
    """Fills de uma carteira, com a política de janela da verificação.

    Três consultas: a janela de seleção `[T0, T)` (conteúdo, guardado); `[T, agora]`
    (**só a contagem**) e `[0, T0)` (só a contagem e o instante do mais antigo). A
    contagem para cedo quando o total passa de 10.000, o que basta para saber que o teto
    documentado não vale para aquela carteira. O resultado é cacheado em disco.
    """
    cache = ctx.path("fills", f"{address}.json")
    if cache.exists():
        record: dict[str, Any] = read_json(cache)
        return record

    weight_before = client.stats["weight"]
    window = collect_fills(client, address, WINDOW_START_MS, CUTOFF_MS - 1, keep=True)
    in_window = [f for f in window.fills if WINDOW_START_MS <= int(f["time"]) < CUTOFF_MS]
    fetched_at = now_ms()
    allowance = RETENTION_CAP - len(in_window)
    post = collect_fills(
        client, address, CUTOFF_MS, fetched_at, keep=False, stop_after=max(allowance, 0)
    )
    pre = collect_fills(
        client,
        address,
        0,
        WINDOW_START_MS - 1,
        keep=False,
        stop_after=max(allowance - post.count, 0),
    )

    total = len(in_window) + post.count + pre.count
    exceeds = total > RETENTION_CAP
    oldest = pre.first_time if pre.count else (window.first_time if in_window else None)
    if oldest is not None and oldest <= WINDOW_START_MS:
        history_starts = "antes da janela"
    elif in_window:
        history_starts = "dentro da janela"
    elif post.count:
        history_starts = "depois da janela"
    else:
        history_starts = "sem fills"
    record = {
        "address": address,
        "fetched_at_ms": fetched_at,
        "window_start_ms": WINDOW_START_MS,
        "cutoff_ms": CUTOFF_MS,
        "in_window_count": len(in_window),
        "pre_window_count": pre.count,
        "post_window_count": post.count,
        # Se a contagem parou cedo, o total real é maior que o somado aqui.
        "counts_are_lower_bounds": pre.capped or post.capped,
        "total_counted": total,
        "exceeds_documented_cap": exceeds,
        "at_documented_cap": total == RETENTION_CAP and not (pre.capped or post.capped),
        "oldest_ms": oldest,
        "history_starts": history_starts,
        "pages": window.pages + post.pages + pre.pages,
        "weight": client.stats["weight"] - weight_before,
        "fills": in_window,
    }
    write_json(cache, record)
    return record


def fetch_wallet_aggregated(ctx: Ctx, client: HlClient, address: str) -> dict[str, Any]:
    """Os fills da janela de seleção com `aggregateByTime = true`, para contar."""
    cache = ctx.path("fills_agg", f"{address}.json")
    if cache.exists():
        record: dict[str, Any] = read_json(cache)
        return record
    got = collect_fills(client, address, WINDOW_START_MS, CUTOFF_MS - 1, aggregate=True)
    record = {"address": address, "in_window_count": got.count, "fills": got.fills}
    write_json(cache, record)
    return record


# ─── Leaderboard e metadados ─────────────────────────────────────────────────


def load_leaderboard(ctx: Ctx, http: httpx.Client | None = None) -> dict[str, Any]:
    """Baixa o leaderboard e guarda só endereço e patrimônio (regra 2 do prompt 02).

    `windowPerformances` traz PnL, ROI e volume por janela, que a verificação não pode
    gravar. Dele só se confirma a existência e a estrutura (nomes de janelas e de
    campos, sem valores). O corpo bruto não é guardado; fica o hash dele.
    """
    cache = ctx.path("leaderboard.json")
    if cache.exists():
        data: dict[str, Any] = read_json(cache)
        return data
    client = http or httpx.Client(timeout=180.0, headers={"User-Agent": USER_AGENT})
    resp = client.get(LEADERBOARD_URL)
    resp.raise_for_status()
    body = resp.json()
    rows = body["leaderboardRows"]
    key_counts: Counter[str] = Counter(k for row in rows for k in row)
    window_names: Counter[str] = Counter()
    window_fields: Counter[str] = Counter()
    wp_present = 0
    for row in rows:
        wp = row.get("windowPerformances")
        if isinstance(wp, list) and wp:
            wp_present += 1
            for entry in wp:
                window_names[str(entry[0])] += 1
                window_fields.update(entry[1].keys())
    addresses = [row["ethAddress"] for row in rows]
    values = [float(row["accountValue"]) for row in rows]
    data = {
        "retrieved_at_ms": now_ms(),
        "source": LEADERBOARD_URL,
        "sha256": hashlib.sha256(resp.content).hexdigest(),
        "size_bytes": len(resp.content),
        "top_level_keys": sorted(body.keys()),
        "n_rows": len(rows),
        "row_key_counts": dict(key_counts),
        "rows_with_window_performances": wp_present,
        "window_names": dict(window_names),
        "window_fields": dict(window_fields),
        "min_account_value": min(values),
        "n_account_value_ge_30000": sum(v >= 30_000 for v in values),
        "n_invalid_addresses": sum(
            not (isinstance(a, str) and a.startswith("0x") and len(a) == 42) for a in addresses
        ),
        "n_duplicate_addresses": len(addresses) - len({a.lower() for a in addresses}),
        "rows": [
            {"ethAddress": row["ethAddress"], "accountValue": float(row["accountValue"])}
            for row in rows
        ],
    }
    write_json(cache, data)
    return data


def load_meta(ctx: Ctx, client: HlClient) -> dict[str, Any]:
    """Metadados dos perpétuos do primeiro dex: nome, `szDecimals`, `isDelisted`."""
    cache = ctx.path("meta.json")
    if cache.exists():
        meta: dict[str, Any] = read_json(cache)
        return meta
    payload = client.meta()
    universe = payload["universe"]
    meta = {
        "retrieved_at_ms": now_ms(),
        "n_assets": len(universe),
        "n_delisted": sum(bool(u.get("isDelisted")) for u in universe),
        "fields": sorted({k for u in universe for k in u}),
        "assets": {
            u["name"]: {"szDecimals": u["szDecimals"], "isDelisted": bool(u.get("isDelisted"))}
            for u in universe
        },
    }
    write_json(cache, meta)
    return meta
