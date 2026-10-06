"""Configuração de logging estruturado.

O projeto não usa ``print()``. Toda saída observável passa por structlog, de
modo que o formato seja decidido em um único ponto: JSON quando o processo roda
como serviço (o coletor), legível por humanos quando roda em desenvolvimento.

Este módulo não lê o ambiente. Quem decide o formato é o chamador, a partir de
:class:`copylab.config.Settings` (CLAUDE.md §3: nada de ``os.getenv`` espalhado).
"""

import logging
import sys
from typing import Final, Literal, get_args

import structlog
from structlog.typing import FilteringBoundLogger, Processor

__all__ = ["LogLevel", "configure_logging", "get_logger"]

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_LEVELS: Final[dict[str, int]] = {name: logging.getLevelName(name) for name in get_args(LogLevel)}


def configure_logging(level: LogLevel = "INFO", *, json_logs: bool = False) -> None:
    """Configura structlog e a raiz do stdlib ``logging``.

    Pode ser chamada mais de uma vez: a última chamada vale. Por isso
    ``cache_logger_on_first_use`` é ``False``. Com ``True``, o primeiro logger
    usado congelaria a configuração vigente e reconfigurar (um teste, ou o
    callback do CLI depois de um import que já logou) não teria efeito.

    Args:
        level: Nível mínimo a emitir.
        json_logs: ``True`` para uma linha JSON por evento; ``False`` para console.
    """
    numeric_level = _LEVELS[level]

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        # RNF-07: timestamps em UTC, sem depender do fuso da máquina.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer: Processor
    if json_logs:
        processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Devolve um logger estruturado ligado ao módulo chamador."""
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger
