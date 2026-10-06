"""Interface de linha de comando do copylab.

Fase 0 expõe apenas ``version``. Os comandos de RF-CLI-01 (``ingest``,
``collect``, ``select``, ``evaluate``, ``gate``) entram quando as specs dos
módulos correspondentes passarem pelo gate de design.
"""

from importlib import metadata

import typer

from copylab.config import get_settings
from copylab.logging import configure_logging, get_logger

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
