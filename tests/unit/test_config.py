"""Testes de `copylab.config`.

Cobre os defaults, a leitura do ambiente com prefixo `COPYLAB_`, a rejeição de
valor inválido como `ConfigError` e o isolamento do cache de `get_settings()`
entre testes.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from copylab.config import Settings, get_settings
from copylab.exceptions import ConfigError


@pytest.mark.unit
def test_defaults_without_environment(clean_env: pytest.MonkeyPatch) -> None:
    """Sem nenhuma variável, o app sobe em desenvolvimento, nível INFO."""
    settings = Settings(_env_file=None)
    assert settings.log_level == "INFO"
    assert settings.env == "dev"
    assert settings.json_logs is False


@pytest.mark.unit
def test_reads_copylab_prefixed_variables(clean_env: pytest.MonkeyPatch) -> None:
    """O prefixo é `COPYLAB_`; o nível é normalizado para maiúsculas."""
    clean_env.setenv("COPYLAB_LOG_LEVEL", " debug ")
    clean_env.setenv("COPYLAB_ENV", "prod")
    settings = Settings(_env_file=None)
    assert settings.log_level == "DEBUG"
    assert settings.json_logs is True


@pytest.mark.unit
def test_ignores_variables_with_other_prefix(clean_env: pytest.MonkeyPatch) -> None:
    """Variável de outro projeto não vaza para a configuração do copylab."""
    clean_env.setenv("QUANTLAB_LOG_LEVEL", "ERROR")
    clean_env.setenv("LOG_LEVEL", "ERROR")
    assert Settings(_env_file=None).log_level == "INFO"


@pytest.mark.unit
def test_unknown_copylab_variable_is_ignored(clean_env: pytest.MonkeyPatch) -> None:
    """Variável `COPYLAB_*` desconhecida não derruba a aplicação."""
    clean_env.setenv("COPYLAB_NAO_EXISTE", "1")
    assert Settings(_env_file=None).log_level == "INFO"


@pytest.mark.unit
def test_invalid_log_level_raises_config_error_naming_the_variable(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Nível inválido não cai em silêncio num default: é `ConfigError` acionável."""
    clean_env.setenv("COPYLAB_LOG_LEVEL", "verbose")
    with pytest.raises(ConfigError, match="COPYLAB_LOG_LEVEL"):
        Settings(_env_file=None)


@pytest.mark.unit
def test_settings_are_immutable(settings: Settings) -> None:
    """Configuração não muda depois de resolvida (RNF-01)."""
    with pytest.raises(ValidationError):
        # mypy já recusa a atribuição (modelo frozen); o teste prova que o runtime também.
        settings.log_level = "DEBUG"  # type: ignore[misc]


@pytest.mark.unit
def test_reads_dotenv_from_working_directory(workdir: Path, clean_env: pytest.MonkeyPatch) -> None:
    """Sem variável no processo, o `.env` do diretório corrente vale."""
    (workdir / ".env").write_text("COPYLAB_LOG_LEVEL=ERROR\n", encoding="utf-8")
    assert Settings().log_level == "ERROR"


@pytest.mark.unit
def test_process_environment_wins_over_dotenv(workdir: Path, clean_env: pytest.MonkeyPatch) -> None:
    """Variável do processo tem precedência sobre o `.env`."""
    (workdir / ".env").write_text("COPYLAB_LOG_LEVEL=ERROR\n", encoding="utf-8")
    clean_env.setenv("COPYLAB_LOG_LEVEL", "WARNING")
    assert Settings().log_level == "WARNING"


@pytest.mark.unit
def test_get_settings_sees_this_tests_own_env_a(clean_env: pytest.MonkeyPatch) -> None:
    """Metade 1 do par que prova isolamento do cache entre testes.

    Se `get_settings.cache_clear()` não rodasse em `clean_env`, este teste e
    `..._b` correriam risco de ver o valor um do outro dependendo da ordem de
    execução (o plugin `pytest-randomly` embaralha essa ordem).
    """
    clean_env.setenv("COPYLAB_LOG_LEVEL", "DEBUG")
    assert get_settings().log_level == "DEBUG"


@pytest.mark.unit
def test_get_settings_sees_this_tests_own_env_b(clean_env: pytest.MonkeyPatch) -> None:
    """Metade 2 do par — ver docstring de `..._a`."""
    clean_env.setenv("COPYLAB_LOG_LEVEL", "ERROR")
    assert get_settings().log_level == "ERROR"
