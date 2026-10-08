"""Orçamento de peso da API de informação (RF-ING-07 CA-07.1, design §3.3).

A corretora limita o peso por IP numa janela de 60 s (1.200 por minuto, ADR-0001). O
orçamento guarda cada reserva com o instante em que foi feita e só libera uma nova quando
a soma das reservas dos últimos 60 s, mais ela, cabe no limite configurado. O relógio e a
espera são injetados: em produção, ``clock.monotonic`` e ``clock.sleep``; nos testes, um
relógio falso que a espera adianta.

O peso de uma página de fills só se conhece depois da resposta (20 mais 1 a cada 20 itens).
Por isso a requisição **reserva** o máximo possível antes de sair e, quando a resposta
chega, :meth:`WeightBudget.settle` troca a reserva pelo peso real, que nunca é maior. Em
qualquer instante, o peso que o orçamento registra é maior ou igual ao que a corretora
cobrou, e o limite vale também para o peso real.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from copylab.exceptions import ConfigError
from copylab.logging import get_logger

__all__ = ["Reservation", "WeightBudget"]

log = get_logger(__name__)

#: Janela deslizante do limite da corretora, em segundos (documentação da Hyperliquid,
#: "Rate limits": peso agregado por minuto por IP).
WINDOW_S: Final = 60.0
#: Folga somada a cada espera. Sem ela, a espera calculada em ponto flutuante pode cair um
#: nada antes da expiração da reserva mais antiga, e o laço giraria com esperas de zero.
_MARGIN_S: Final = 0.05


@dataclass(slots=True)
class Reservation:
    """Peso reservado no instante ``at`` do relógio do orçamento."""

    at: float
    weight: int


class WeightBudget:
    """Janela deslizante de 60 s com teto de ``limit_per_minute`` de peso."""

    def __init__(
        self,
        limit_per_minute: int,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        if limit_per_minute <= 0:
            raise ConfigError(f"Limite de peso precisa ser positivo, recebi {limit_per_minute}.")
        self._limit = limit_per_minute
        self._clock = clock
        self._sleep = sleep
        self._live: deque[Reservation] = deque()
        self.total = 0
        self.peak = 0
        self.waited_s = 0.0

    @property
    def limit(self) -> int:
        return self._limit

    def _used(self, now: float) -> int:
        while self._live and self._live[0].at <= now - WINDOW_S:
            self._live.popleft()
        return sum(r.weight for r in self._live)

    def acquire(self, weight: int) -> Reservation:
        """Bloqueia até ``weight`` caber na janela e devolve a reserva.

        Raises:
            ConfigError: se ``weight`` sozinho já passa do limite: nunca caberia.
        """
        if weight > self._limit:
            raise ConfigError(f"Peso {weight} maior que o limite de {self._limit} por minuto.")
        while True:
            now = self._clock()
            used = self._used(now)
            if used + weight <= self._limit:
                break
            wait = self._live[0].at + WINDOW_S - now + _MARGIN_S
            self.waited_s += wait
            self._sleep(wait)
        reservation = Reservation(now, weight)
        self._live.append(reservation)
        self.total += weight
        self.peak = max(self.peak, used + weight)
        return reservation

    def settle(self, reservation: Reservation, actual: int) -> None:
        """Troca a reserva pelo peso cobrado de fato.

        Um peso real maior que o reservado não deveria acontecer: a reserva é o máximo da
        requisição. Se acontecer, ele é registrado como veio e logado, para o orçamento
        continuar contando o que a corretora cobrou.
        """
        if actual > reservation.weight:
            log.warning(
                "ingestion.budget.under_reserved", reserved=reservation.weight, actual=actual
            )
        self.total += actual - reservation.weight
        reservation.weight = actual
