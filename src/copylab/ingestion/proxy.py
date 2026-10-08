"""Preço proxy da Binance (T-025; RF-ING-06 CA-06.1 e CA-06.2, design §3.3).

Para cada ativo e dia: baixa o arquivo diário de negócios agregados do perpétuo USD-M e o
``.CHECKSUM`` publicado ao lado, confere o SHA-256 (divergente é falha explícita), e reduz
a uma linha por segundo com o mínimo, o máximo e o último preço do segundo, e o número de
negócios. Segundo sem negócio fica ausente, não preenchido. O arquivo bruto é baixado para
uma pasta temporária do sistema, fora do diretório de dados, e apagado em seguida
(RNF-10): o que fica é a série por segundo, gravada por ``storage``.

O instante dos negócios é conferido na borda: todos têm de cair dentro do dia do arquivo,
em milissegundos (design §3.1). Um arquivo em microssegundos, ou de outro dia, falha.

Arquivo ausente (HTTP 404) não é erro: é o ativo sem dado naquele dia, o que a condição (i)
do universo precisa saber (RF-SEL-08 CA-08.1). Erro de rede ou 5xx repete com recuo e,
esgotadas as tentativas, falha.
"""

import hashlib
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import httpx
import polars as pl

from copylab.exceptions import DataError
from copylab.logging import get_logger
from copylab.storage import ParquetStore, Span
from copylab.storage.tables import PROXY, SCHEMAS
from copylab.timeutil import MS_PER_DAY, MS_PER_SECOND, day_start, iso, utc_day

__all__ = [
    "BINANCE_BASE",
    "BinanceDaily",
    "DailyArchive",
    "ProxyAsset",
    "files_exist",
    "ingest_proxy",
    "ingest_proxy_day",
    "proxy_covered",
    "reduce_to_seconds",
]

log = get_logger(__name__)

#: Arquivos diários de negócios agregados dos perpétuos USD-M (data.binance.vision).
BINANCE_BASE: Final = "https://data.binance.vision/data/futures/um/daily/aggTrades"
#: Colunas do CSV, na ordem do arquivo; os mais antigos vêm sem cabeçalho.
CSV_COLUMNS: Final = (
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
)
_CHUNK: Final = 1 << 20


def _day_text(day: int) -> str:
    return iso(day_start(day))[:10]


class DailyArchive(Protocol):
    """Onde estão os arquivos diários. ``symbol`` é o da Binance, ``day`` é o dia UTC."""

    def checksum(self, symbol: str, day: int) -> str | None: ...
    def download(self, symbol: str, day: int, dest: Path) -> bool: ...


class BinanceDaily:
    """:class:`DailyArchive` sobre ``httpx``, com recuo em erro de rede e 5xx."""

    def __init__(
        self,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None],
        max_retries: int,
        backoff_initial_s: float,
        backoff_max_s: float,
        base: str = BINANCE_BASE,
    ) -> None:
        self._http = http
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_initial_s = backoff_initial_s
        self._backoff_max_s = backoff_max_s
        self._base = base
        self.downloaded_bytes = 0

    def _url(self, symbol: str, day: int) -> str:
        return f"{self._base}/{symbol}/{symbol}-aggTrades-{_day_text(day)}.zip"

    def _get(self, url: str, sink: Callable[[httpx.Response], None]) -> bool:
        last_error = ""
        for attempt in range(self._max_retries + 1):
            if attempt:
                self._sleep(min(self._backoff_max_s, self._backoff_initial_s * 2 ** (attempt - 1)))
            try:
                with self._http.stream("GET", url) as response:
                    if response.status_code == 404:
                        return False
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = f"HTTP {response.status_code}"
                        continue
                    if response.status_code != 200:
                        raise DataError(f"{url}: HTTP {response.status_code}.")
                    sink(response)
                    return True
            except httpx.TransportError as exc:
                last_error = f"transporte: {type(exc).__name__}"
        raise DataError(f"{url}: {self._max_retries + 1} tentativas esgotadas ({last_error}).")

    def checksum(self, symbol: str, day: int) -> str | None:
        body: list[bytes] = []
        found = self._get(self._url(symbol, day) + ".CHECKSUM", lambda r: body.append(r.read()))
        if not found:
            return None
        text = b"".join(body).decode("ascii", errors="replace").split()
        if not text or len(text[0]) != 64:
            raise DataError(f"CHECKSUM de {symbol} {_day_text(day)} fora do formato.")
        return text[0].lower()

    def download(self, symbol: str, day: int, dest: Path) -> bool:
        def write(response: httpx.Response) -> None:
            with dest.open("wb") as handle:
                for block in response.iter_bytes(_CHUNK):
                    handle.write(block)
                    self.downloaded_bytes += len(block)

        return self._get(self._url(symbol, day), write)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def reduce_to_seconds(csv_path: Path, day: int) -> pl.DataFrame:
    """Série por segundo de um dia de negócios agregados (CA-06.1).

    ``last`` é o preço do negócio de maior ``agg_trade_id`` no segundo.

    Raises:
        DataError: instante fora do dia, o que denuncia unidade errada.
    """
    with csv_path.open("rb") as handle:
        has_header = handle.readline().startswith(b"agg_trade_id")
    trades = pl.scan_csv(
        csv_path, has_header=has_header, new_columns=None if has_header else list(CSV_COLUMNS)
    ).select(
        pl.col("agg_trade_id").cast(pl.Int64),
        pl.col("price").cast(pl.Float64),
        pl.col("transact_time").cast(pl.Int64),
    )
    bounds = trades.select(
        pl.col("transact_time").min().alias("first"), pl.col("transact_time").max().alias("last")
    ).collect()
    first, last = bounds.item(0, "first"), bounds.item(0, "last")
    if first is not None and not (day_start(day) <= first and last < day_start(day + 1)):
        raise DataError(
            f"{csv_path.name}: instantes de {first} a {last} fora do dia {_day_text(day)} em "
            "milissegundos; o arquivo não está na unidade esperada."
        )
    return (
        trades.sort("agg_trade_id")
        .group_by((pl.col("transact_time") // MS_PER_SECOND).alias("second"), maintain_order=True)
        .agg(
            pl.col("price").min().alias("low"),
            pl.col("price").max().alias("high"),
            pl.col("price").last().alias("last"),
            pl.len().cast(pl.Int64).alias("n_trades"),
        )
        .sort("second")
        .collect()
        .cast(pl.Schema(SCHEMAS[PROXY]))
    )


def proxy_covered(store: ParquetStore, coin: str, day: int) -> bool:
    return store.exists(PROXY, (coin, str(day)))


@dataclass(frozen=True, slots=True)
class ProxyDay:
    day: int
    found: bool
    seconds: int = 0
    trades: int = 0
    zip_bytes: int = 0


def ingest_proxy_day(
    archive: DailyArchive, store: ParquetStore, coin: str, symbol: str, day: int
) -> ProxyDay:
    """Baixa, confere, reduz e grava um dia; apaga o arquivo bruto.

    Raises:
        DataError: checksum ausente ou divergente (CA-06.2), arquivo ilegível.
    """
    with tempfile.TemporaryDirectory(prefix="copylab-proxy-") as folder:
        zip_path = Path(folder) / f"{symbol}-{_day_text(day)}.zip"
        if not archive.download(symbol, day, zip_path):
            return ProxyDay(day, found=False)
        expected = archive.checksum(symbol, day)
        if expected is None:
            raise DataError(f"{zip_path.name} sem .CHECKSUM publicado: não há como conferir.")
        actual = _sha256(zip_path)
        if actual != expected:
            raise DataError(
                f"{zip_path.name}: SHA-256 {actual} difere do .CHECKSUM {expected} (CA-06.2)."
            )
        try:
            with zipfile.ZipFile(zip_path) as bundle:
                (name,) = bundle.namelist()
                csv_path = Path(bundle.extract(name, folder))
        except (zipfile.BadZipFile, ValueError) as exc:
            raise DataError(f"{zip_path.name} ilegível: {exc}") from exc
        series = reduce_to_seconds(csv_path, day)
        size = zip_path.stat().st_size
    span = Span(day_start(day), day_start(day + 1))
    store.write(
        PROXY, (coin, str(day)), series, span=span, instant=pl.col("second") * MS_PER_SECOND
    )
    trades = int(series.get_column("n_trades").sum())
    return ProxyDay(day, True, series.height, trades, size)


@dataclass(frozen=True, slots=True)
class ProxyAsset:
    """Resultado de um ativo numa janela: ``missing_day`` é o primeiro dia sem arquivo."""

    coin: str
    symbol: str
    days: int
    downloaded: int
    missing_day: int | None

    @property
    def complete(self) -> bool:
        return self.missing_day is None


def _days(span: Span) -> range:
    if span.start % MS_PER_DAY or span.end % MS_PER_DAY or span.empty:
        raise DataError(
            f"Janela de proxy fora da meia-noite: [{iso(span.start)}, {iso(span.end)})."
        )
    return range(utc_day(span.start), utc_day(span.end))


def ingest_proxy(
    archive: DailyArchive, store: ParquetStore, coin: str, symbol: str, span: Span
) -> ProxyAsset:
    """Todos os dias de ``span`` para o ativo, pulando os já gravados.

    Para no primeiro dia sem arquivo: o ativo já falhou na condição (i), e baixar o resto
    só gastaria tempo e disco.
    """
    downloaded = 0
    days = _days(span)
    for day in days:
        if proxy_covered(store, coin, day):
            continue
        result = ingest_proxy_day(archive, store, coin, symbol, day)
        if not result.found:
            log.warning("ingest.proxy.missing_day", coin=coin, symbol=symbol, day=_day_text(day))
            return ProxyAsset(coin, symbol, len(days), downloaded, day)
        downloaded += 1
        log.info(
            "ingest.proxy.day",
            coin=coin,
            symbol=symbol,
            day=_day_text(day),
            seconds=result.seconds,
            trades=result.trades,
            zip_mb=round(result.zip_bytes / 10**6, 2),
        )
    return ProxyAsset(coin, symbol, len(days), downloaded, None)


def files_exist(archive: DailyArchive, coin: str, symbol: str, span: Span) -> ProxyAsset:
    """Confere a condição (i) sem baixar os arquivos: só o ``.CHECKSUM`` de cada dia."""
    days = _days(span)
    for day in days:
        if archive.checksum(symbol, day) is None:
            return ProxyAsset(coin, symbol, len(days), 0, day)
    return ProxyAsset(coin, symbol, len(days), 0, None)
