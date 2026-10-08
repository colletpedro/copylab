"""Fills por carteira (T-022, T-023; RF-ING-02, RF-ING-07 CA-07.2, RF-ING-08; design §3.3).

**Paginação** (CA-02.1). Fills não agregados. A próxima página começa no instante do último
fill recebido, inclusive; os fills desse milissegundo que já tinham vindo são descartados
por **multiconjunto** do conteúdo inteiro de cada fill, de modo que dois fills idênticos
genuínos não se fundem e nenhum fill da fronteira se perde. Uma página com menos de
``page_max`` fills encerra a janela. Uma página cheia sem nada novo quer dizer mais de
``page_max`` fills num milissegundo, que a paginação por tempo não atravessa: falha
explícita, em vez de laço infinito.

**Teto** (CA-02.3). Passou de ``cap`` fills na janela, a coleta para, nada é gravado e a
cobertura fica com status ``frequência incompatível``.

**Classificação** (CA-02.4). Pelo nome do ativo e pelo ``meta``: perpétuo do primeiro dex se
o nome está no ``meta``; HIP-3 se tem prefixo de dex (``dex:ATIVO``); spot se começa com
``@`` ou contém ``/``; token de resultado se começa com ``#``; senão, outro. Todo fill é
gravado, com a classe; os nomes classificados como outro vão para o relatório.

**Validação** (CA-02.5). Cada campo é lido para o tipo da coluna; o que não é interpretável
vira nulo, e o fill é gravado assim mesmo. Fill de perpétuo do primeiro dex com algum dos 12
campos de RF-VER-01 CA-01.1 nulo é contado e reportado: é ele que torna a carteira
inelegível em F3 (T-063). Nas outras classes, preço ou tamanho nulo é notional zero, também
contado. Instante ou nome de ativo ilegível impedem gravar o fill e são falha da carteira.

**Cobertura e retomada** (RF-ING-07 CA-07.2). Uma linha de ``coverage`` por endereço e
janela, com o instante da ingestão, o número de fills, o status e o hash de conteúdo dos
fills gravados (RF-ING-08 CA-08.1). Uma ingestão interrompida recomeça do primeiro endereço
sem cobertura ``ok`` ou ``frequência incompatível`` naquela janela. Falha numa carteira é
registrada e não aborta as demais.

**Reingestão** (T-023; RF-ING-02 CA-02.2, RF-ING-08 CA-08.2; design §3.2). Com
``reingest``, as carteiras já cobertas são coletadas de novo. O conteúdo novo é comparado
com o gravado **sem olhar** ``seq``: igual, nada muda, e a ordem gravada fica. Diferente,
cada diferença vai para ``divergences``, com o valor anterior e o novo, e o conteúdo novo
substitui o antigo, o que muda o hash. Dentro de janela congelada o armazenamento mantém
as linhas gravadas: a divergência é registrada do mesmo jeito, e o dado fica como estava.
"""

import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import polars as pl

from copylab.exceptions import DataError
from copylab.ingestion.provider import FILLS_PAGE_MAX, InfoProvider
from copylab.logging import get_logger
from copylab.storage import ParquetRepository, ParquetStore, Span, content_hash, multiset_difference
from copylab.storage.tables import COVERAGE, DIVERGENCES, FILLS, SCHEMAS
from copylab.timeutil import Ms, iso

__all__ = [
    "FILL_FIELDS",
    "STATUS_FAILED",
    "STATUS_INCOMPATIBLE",
    "STATUS_OK",
    "Collected",
    "FillsReport",
    "WalletOutcome",
    "classify",
    "collect_fills",
    "fills_frame",
    "ingest_fills",
]

log = get_logger(__name__)

STATUS_OK: Final = "ok"
STATUS_INCOMPATIBLE: Final = "frequência incompatível"
STATUS_FAILED: Final = "falha"
#: Status que dispensam nova coleta na retomada.
_DONE: Final = frozenset({STATUS_OK, STATUS_INCOMPATIBLE})

#: Os 12 campos de RF-VER-01 CA-01.1, com o nome que a API usa.
FILL_FIELDS: Final = (
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
#: Coluna da tabela ``fills`` de cada um dos 12 campos.
_COLUMN: Final = {
    "time": "time_ms",
    "coin": "coin",
    "px": "px",
    "sz": "sz",
    "side": "side",
    "startPosition": "start_position",
    "dir": "dir",
    "crossed": "crossed",
    "closedPnl": "closed_pnl",
    "fee": "fee",
    "tid": "tid",
    "oid": "oid",
}
#: Faixa plausível de um instante em ms (2001 a 2033), a mesma da verificação de dados.
_TIME_RANGE: Final = (10**12, 2 * 10**12)

PERP: Final = "perp"
HIP3: Final = "hip3"
SPOT: Final = "spot"
OUTCOME: Final = "outcome"
OTHER: Final = "other"


def classify(coin: str, perps: frozenset[str]) -> str:
    """Classe do instrumento de um fill (CA-02.4), na ordem de design §3.3."""
    if coin in perps:
        return PERP
    if ":" in coin:
        return HIP3
    if coin.startswith("@") or "/" in coin:
        return SPOT
    if coin.startswith("#"):
        return OUTCOME
    return OTHER


# ─── Leitura dos campos ──────────────────────────────────────────────────────


def _float(value: object, *, positive: bool) -> float | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _liquidated_user(fill: dict[str, Any]) -> str | None:
    liquidation = fill.get("liquidation")
    if isinstance(liquidation, dict):
        user = liquidation.get("liquidatedUser")
        if isinstance(user, str) and user:
            return user.lower()
    return None


def _twap_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _row(seq: int, fill: dict[str, Any], perps: frozenset[str]) -> dict[str, Any]:
    time_ms = _positive_int(fill.get("time"))
    coin = _text(fill.get("coin"))
    if time_ms is None or not _TIME_RANGE[0] < time_ms < _TIME_RANGE[1] or coin is None:
        raise DataError(
            f"Fill sem instante ou ativo interpretável: {json.dumps(fill, sort_keys=True)[:200]}"
        )
    side = fill.get("side")
    crossed = fill.get("crossed")
    return {
        "seq": seq,
        "time_ms": time_ms,
        "coin": coin,
        "kind": classify(coin, perps),
        "px": _float(fill.get("px"), positive=True),
        "sz": _float(fill.get("sz"), positive=True),
        "side": side if side in ("A", "B") else None,
        "start_position": _float(fill.get("startPosition"), positive=False),
        "dir": _text(fill.get("dir")),
        "crossed": crossed if isinstance(crossed, bool) else None,
        "closed_pnl": _float(fill.get("closedPnl"), positive=False),
        "fee": _float(fill.get("fee"), positive=False),
        "tid": _positive_int(fill.get("tid")),
        "oid": _positive_int(fill.get("oid")),
        "twap_id": _twap_id(fill.get("twapId")),
        "liquidated_user": _liquidated_user(fill),
    }


def fills_frame(fills: Sequence[dict[str, Any]], perps: frozenset[str]) -> pl.DataFrame:
    """Tabela ``fills`` a partir das respostas, com ``seq`` na ordem em que vieram.

    Raises:
        DataError: fill sem instante ou sem ativo interpretável.
    """
    rows = [_row(seq, fill, perps) for seq, fill in enumerate(fills)]
    return pl.DataFrame(rows, schema=SCHEMAS[FILLS], orient="row")


# ─── Paginação ───────────────────────────────────────────────────────────────


def _key(fill: dict[str, Any]) -> str:
    """O conteúdo inteiro do fill, em forma canônica: a chave do multiconjunto."""
    return json.dumps(fill, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class Collected:
    fills: list[dict[str, Any]]
    pages: int
    capped: bool


def collect_fills(
    provider: InfoProvider,
    address: str,
    start: Ms,
    end: Ms,
    cap: int,
    page_max: int = FILLS_PAGE_MAX,
) -> Collected:
    """Todos os fills de ``[start, end)``, na ordem da API, ou os primeiros ``cap + 1``.

    Raises:
        DataError: página fora de ordem ou fora da janela, ou mais de ``page_max`` fills
            num só milissegundo.
    """
    collected: list[dict[str, Any]] = []
    cursor = start
    seen_at_cursor: Counter[str] = Counter()
    pages = 0
    while True:
        page = provider.user_fills(address, cursor, end)
        pages += 1
        times = [int(f["time"]) if isinstance(f.get("time"), int) else -1 for f in page]
        if any(t < cursor or t >= end for t in times):
            raise DataError(f"Página de {address} com fill fora de [{iso(cursor)}, {iso(end)}).")
        if times != sorted(times):
            raise DataError(f"Página de {address} fora da ordem crescente de instante.")
        remaining = Counter(seen_at_cursor)
        fresh: list[dict[str, Any]] = []
        for fill, t in zip(page, times, strict=True):
            key = _key(fill)
            if t == cursor and remaining[key] > 0:
                remaining[key] -= 1
            else:
                fresh.append(fill)
        collected.extend(fresh)
        if len(collected) > cap:
            return Collected(collected, pages, capped=True)
        if len(page) < page_max:
            return Collected(collected, pages, capped=False)
        if not fresh:
            raise DataError(
                f"{address}: mais de {page_max} fills em {iso(Ms(cursor))}; a paginação por "
                "instante não atravessa esse milissegundo."
            )
        cursor = Ms(times[-1])
        seen_at_cursor = Counter(_key(f) for f, t in zip(page, times, strict=True) if t == cursor)


# ─── Reingestão e divergências (T-023) ───────────────────────────────────────


def _cell(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value) if isinstance(value, bool) else str(value)


def _same(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    return a == b


def _divergences(removed: pl.DataFrame, added: pl.DataFrame, detected_at: Ms) -> pl.DataFrame:
    """Uma linha por campo que mudou, pareando os fills por instante e ``tid``.

    Fill gravado que não voltou é ``row_removed``; fill novo sem par é ``row_added``. O
    valor de cada lado é texto: a coluna é a mesma para campos de tipos diferentes.
    """
    pending: dict[tuple[object, object], list[dict[str, Any]]] = {}
    for row in added.iter_rows(named=True):
        pending.setdefault((row["time_ms"], row["tid"]), []).append(row)
    out: list[tuple[Any, ...]] = []
    for old in removed.iter_rows(named=True):
        candidates = pending.get((old["time_ms"], old["tid"]))
        if not candidates:
            out.append((old["time_ms"], old["tid"], "row_removed", _key(old), None, detected_at))
            continue
        new = candidates.pop(0)
        for name in removed.columns:
            if not _same(old[name], new[name]):
                out.append(
                    (
                        old["time_ms"],
                        old["tid"],
                        name,
                        _cell(old[name]),
                        _cell(new[name]),
                        detected_at,
                    )
                )
    for rows in pending.values():
        for new in rows:
            out.append((new["time_ms"], new["tid"], "row_added", None, _key(new), detected_at))
    return pl.DataFrame(out, schema=SCHEMAS[DIVERGENCES], orient="row")


@dataclass(frozen=True, slots=True)
class _Stored:
    n_fills: int
    content_hash: str
    changed: bool
    divergences: int
    frozen_kept: int


def _store_window(
    store: ParquetStore, address: str, span: Span, frame: pl.DataFrame, now: Ms
) -> _Stored:
    repo = ParquetRepository(store)
    partition = (address,)
    stored = repo.fills(address, span.start, span.end)
    already = any(
        s.start <= span.start and span.end <= s.end for s in store.spans(FILLS, partition)
    )
    divergences = 0
    changed = True
    kept = 0
    if already or stored.height:
        removed, added = multiset_difference(stored.drop("seq"), frame.drop("seq"))
        if removed.height == 0 and added.height == 0:
            changed = False
        else:
            found = _divergences(removed, added, now)
            divergences = found.height
            store.append(DIVERGENCES, partition, found)
            log.warning(
                "ingest.fills.divergence",
                address=address,
                window=[iso(span.start), iso(span.end)],
                removed=removed.height,
                added=added.height,
                fields=divergences,
            )
    if changed:
        outcome = store.write(FILLS, partition, frame, span=span, instant="time_ms")
        kept = outcome.frozen_kept.height
    final = repo.fills(address, span.start, span.end)
    return _Stored(
        final.height, content_hash(final, ["time_ms", "seq"]), changed, divergences, kept
    )


# ─── Ingestão de uma lista ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WalletOutcome:
    address: str
    status: str
    n_fills: int = 0
    pages: int = 0
    skipped: bool = False
    changed: bool = False
    divergences: int = 0
    frozen_kept: int = 0
    invalid_perp_fills: int = 0
    zero_notional_fills: int = 0
    other_coins: tuple[str, ...] = ()
    error: str | None = None


@dataclass
class FillsReport:
    start: Ms
    end: Ms
    wallets: list[WalletOutcome] = field(default_factory=list)

    @property
    def failed(self) -> list[WalletOutcome]:
        return [w for w in self.wallets if w.status == STATUS_FAILED]

    @property
    def other_coins(self) -> list[str]:
        """Nomes classificados como "outro", em todas as carteiras (CA-02.4)."""
        return sorted({coin for w in self.wallets for coin in w.other_coins})


def _coverage_status(store: ParquetStore, address: str, span: Span) -> str | None:
    rows = ParquetRepository(store).coverage(address, span.start, span.end)
    exact = rows.filter((pl.col("start_ms") == span.start) & (pl.col("end_ms") == span.end))
    return None if exact.height == 0 else str(exact.item(-1, "status"))


def _record_coverage(
    store: ParquetStore, address: str, span: Span, now: Ms, n: int, status: str, digest: str
) -> None:
    frame = pl.DataFrame(
        [(span.start, span.end, now, n, status, digest)], schema=SCHEMAS[COVERAGE], orient="row"
    )
    store.write(COVERAGE, (address,), frame, span=span, instant="start_ms")


def _ingest_wallet(
    provider: InfoProvider,
    store: ParquetStore,
    address: str,
    span: Span,
    perps: frozenset[str],
    cap: int,
    page_max: int,
    now: Callable[[], Ms],
) -> WalletOutcome:
    collected = collect_fills(provider, address, span.start, span.end, cap, page_max)
    if collected.capped:
        _record_coverage(store, address, span, now(), len(collected.fills), STATUS_INCOMPATIBLE, "")
        return WalletOutcome(address, STATUS_INCOMPATIBLE, len(collected.fills), collected.pages)
    frame = fills_frame(collected.fills, perps)
    stored = _store_window(store, address, span, frame, now())
    _record_coverage(store, address, span, now(), stored.n_fills, STATUS_OK, stored.content_hash)
    perp = pl.col("kind") == PERP
    required = [pl.col(_COLUMN[name]).is_null() for name in FILL_FIELDS]
    invalid = frame.filter(perp & pl.any_horizontal(required)).height
    zero = frame.filter(~perp & (pl.col("px").is_null() | pl.col("sz").is_null())).height
    others = frame.filter(pl.col("kind") == OTHER).get_column("coin").unique().sort().to_list()
    return WalletOutcome(
        address,
        STATUS_OK,
        stored.n_fills,
        collected.pages,
        changed=stored.changed,
        divergences=stored.divergences,
        frozen_kept=stored.frozen_kept,
        invalid_perp_fills=invalid,
        zero_notional_fills=zero,
        other_coins=tuple(others),
    )


def ingest_fills(
    provider: InfoProvider,
    store: ParquetStore,
    addresses: Sequence[str],
    span: Span,
    perps: frozenset[str],
    cap: int,
    now: Callable[[], Ms],
    *,
    reingest: bool = False,
    page_max: int = FILLS_PAGE_MAX,
) -> FillsReport:
    """Ingere os fills de ``span`` para cada endereço, na ordem dada.

    Endereço já coberto nessa janela (``ok`` ou ``frequência incompatível``) é pulado,
    salvo com ``reingest``. Falha numa carteira vira cobertura ``falha`` (se ela ainda não
    tinha cobertura) e não interrompe as outras.
    """
    report = FillsReport(span.start, span.end)
    began = now()
    for index, address in enumerate(addresses, start=1):
        previous = _coverage_status(store, address, span)
        if previous in _DONE and not reingest:
            report.wallets.append(WalletOutcome(address, previous, skipped=True))
            continue
        try:
            outcome = _ingest_wallet(provider, store, address, span, perps, cap, page_max, now)
        except DataError as exc:
            if previous is None or previous == STATUS_FAILED:
                _record_coverage(store, address, span, now(), 0, STATUS_FAILED, "")
            outcome = WalletOutcome(address, STATUS_FAILED, error=str(exc))
            log.error("ingest.fills.wallet_failed", address=address, error=str(exc))
        report.wallets.append(outcome)
        elapsed = (now() - began) / 1_000
        done = sum(1 for w in report.wallets if not w.skipped)
        left = len(addresses) - index
        log.info(
            "ingest.fills.wallet",
            progress=f"{index}/{len(addresses)}",
            address=address,
            status=outcome.status,
            fills=outcome.n_fills,
            pages=outcome.pages,
            invalid_perp_fills=outcome.invalid_perp_fills,
            divergences=outcome.divergences,
            elapsed_s=round(elapsed),
            eta_s=round(elapsed / done * left) if done else None,
        )
    return report
