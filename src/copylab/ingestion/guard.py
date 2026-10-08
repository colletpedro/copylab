"""Guarda da janela de avaliação (T-027; RF-SEL-05 CA-05.4, ADR-0004, design §3.3).

Os comandos de ingestão recebem rota e janela, não datas, para poderem recusar:

- a janela de **avaliação** de uma rota enquanto não existir o congelamento dela, para
  fills e para dados de mercado, sem exceção para proxy e funding;
- a janela de **seleção da Rota B** enquanto não existir o congelamento da Rota A, porque
  ela contém a avaliação da Rota A.

A guarda roda antes de qualquer requisição. O congelamento de uma rota é o arquivo
``preregistro/rota-<a|b>.json``, o nome que RF-CLI-01 usa. O formato dele chega com T-066;
até lá, a guarda só confere que o arquivo existe, e nenhum existe.
"""

from pathlib import Path
from typing import Final, Literal

from copylab.exceptions import ConfigError
from copylab.params import Params
from copylab.storage import Span
from copylab.timeutil import MS_PER_DAY, Ms, iso

__all__ = [
    "FREEZE_DIR",
    "Route",
    "WindowName",
    "check_ingest_allowed",
    "freeze_path",
    "window_span",
]

Route = Literal["A", "B"]
WindowName = Literal["selection", "evaluation"]

#: Onde moram os congelamentos, relativo à raiz do repositório.
FREEZE_DIR: Final = Path("preregistro")


def freeze_path(route: Route, root: Path = FREEZE_DIR) -> Path:
    return root / f"rota-{route.lower()}.json"


def check_ingest_allowed(route: Route, window: WindowName, root: Path = FREEZE_DIR) -> None:
    """Recusa o que a guarda proíbe.

    Raises:
        ConfigError: janela de avaliação sem o congelamento da rota, ou seleção da Rota B
            sem o congelamento da Rota A. A mensagem diz o que falta.
    """
    if window == "evaluation" and not freeze_path(route, root).is_file():
        raise ConfigError(
            f"Recusado: a janela de avaliação da Rota {route} só é ingerida depois do "
            f"congelamento dela, e {freeze_path(route, root).as_posix()} não existe "
            "(RF-SEL-05 CA-05.4). "
            f"Rode `copylab select --route {route}` e commite o congelamento antes."
        )
    if route == "B" and window == "selection" and not freeze_path("A", root).is_file():
        raise ConfigError(
            "Recusado: a janela de seleção da Rota B contém a avaliação da Rota A e só é "
            f"ingerida depois do congelamento da Rota A, e {freeze_path('A', root).as_posix()} não "
            "existe (RF-SEL-05 CA-05.4)."
        )


def window_span(route: Route, window: WindowName, params: Params, cutoff: Ms | None) -> Span:
    """A janela pedida, ``[início, fim)``, pelo arquivo de parâmetros e pelo corte da Rota B.

    Raises:
        ConfigError: corte ausente ou fora da meia-noite na Rota B, ou janela que ainda não
            tem como ser calculada (a avaliação da Rota B depende da publicação, T-07x).
    """
    if route == "A":
        a = params.route_a
        if window == "selection":
            return Span(a.selection_start, a.selection_end)
        return Span(a.evaluation_start, a.evaluation_end)
    if window == "evaluation":
        raise ConfigError(
            "A janela de avaliação da Rota B depende do instante de publicação do congelamento "
            "(design §4.4), que ainda não tem leitor: chega com o Bloco H."
        )
    if cutoff is None or cutoff % MS_PER_DAY:
        raise ConfigError("A Rota B precisa de --cutoff, uma data UTC (AAAA-MM-DD).")
    days = params.route_b.selection_days
    span = Span(Ms(cutoff - days * MS_PER_DAY), cutoff)
    if span.end <= span.start:
        raise ConfigError(f"Janela de seleção da Rota B vazia até {iso(cutoff)}.")
    return span
