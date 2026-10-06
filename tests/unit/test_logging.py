"""Testes de `copylab.logging`.

Cobre o contrato que o resto do projeto assume: JSON ou console conforme o
chamador pede, timestamp em UTC (RNF-07), filtro por nível e reconfiguração que
realmente vale.
"""

import json

import pytest

from copylab.logging import configure_logging, get_logger


def _events(captured: str) -> list[dict[str, object]]:
    """Interpreta a saída como uma linha JSON por evento."""
    return [json.loads(line) for line in captured.splitlines() if line.strip()]


@pytest.mark.unit
def test_json_output_has_event_fields_and_utc_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)
    get_logger("teste").info("evento.ocorreu", chave=1)

    (event,) = _events(capsys.readouterr().out)
    assert event["event"] == "evento.ocorreu"
    assert event["chave"] == 1
    assert event["level"] == "info"
    # RNF-07: ISO 8601 em UTC, marcado com Z, nunca fuso local.
    assert str(event["timestamp"]).endswith("Z")


@pytest.mark.unit
def test_console_output_is_human_readable_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=False)
    get_logger("teste").info("evento.ocorreu", chave=1)

    out = capsys.readouterr().out
    assert "evento.ocorreu" in out
    assert "chave" in out
    assert not out.lstrip().startswith("{")


@pytest.mark.unit
def test_events_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_logs=True)
    log = get_logger("teste")
    log.info("some")
    log.warning("fica")

    assert [e["event"] for e in _events(capsys.readouterr().out)] == ["fica"]


@pytest.mark.unit
def test_reconfiguring_applies_to_a_logger_already_used(capsys: pytest.CaptureFixture[str]) -> None:
    """A última chamada de `configure_logging` vale, mesmo para logger já usado.

    Prova `cache_logger_on_first_use=False`. Mutação registrada: com a opção em
    `True`, o primeiro uso congela o filtro WARNING e o `debug` final some, o que
    derruba este teste.
    """
    log = get_logger("teste")

    configure_logging("WARNING", json_logs=True)
    log.warning("primeiro")
    log.debug("filtrado")

    configure_logging("DEBUG", json_logs=True)
    log.debug("depois")

    assert [e["event"] for e in _events(capsys.readouterr().out)] == ["primeiro", "depois"]
