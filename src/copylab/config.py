"""Configuração da aplicação, lida do ambiente com o prefixo ``COPYLAB_``.

``Settings`` descreve só o ambiente de execução. Parâmetro pré-registrado
(§7.2 dos requisitos da Fase 1: janelas, Δ, taxas, filtros) não mora aqui: vem do
arquivo de parâmetros e de nenhum outro lugar (RF-SEL-02 CA-02.2). Misturar os
dois permitiria mudar um parâmetro congelado com uma variável de ambiente.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from copylab.exceptions import ConfigError
from copylab.logging import LogLevel

__all__ = ["Settings", "get_settings"]

#: Ambientes tratados como desenvolvimento — log colorido e legível.
_DEV_ENVIRONMENTS: Final = frozenset({"dev", "development", "local", "test"})


class Settings(BaseSettings):
    """Parâmetros de execução resolvidos a partir do ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="COPYLAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    log_level: LogLevel = Field(
        default="INFO",
        description="Nível mínimo de log emitido por structlog.",
    )
    env: str = Field(
        default="dev",
        description="dev | development | local | test: log legível. Qualquer outro "
        "valor (ex.: prod): log em JSON, uma linha por evento.",
    )
    data_dir: Path | None = Field(
        default=None,
        description="Diretório de dados (ADR-0006), fora do git. Só copylab.storage o "
        "usa; sem ele, abrir o armazenamento é ConfigError.",
    )
    # Números que só mudam a operação, não o resultado do estudo (design 1.1 §3.9).
    weight_limit_per_minute: int = Field(
        default=1_000,
        gt=0,
        le=1_200,
        description="Peso por minuto que a ingestão se permite na API de informação "
        "(RF-ING-07 CA-07.1). O teto da corretora é 1.200 por IP (ADR-0001).",
    )
    disk_budget_gb: float = Field(
        default=30.0,
        gt=0,
        description="Orçamento de disco da fase, em GB (RNF-10). O status do coletor "
        "projeta o uso contra ele.",
    )
    disk_projection_days: int = Field(
        default=45,
        gt=0,
        description="Horizonte, em dias, da projeção de disco do coletor (RF-COL-04 CA-04.2).",
    )
    collector_flush_seconds: float = Field(
        default=5.0,
        gt=0,
        description="De quanto em quanto tempo o gravador descarrega os segmentos no disco. "
        "É o máximo que uma queda do processo faz perder.",
    )
    collector_silence_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Sem nenhuma mensagem por este tempo, o gravador dá a conexão por morta "
        "e reconecta. Não é a regra de lacuna, que está no arquivo de parâmetros.",
    )
    collector_backoff_initial_seconds: float = Field(
        default=1.0,
        gt=0,
        description="Primeira espera antes de reconectar; dobra a cada falha seguida.",
    )
    collector_backoff_max_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Espera máxima entre tentativas de reconexão.",
    )

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            problems = "; ".join(
                f"COPYLAB_{'.'.join(str(part) for part in error['loc']).upper()}: {error['msg']}"
                for error in exc.errors()
            )
            raise ConfigError(f"Configuração inválida. {problems}") from exc

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        """Aceita ``info`` e `` INFO `` do ambiente; a validação de verdade é do ``Literal``."""
        return value.strip().upper() if isinstance(value, str) else value

    @property
    def json_logs(self) -> bool:
        """``True`` fora de desenvolvimento: o log vira JSON."""
        return self.env.strip().lower() not in _DEV_ENVIRONMENTS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve as configurações do processo, resolvidas uma única vez.

    O cache mantém RNF-01 (determinismo): a mesma execução enxerga sempre a
    mesma configuração, mesmo que o ambiente mude no meio do caminho. Testes
    que precisem de outra configuração devem instanciar ``Settings`` direto.
    """
    return Settings()
