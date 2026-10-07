"""Único módulo que lê o relógio da máquina (RNF-01, RNF-07, design §3.1).

Serve para carimbar o que entra, no coletor e na ingestão, e para o orçamento de peso
esperar. Só ``collector``, ``ingestion`` e ``cli`` podem importá-lo, e nenhum
cálculo de seleção, simulação ou métrica depende dele
(``test_architecture_time_boundary``). É também o único módulo que importa ``time``.
"""

import time
from typing import Final

from copylab.timeutil import Ms

__all__ = ["monotonic", "now", "sleep"]

_NS_PER_MS: Final = 1_000_000


def now() -> Ms:
    """Instante atual, em milissegundos UTC, pelo relógio de parede."""
    return Ms(time.time_ns() // _NS_PER_MS)


def monotonic() -> float:
    """Segundos de um relógio que nunca anda para trás, para medir intervalos."""
    return time.monotonic()


def sleep(seconds: float) -> None:
    """Bloqueia o processo por ``seconds`` segundos."""
    time.sleep(seconds)
