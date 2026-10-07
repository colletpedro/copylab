"""Interface de linha de comando do copylab.

Monta as peças (design §2.1): lê ``Settings``, a lista do coletor e o arquivo de
parâmetros, e entrega cada coisa a quem a usa. Os comandos de RF-CLI-01 entram com as
tarefas do plano que os constroem; por enquanto, ``version`` e os do coletor (T-014).

Erro esperado (configuração, dado) sai com código 1 e uma mensagem no log, sem traceback
(RF-CLI-01 CA-01.2).
"""

from collections.abc import Callable
from functools import wraps
from importlib import metadata
from pathlib import Path
from typing import Annotated

import typer

from copylab import clock
from copylab.collector.assets import DEFAULT_ASSETS_PATH, load_assets
from copylab.collector.compact import Compactor
from copylab.collector.recorder import WS_URL, RecorderConfig
from copylab.collector.service import collect as run_collector
from copylab.collector.status import collector_status
from copylab.config import get_settings
from copylab.exceptions import CopylabError
from copylab.logging import configure_logging, get_logger
from copylab.params import DEFAULT_PATH as PARAMS_PATH
from copylab.params import load_params
from copylab.storage import ParquetStore
from copylab.storage.segments import SegmentStore
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
