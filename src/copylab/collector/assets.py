"""Lista de ativos do coletor, em arquivo versionado (design §3.4 e decisão 12)."""

import re
import tomllib
from pathlib import Path
from typing import Final

from copylab.exceptions import ConfigError

__all__ = ["DEFAULT_ASSETS_PATH", "REQUIRED", "load_assets"]

#: Caminho do arquivo, relativo à raiz do repositório.
DEFAULT_ASSETS_PATH: Final = Path("config/collector_assets.toml")
#: Sempre gravado: o benchmark depende dele (RF-SEL-08 CA-08.5).
REQUIRED: Final = "BTC"
#: Perpétuo do primeiro dex: letras e dígitos, com o ``k`` minúsculo dos múltiplos de mil.
_COIN: Final = re.compile(r"[A-Za-z0-9]+")


def load_assets(path: Path = DEFAULT_ASSETS_PATH) -> tuple[str, ...]:
    """Lê a lista, na ordem do arquivo.

    Raises:
        ConfigError: arquivo ausente ou inválido, lista vazia, repetida, com nome que não é
            de perpétuo do primeiro dex, ou sem BTC.
    """
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Lista do coletor {path} não existe.") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Lista do coletor {path} não é TOML válido: {exc}.") from exc

    coins = raw.get("coins")
    if set(raw) != {"coins"} or not isinstance(coins, list) or not coins:
        raise ConfigError(f"{path} precisa de uma única chave, `coins`, com uma lista não vazia.")
    bad = [c for c in coins if not isinstance(c, str) or _COIN.fullmatch(c) is None]
    if bad:
        raise ConfigError(f"{path}: nomes que não são de perpétuo do primeiro dex: {bad}.")
    repeated = sorted({c for c in coins if coins.count(c) > 1})
    if repeated:
        raise ConfigError(f"{path}: ativos repetidos: {repeated}.")
    if REQUIRED not in coins:
        raise ConfigError(f"{path}: {REQUIRED} precisa estar na lista (RF-SEL-08 CA-08.5).")
    return tuple(coins)
