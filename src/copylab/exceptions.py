"""Hierarquia de exceções do copylab.

Sem lógica: as subclasses existem para que o chamador consiga distinguir a
origem do erro (dado, configuração, simulação) sem inspecionar mensagens.
"""

__all__ = ["ConfigError", "CopylabError", "DataError", "SimulationError"]


class CopylabError(Exception):
    """Raiz de toda exceção levantada deliberadamente pelo copylab."""


class DataError(CopylabError):
    """Falha de ingestão, validação ou leitura de dados (inclusive leitura proibida)."""


class ConfigError(CopylabError):
    """Configuração ausente, malformada ou inconsistente."""


class SimulationError(CopylabError):
    """Violação de invariante ou falha durante a simulação."""
