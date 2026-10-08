"""Interface de linha de comando do copylab.

Monta as peças (design §2.1): lê ``Settings``, a lista do coletor e o arquivo de
parâmetros, e entrega cada coisa a quem a usa. Os comandos de RF-CLI-01 entram com as
tarefas do plano que os constroem; por enquanto, ``version``, os do coletor (T-014) e os de
ingestão (T-027).

Códigos de saída: erro esperado (configuração, dado, recusa da guarda) sai com 1 e uma
mensagem no log, sem traceback (RF-CLI-01 CA-01.2); um comando de ingestão que terminou a
lista mas teve falha em alguma carteira ou ativo sai com 2 (RF-ING-07 CA-07.2).
"""

from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from importlib import metadata
from pathlib import Path
from typing import Annotated, Final

import polars as pl
import typer

from copylab import clock
from copylab.collector.assets import DEFAULT_ASSETS_PATH, load_assets
from copylab.collector.compact import Compactor
from copylab.collector.recorder import WS_URL, RecorderConfig
from copylab.collector.service import collect as run_collector
from copylab.collector.status import collector_status
from copylab.config import get_settings
from copylab.exceptions import ConfigError, CopylabError, DataError
from copylab.ingestion.budget import WeightBudget
from copylab.ingestion.fills import STATUS_FAILED, STATUS_INCOMPATIBLE, STATUS_OK, ingest_fills
from copylab.ingestion.guard import Route, WindowName, check_ingest_allowed, window_span
from copylab.ingestion.market import ingest_market
from copylab.ingestion.provider import HyperliquidInfo, InfoProvider
from copylab.ingestion.proxy import BinanceDaily, DailyArchive
from copylab.ingestion.snapshots import ingest_snapshot
from copylab.logging import configure_logging, get_logger
from copylab.params import DEFAULT_PATH as PARAMS_PATH
from copylab.params import Params, load_params
from copylab.selection.pool import pool_block, sample_pool
from copylab.storage import ParquetRepository, ParquetStore, Span
from copylab.storage.segments import SegmentStore
from copylab.storage.tables import LEADERBOARD
from copylab.timeutil import Ms, iso, parse_utc_date, utc_day

__all__ = ["app"]

app = typer.Typer(
    name="copylab",
    help="Estudo de simulação de copy trading na Hyperliquid.",
    no_args_is_help=True,
    add_completion=False,
)

log = get_logger(__name__)


def _installed_version() -> str:
    """Versão do pacote instalado, com fallback quando rodando fora de install."""
    try:
        return metadata.version("copylab")
    except metadata.PackageNotFoundError:  # pragma: no cover - ambiente não instalado
        return "desconhecida"


@app.callback()
def main() -> None:
    """Configura o logging antes de qualquer subcomando."""
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)


@app.command()
def version() -> None:
    """Mostra a versão instalada do copylab."""
    log.info("copylab.version", version=_installed_version())


# ─── Coletor (T-014) ──────────────────────────────────────────────────────────

AssetsOption = Annotated[
    Path, typer.Option("--assets", help="Lista de ativos do coletor.", show_default=True)
]
ParamsOption = Annotated[
    Path, typer.Option("--params", help="Arquivo de parâmetros pré-registrados.", show_default=True)
]


def _exit_on_expected_error[**P, R](command: Callable[P, R]) -> Callable[P, R]:
    """Erro de configuração ou de dado vira código de saída 1 com mensagem, sem traceback."""

    @wraps(command)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return command(*args, **kwargs)
        except CopylabError as exc:
            log.error("copylab.error", kind=type(exc).__name__, message=str(exc))
            raise typer.Exit(code=1) from exc

    return wrapper


collect_app = typer.Typer(
    help="Coletor do livro e dos negócios (RF-COL). Sem subcomando, grava até ser parado.",
    no_args_is_help=False,
)
app.add_typer(collect_app, name="collect")


@collect_app.callback(invoke_without_command=True)
@_exit_on_expected_error
def collect(
    ctx: typer.Context,
    assets: AssetsOption = DEFAULT_ASSETS_PATH,
    duration_seconds: Annotated[
        float | None,
        typer.Option(
            help="Para depois de tantos segundos. Só para teste; sem ele, roda até SIGINT/SIGTERM."
        ),
    ] = None,
) -> None:
    """Grava o WebSocket público da corretora até receber SIGINT ou SIGTERM."""
    if ctx.invoked_subcommand is not None:
        return
    settings = get_settings()
    config = RecorderConfig(
        url=WS_URL,
        coins=load_assets(assets),
        flush_s=settings.collector_flush_seconds,
        silence_s=settings.collector_silence_seconds,
        backoff_initial_s=settings.collector_backoff_initial_seconds,
        backoff_max_s=settings.collector_backoff_max_seconds,
    )
    run_collector(config, SegmentStore.from_settings(settings, wait=clock.sleep), duration_seconds)


@collect_app.command("compact")
@_exit_on_expected_error
def collect_compact(
    day: Annotated[
        str | None,
        typer.Option(help="Dia UTC (AAAA-MM-DD). Sem ele, todos os dias encerrados pendentes."),
    ] = None,
    params: ParamsOption = PARAMS_PATH,
) -> None:
    """Converte os segmentos fechados em tabelas, confere as contagens e apaga os segmentos."""
    settings = get_settings()
    max_silence = load_params(params).book_record.max_book_silence_ms
    compactor = Compactor(
        SegmentStore.from_settings(settings), ParquetStore.from_settings(settings), max_silence
    )
    today = utc_day(clock.now())
    if day is None:
        days = compactor.pending_days(today)
    else:
        days = [utc_day(parse_utc_date(day))]
        if days[0] >= today:
            log.error("collector.compact.not_closed", day=day, message="o dia ainda não terminou")
            raise typer.Exit(code=1)
    if not days:
        log.info("collector.compact.nothing_to_do")
    for each in days:
        compactor.compact_day(each)


@collect_app.command("status")
@_exit_on_expected_error
def collect_status(
    assets: AssetsOption = DEFAULT_ASSETS_PATH, params: ParamsOption = PARAMS_PATH
) -> None:
    """Cobertura por ativo, latência de recebimento e projeção de disco, lendo só os arquivos."""
    settings = get_settings()
    loaded = load_params(params)
    now = clock.now()
    result = collector_status(
        SegmentStore.from_settings(settings),
        ParquetStore.from_settings(settings),
        load_assets(assets),
        now_ms=now,
        max_silence_ms=loaded.book_record.max_book_silence_ms,
        projection_days=settings.disk_projection_days,
        budget_bytes=round(settings.disk_budget_gb * 10**9),
    )
    for asset in result.assets:
        latency = asset.latency
        log.info(
            "collector.status.asset",
            coin=asset.coin,
            coverage_pct=None
            if asset.covered_fraction is None
            else round(100 * asset.covered_fraction, 3),
            since=None if asset.since_ms is None else iso(Ms(asset.since_ms)),
            last_book=None if asset.last_book_ms is None else iso(Ms(asset.last_book_ms)),
            gaps=asset.gap_count,
            gap_s=round(asset.gap_ms / 1_000, 1),
            trades=0 if latency is None else latency.count,
            latency_p50_ms=None if latency is None else latency.p50_ms,
            latency_p95_ms=None if latency is None else latency.p95_ms,
            latency_p99_ms=None if latency is None else latency.p99_ms,
        )
    overall = result.latency
    log.info(
        "collector.status.latency",
        trades=0 if overall is None else overall.count,
        p50_ms=None if overall is None else overall.p50_ms,
        p95_ms=None if overall is None else overall.p95_ms,
        p99_ms=None if overall is None else overall.p99_ms,
        delay_grid_s=list(loaded.delay.grid_s),
        note="recebimento menos corretora: rede mais diferença de relógio",
    )
    log.info(
        "collector.status.disk",
        recording_since=None if result.started_ms is None else iso(Ms(result.started_ms)),
        used_mb=round(result.disk_bytes / 10**6, 2),
        projected_gb=None
        if result.projected_bytes is None
        else round(result.projected_bytes / 10**9, 2),
        horizon_days=result.projection_days,
        budget_gb=round(result.budget_bytes / 10**9, 2),
        within_budget=result.within_budget,
    )


# ─── Ingestão (T-027) ─────────────────────────────────────────────────────────

#: Código de saída de um comando de ingestão que terminou com falha em parte da lista.
EXIT_PARTIAL: Final = 2

ingest_app = typer.Typer(
    help="Ingestão da API da Hyperliquid e do preço proxy da Binance (RF-ING).",
    no_args_is_help=True,
)
app.add_typer(ingest_app, name="ingest")


class RouteArg(StrEnum):
    A = "A"
    B = "B"


class WindowArg(StrEnum):
    selection = "selection"
    evaluation = "evaluation"


RouteOption = Annotated[RouteArg, typer.Option("--route", help="Rota do estudo.")]
WindowOption = Annotated[WindowArg, typer.Option("--window", help="Janela da rota.")]
SnapshotOption = Annotated[
    int | None,
    typer.Option(
        help="Instante (ms) do snapshot do leaderboard que define o pool. Obrigatório quando há "
        "mais de um gravado."
    ),
]
CutoffOption = Annotated[
    str | None, typer.Option(help="Corte da Rota B (AAAA-MM-DD, UTC). Só na Rota B.")
]


def _info_provider() -> InfoProvider:
    """Provedor real da API, com o orçamento de peso de ``Settings``. Os testes o trocam."""
    settings = get_settings()
    return HyperliquidInfo(
        WeightBudget(settings.weight_limit_per_minute, clock.monotonic, clock.sleep),
        http=HyperliquidInfo.client(settings.api_timeout_seconds),
        sleep=clock.sleep,
        max_retries=settings.api_max_retries,
        backoff_initial_s=settings.api_backoff_initial_seconds,
        backoff_max_s=settings.api_backoff_max_seconds,
    )


def _archive() -> DailyArchive:
    """Arquivos diários da Binance. Os testes o trocam."""
    settings = get_settings()
    return BinanceDaily(
        HyperliquidInfo.client(settings.api_timeout_seconds),
        sleep=clock.sleep,
        max_retries=settings.api_max_retries,
        backoff_initial_s=settings.api_backoff_initial_seconds,
        backoff_max_s=settings.api_backoff_max_seconds,
    )


def _log_api_usage(provider: InfoProvider) -> None:
    if isinstance(provider, HyperliquidInfo):
        log.info(
            "ingest.api_usage",
            requests=provider.requests,
            retries=provider.retries,
            rate_limited=provider.rate_limited,
        )


def _guarded_span(route: RouteArg, window: WindowArg, loaded: Params, cutoff: str | None) -> Span:
    """A guarda roda antes de qualquer leitura ou requisição (RF-SEL-05 CA-05.4)."""
    route_name: Route = "A" if route is RouteArg.A else "B"
    window_name: WindowName = "selection" if window is WindowArg.selection else "evaluation"
    check_ingest_allowed(route_name, window_name)
    if window is WindowArg.evaluation:
        raise ConfigError(
            "A ingestão da janela de avaliação lê os elegíveis do congelamento, cujo formato "
            "chega com T-066; o comando dela entra com o Bloco G."
        )
    cutoff_ms = None if cutoff is None else parse_utc_date(cutoff)
    if route is RouteArg.A and cutoff is not None:
        raise ConfigError(
            "--cutoff é só da Rota B; o corte da Rota A está no arquivo de parâmetros."
        )
    span = window_span(route_name, window_name, loaded, cutoff_ms)
    log.info(
        "ingest.window",
        route=route.value,
        window=window.value,
        start=iso(span.start),
        end=iso(span.end),
    )
    return span


def _snapshot(repo: ParquetRepository, snapshot: int | None) -> Ms:
    taken = repo.snapshots(LEADERBOARD)
    if not taken:
        raise DataError(
            "Não há snapshot do leaderboard. Rode `copylab ingest leaderboard` primeiro."
        )
    if snapshot is None:
        if len(taken) > 1:
            listed = ", ".join(f"{s} ({iso(s)})" for s in taken)
            raise ConfigError(
                f"Há {len(taken)} snapshots do leaderboard: {listed}. Diga qual define o pool "
                "com --snapshot <ms>; trocar de snapshot no meio troca o pool."
            )
        return taken[0]
    if Ms(snapshot) not in taken:
        raise DataError(f"Não há snapshot do leaderboard em {snapshot}. Gravados: {taken}.")
    return Ms(snapshot)


@ingest_app.command("leaderboard")
@_exit_on_expected_error
def ingest_leaderboard() -> None:
    """Grava um snapshot do leaderboard (bruto e derivado) e um dos tamanhos de lote."""
    store = ParquetStore.from_settings(get_settings())
    provider = _info_provider()
    ingest_snapshot(provider, store, clock.now())
    _log_api_usage(provider)


@ingest_app.command("fills")
@_exit_on_expected_error
def ingest_fills_command(
    route: RouteOption,
    window: WindowOption,
    block: Annotated[int, typer.Option(help="Bloco do pool, a partir de 0.")] = 0,
    snapshot: SnapshotOption = None,
    cutoff: CutoffOption = None,
    reingest: Annotated[
        bool, typer.Option(help="Coleta de novo as carteiras já cobertas e registra divergências.")
    ] = False,
    params: ParamsOption = PARAMS_PATH,
) -> None:
    """Fills não agregados de um bloco do pool, com retomada pela cobertura."""
    loaded = load_params(params)
    span = _guarded_span(route, window, loaded, cutoff)
    store = ParquetStore.from_settings(get_settings())
    repo = ParquetRepository(store)
    taken = _snapshot(repo, snapshot)
    perps = frozenset(repo.meta(taken).get_column("coin").to_list())
    pool = loaded.pool
    addresses = pool_block(
        repo.leaderboard(taken),
        loaded.filters.f2_min_account_value_usd,
        block,
        pool.block_size,
        pool.seed,
    )
    if not addresses:
        raise ConfigError(f"O bloco {block} do pool está vazio: o pool acabou antes dele.")
    log.info("ingest.fills.start", snapshot_ms=taken, block=block, wallets=len(addresses))
    provider = _info_provider()
    began = clock.now()
    report = ingest_fills(
        provider,
        store,
        addresses,
        span,
        perps,
        loaded.ingestion.max_fills_per_wallet,
        clock.now,
        reingest=reingest,
    )
    statuses = {
        status: sum(w.status == status for w in report.wallets)
        for status in (STATUS_OK, STATUS_INCOMPATIBLE, STATUS_FAILED)
    }
    log.info(
        "ingest.fills.done",
        block=block,
        wallets=len(report.wallets),
        skipped=sum(w.skipped for w in report.wallets),
        statuses=statuses,
        fills=sum(w.n_fills for w in report.wallets if not w.skipped),
        invalid_perp_fills=sum(w.invalid_perp_fills for w in report.wallets),
        zero_notional_fills=sum(w.zero_notional_fills for w in report.wallets),
        divergences=sum(w.divergences for w in report.wallets),
        other_coins=report.other_coins,
        elapsed_s=round((clock.now() - began) / 1_000),
    )
    _log_api_usage(provider)
    if report.failed:
        log.error(
            "ingest.fills.failed",
            wallets=[w.address for w in report.failed],
            action="rode o mesmo comando de novo: só as carteiras sem cobertura são coletadas",
        )
        raise typer.Exit(code=EXIT_PARTIAL)


@ingest_app.command("market")
@_exit_on_expected_error
def ingest_market_command(
    route: RouteOption,
    window: WindowOption,
    pool_blocks: Annotated[
        int, typer.Option(help="Quantos blocos do pool, a partir do 0, formam as candidatas.")
    ] = 1,
    snapshot: SnapshotOption = None,
    cutoff: CutoffOption = None,
    params: ParamsOption = PARAMS_PATH,
    assets: AssetsOption = DEFAULT_ASSETS_PATH,
) -> None:
    """Preço proxy e funding dos ativos candidatos e de BTC."""
    loaded = load_params(params)
    span = _guarded_span(route, window, loaded, cutoff)
    store = ParquetStore.from_settings(get_settings())
    repo = ParquetRepository(store)
    taken = _snapshot(repo, snapshot)
    pool = loaded.pool
    addresses = sample_pool(
        repo.leaderboard(taken),
        loaded.filters.f2_min_account_value_usd,
        pool_blocks,
        pool.block_size,
        pool.seed,
    )
    ok: list[str] = []
    pending: dict[int, int] = {}
    for index, address in enumerate(addresses):
        coverage = repo.coverage(address, span.start, span.end).filter(
            (pl.col("start_ms") == span.start) & (pl.col("end_ms") == span.end)
        )
        status = None if coverage.height == 0 else coverage.item(-1, "status")
        if status == STATUS_OK:
            ok.append(address)
        elif status != STATUS_INCOMPATIBLE:
            block = index // pool.block_size
            pending[block] = pending.get(block, 0) + 1
    if pending:
        commands = "; ".join(
            f"`copylab ingest fills --route {route.value} --window {window.value} --block {b}`"
            f" ({n} carteira(s))"
            for b, n in sorted(pending.items())
        )
        raise DataError(
            "Há carteiras do pool sem fills ingeridos, ou com falha, nesta janela: as candidatas "
            f"precisam estar completas antes de ordenar os ativos. Rode {commands}."
        )
    columns = ["coin", "kind", "px", "sz"]
    frames = [repo.fills(a, span.start, span.end).select(columns) for a in ok]
    candidate_fills = (
        pl.concat(frames)
        if frames
        else pl.DataFrame(
            schema={"coin": pl.String, "kind": pl.String, "px": pl.Float64, "sz": pl.Float64}
        )
    )
    log.info(
        "ingest.market.start", snapshot_ms=taken, candidates=len(ok), fills=candidate_fills.height
    )
    provider = _info_provider()
    began = clock.now()
    report = ingest_market(
        provider,
        _archive(),
        store,
        candidate_fills,
        span,
        max_assets=loaded.universe.max_assets,
        min_fills=loaded.universe.min_candidate_fills,
        symbol_of=loaded.binance.symbol,
    )
    collector = set(load_assets(assets))
    missing = [coin for coin in report.proxied if coin not in collector]
    log.info(
        "ingest.market.done",
        walked=len(report.walked),
        meeting_condition_i=report.meeting_i,
        proxied=report.proxied,
        funding=[f.coin for f in report.funding],
        failures=len(report.failures),
        elapsed_s=round((clock.now() - began) / 1_000),
    )
    _log_api_usage(provider)
    if missing:
        log.warning(
            "ingest.market.not_in_collector",
            coins=missing,
            action=f"acrescente-os a {assets} na máquina do coletor (docs/ingestao.md)",
        )
    if report.failures:
        for what, message in report.failures:
            log.error("ingest.market.failure", what=what, message=message)
        raise typer.Exit(code=EXIT_PARTIAL)
