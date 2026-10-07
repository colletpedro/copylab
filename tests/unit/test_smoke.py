"""Teste de fumaça da Fase 0.

Não valida comportamento de domínio — não existe domínio ainda. Valida que o
pacote importa, que os subpacotes vazios estão no lugar e que o CLI responde.
"""

import importlib
from importlib import metadata

import pytest
from typer.testing import CliRunner

import copylab
from copylab.cli import app
from copylab.exceptions import (
    ConfigError,
    CopylabError,
    DataError,
    LookaheadError,
    SimulationError,
)

_DOMAIN_SUBPACKAGES = (
    "copylab.ingestion",
    "copylab.collector",
    "copylab.storage",
    "copylab.leader",
    "copylab.selection",
    "copylab.sim",
    "copylab.analytics",
)


@pytest.mark.unit
def test_scaffold_imports_and_cli_answers(clean_env: pytest.MonkeyPatch) -> None:
    """O esqueleto da Fase 0 está de pé e coerente com a spec."""
    # Os sete subpacotes de domínio existem e importam.
    for name in _DOMAIN_SUBPACKAGES:
        assert importlib.import_module(name) is not None

    # A hierarquia de exceções tem uma raiz única.
    for error in (DataError, ConfigError, SimulationError, LookaheadError):
        assert issubclass(error, CopylabError)

    # O CLI sobe e o comando `version` reporta a versão do pacote.
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert copylab.__version__ in result.output


@pytest.mark.unit
def test_version_in_code_matches_installed_metadata() -> None:
    """`__version__` e o `pyproject.toml` são duas cópias do mesmo número.

    Nada as sincroniza, então este teste é o que impede a divergência: o CLI
    lê a versão do metadado instalado, e `__version__` é o que o código importa.
    """
    assert copylab.__version__ == metadata.version("copylab")
