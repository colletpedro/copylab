"""Dados de mercado dos ativos candidatos: percurso do proxy e funding (T-025, T-024;
design §3.3, "Quais ativos recebem proxy").

Os perpétuos do primeiro dex são percorridos em ordem decrescente de notional das
candidatas (:func:`copylab.selection.assets.order_candidate_assets`). Para cada um, o nome
na Binance vem da regra do arquivo de parâmetros, e a condição (i) do universo, perpétuo
equivalente com dado em todos os dias da janela, é conferida contra os arquivos. A busca
para quando ``max_assets`` ativos a cumprem. BTC entra sempre (RF-SEL-08 CA-08.5).

**Leitura adotada onde design e requisitos divergem.** O design diz "enquanto tiverem ao
menos 2.000 fills"; RF-SEL-08 CA-08.1 (ii) toma os 20 de maior notional *entre os que
cumprem (i)*, sem filtrar por fills, e (iii) é outra condição. Pela regra do próprio design
(valem os requisitos), o percurso passa por todos os perpétuos, em ordem, até 20 cumprirem
(i). Só os que têm ao menos ``min_fills`` fills podem entrar no universo, e só deles o
proxy é baixado inteiro; dos demais, (i) é conferida pelos ``.CHECKSUM`` diários, sem
baixar os arquivos. Ver HANDOFF.

Funding: um registro por hora da janela para os ativos que cumprem (i) e têm ao menos
``min_fills`` fills, e para BTC.

Falha num ativo (checksum divergente, rede esgotada, hora de funding faltante) é registrada
e não interrompe os outros. O relatório diz quais falharam, e a CLI sai com código diferente
de zero. Rodar de novo retoma: dia de proxy e janela de funding já gravados são pulados.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial

import polars as pl

from copylab.exceptions import DataError
from copylab.ingestion.funding import FundingResult, funding_covered, ingest_funding
from copylab.ingestion.provider import InfoProvider
from copylab.ingestion.proxy import DailyArchive, ProxyAsset, files_exist, ingest_proxy
from copylab.logging import get_logger
from copylab.selection.assets import CandidateAsset, order_candidate_assets
from copylab.storage import ParquetStore, Span

__all__ = ["MarketReport", "ingest_market"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WalkedAsset:
    """Um ativo do percurso. ``downloaded``: o proxy foi baixado inteiro, porque o ativo tem
    fills bastantes para entrar no universo; senão, (i) foi conferida pelos ``.CHECKSUM``."""

    asset: CandidateAsset
    downloaded: bool
    result: ProxyAsset


@dataclass
class MarketReport:
    order: list[CandidateAsset]
    walked: list[WalkedAsset] = field(default_factory=list)
    always: list[ProxyAsset] = field(default_factory=list)
    funding: list[FundingResult] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def meeting_i(self) -> list[str]:
        """Ativos do percurso que cumprem a condição (i), em ordem de notional."""
        return [w.asset.coin for w in self.walked if w.result.complete]

    @property
    def proxied(self) -> list[str]:
        """Ativos com o proxy da janela inteiro gravado: os candidatos ao universo e BTC."""
        coins = [w.asset.coin for w in self.walked if w.downloaded and w.result.complete]
        return coins + [r.coin for r in self.always if r.complete and r.coin not in coins]


def _proxy(report: MarketReport, what: str, run: Callable[[], ProxyAsset]) -> ProxyAsset | None:
    try:
        return run()
    except DataError as exc:
        report.failures.append((what, str(exc)))
        log.error("ingest.market.failed", what=what, error=str(exc))
        return None


def ingest_market(
    provider: InfoProvider,
    archive: DailyArchive,
    store: ParquetStore,
    candidate_fills: pl.DataFrame,
    span: Span,
    *,
    max_assets: int,
    min_fills: int,
    symbol_of: Callable[[str], str],
    always: Sequence[str] = ("BTC",),
) -> MarketReport:
    """Percorre os candidatos e grava o proxy e o funding de ``span``."""
    report = MarketReport(order_candidate_assets(candidate_fills))
    for asset in report.order:
        if len(report.meeting_i) >= max_assets:
            break
        coin, symbol = asset.coin, symbol_of(asset.coin)
        full = asset.n_fills >= min_fills
        result = _proxy(
            report,
            f"proxy {coin}",
            partial(ingest_proxy, archive, store, coin, symbol, span)
            if full
            else partial(files_exist, archive, coin, symbol, span),
        )
        if result is None:
            continue
        report.walked.append(WalkedAsset(asset, full, result))
        log.info(
            "ingest.market.asset",
            coin=coin,
            symbol=symbol,
            notional=round(asset.notional, 2),
            fills=asset.n_fills,
            downloaded=full,
            condition_i=result.complete,
            meeting_i=len(report.meeting_i),
        )

    walked_full = {w.asset.coin: w.result for w in report.walked if w.downloaded}
    for coin in always:
        result = walked_full.get(coin)
        if result is None:
            result = _proxy(
                report,
                f"proxy {coin}",
                partial(ingest_proxy, archive, store, coin, symbol_of(coin), span),
            )
            if result is None:
                continue
            report.always.append(result)
        if not result.complete:
            report.failures.append((f"proxy {coin}", "falta arquivo diário na janela"))

    for coin in report.proxied:
        if funding_covered(store, coin, span):
            continue
        try:
            report.funding.append(ingest_funding(provider, store, coin, span))
        except DataError as exc:
            report.failures.append((f"funding {coin}", str(exc)))
            log.error("ingest.market.failed", what=f"funding {coin}", error=str(exc))
    return report
