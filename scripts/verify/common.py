"""Constantes e caminhos compartilhados pelos scripts de verificação de dados (§4.1).

Código exploratório, fora de `src/`: mede e reporta, não decide nada e não altera
spec. Não passa pelo `mypy` nem entra na cobertura (ver HANDOFF.md).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

#: Semente de toda amostragem (§7.2: coortes de controle usam a mesma). Registrada no relatório.
SEED = 20261005

REPO_ROOT = Path(__file__).resolve().parents[2]


def utc_ms(year: int, month: int, day: int) -> int:
    """Meia-noite UTC do dia, em milissegundos."""
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


#: Janela de seleção da Rota A (§7.2): [2026-07-01, 2026-09-01) UTC. O corte T é o fim.
WINDOW_START_MS = utc_ms(2026, 7, 1)
CUTOFF_MS = utc_ms(2026, 9, 1)
