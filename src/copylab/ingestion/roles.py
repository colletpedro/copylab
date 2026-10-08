"""Tipo de conta (T-026; F1, design §3.3 "Tipo de conta").

``userRole`` é consultado só para as carteiras que a seleção mandar, as que passaram nos
outros filtros, porque pesa 60 por consulta. O resultado é um snapshot: a tabela ``roles``
ganha uma partição por instante de coleta, nunca sobrescrita, e o congelamento guarda esse
instante e o hash (design §3.2). Quem chama é ``select`` (T-066); não há comando próprio.

Falha numa carteira é registrada e não interrompe as demais; a carteira fica fora da
tabela, e quem chama decide o que fazer com ela.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import polars as pl

from copylab.exceptions import DataError
from copylab.ingestion.provider import InfoProvider
from copylab.logging import get_logger
from copylab.storage import ParquetStore
from copylab.storage.tables import ROLES, SCHEMAS
from copylab.timeutil import Ms, iso

__all__ = ["RolesReport", "ingest_roles"]

log = get_logger(__name__)


@dataclass
class RolesReport:
    snapshot_ms: Ms
    roles: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)


def ingest_roles(
    provider: InfoProvider, store: ParquetStore, addresses: Sequence[str], now: Ms
) -> RolesReport:
    """Consulta o tipo de cada endereço e grava o snapshot no instante ``now``.

    Raises:
        DataError: já existe snapshot de ``roles`` nesse instante.
    """
    report = RolesReport(now)
    for address in addresses:
        try:
            report.roles[address] = provider.user_role(address)
        except DataError as exc:
            report.failed[address] = str(exc)
            log.error("ingest.roles.failed", address=address, error=str(exc))
    frame = pl.DataFrame(sorted(report.roles.items()), schema=SCHEMAS[ROLES], orient="row")
    store.create(ROLES, (str(now),), frame)
    log.info(
        "ingest.roles",
        snapshot_ms=now,
        at=iso(now),
        wallets=frame.height,
        failed=len(report.failed),
    )
    return report
