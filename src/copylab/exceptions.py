"""Hierarquia de exceções do copylab.

Sem lógica: as subclasses existem para que o chamador consiga distinguir a
origem do erro (dado, configuração, simulação, leitura do futuro) sem
inspecionar mensagens.
"""

__all__ = ["ConfigError", "CopylabError", "DataError", "LookaheadError", "SimulationError"]


class CopylabError(Exception):
    """Raiz de toda exceção levantada deliberadamente pelo copylab."""


class DataError(CopylabError):
    """Falha de ingestão, validação ou leitura de dados."""


class ConfigError(CopylabError):
    """Configuração ausente, malformada ou inconsistente."""


class SimulationError(CopylabError):
    """Violação de invariante ou falha durante a simulação."""


class LookaheadError(CopylabError):
    """Leitura de informação que ainda não era conhecível no instante pedido.

    Levantada pelo repositório limitado pelo corte (RF-SEL-01 CA-01.1) e pelas
    entradas do simulador presas ao cursor (RF-SIM-01 CA-01.3). Não é ``DataError``
    de propósito: o dado existe e está íntegro; quem errou foi quem pediu.
    """
