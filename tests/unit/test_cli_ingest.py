"""Comandos de ingestão e guarda da janela de avaliação (T-027; RF-SEL-05 CA-05.4,
RF-CLI-01 CA-01.2, RF-ING-07 CA-07.2).

A CLI roda com ``CliRunner``, com o diretório de trabalho numa pasta temporária (é nela que a
guarda procura ``preregistro/rota-<a|b>.json``) e o arquivo de parâmetros do repositório.
O provedor e o arquivo da Binance são os falsos: nada sai para a rede, e o provedor registra
cada chamada, o que prova que a guarda recusa *antes* de qualquer requisição.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez:

- ``check_ingest_allowed`` sem o caso da avaliação: falharam
  ``test_evaluation_ingest_requires_freeze`` e
  ``test_market_ingest_of_evaluation_window_requires_freeze`` (o comando passava da guarda).
- ``check_ingest_allowed`` sem o caso da seleção da Rota B: falhou
  ``test_route_b_selection_ingest_requires_route_a_freeze``.
- ``ingest fills`` sem o ``typer.Exit`` de falha parcial: falhou
  ``test_wallet_failure_does_not_abort_and_sets_exit_code`` (saía com 0).
"""

import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from copylab import cli
from copylab.exceptions import ConfigError
from copylab.ingestion.fake import FakeArchive, FakeInfo
from copylab.ingestion.guard import window_span
from copylab.params import load_params
from copylab.storage import ParquetRepository, ParquetStore
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms, parse_utc_date

REPO_ROOT = Path(__file__).resolve().parents[2]
PARAMS = str(REPO_ROOT / "preregistro" / "parametros.toml")
ASSETS = str(REPO_ROOT / "config" / "collector_assets.toml")
W0 = Ms(1_782_864_000_000)  # 2026-07-01, início da janela de seleção da Rota A
W1 = Ms(W0 + 62 * MS_PER_DAY)  # 2026-09-01, o corte
FIRST_DAY = W0 // MS_PER_DAY
A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40


def board() -> bytes:
    rows = [{"ethAddress": a, "accountValue": "50000", "windowPerformances": []} for a in (A, B, C)]
    return json.dumps({"leaderboardRows": rows}).encode()


def fill(t: int, coin: str) -> dict[str, Any]:
    return {
        "time": t, "coin": coin, "px": "100", "sz": "1", "side": "B", "startPosition": "0",
        "dir": "Open Long", "crossed": True, "closedPnl": "0", "fee": "0.1", "tid": t, "oid": 1,
    }  # fmt: skip


def fake_info() -> FakeInfo:
    funding = [
        {"coin": "BTC", "fundingRate": "0.00001", "premium": "0", "time": W0 + h * MS_PER_HOUR}
        for h in range(62 * 24)
    ]
    return FakeInfo(
        fills={A: [fill(W0 + 1_000, "BTC")], C: [fill(W0 + 2_000, "ETH")]},
        meta_payload={
            "universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4}]
        },
        leaderboard_body=board(),
        funding={"BTC": funding},
        failing=frozenset({B}),
    )


def btc_archive() -> FakeArchive:
    files: dict[tuple[str, int], bytes] = {}
    for day in range(FIRST_DAY, FIRST_DAY + 62):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("x.csv", f"1,100.0,1,1,1,{day * MS_PER_DAY + 5},false\n")
        files[("BTCUSDT", day)] = buffer.getvalue()
    for day in range(FIRST_DAY, FIRST_DAY + 62):
        files[("ETHUSDT", day)] = files[("BTCUSDT", day)]
    return FakeArchive(files)


@pytest.fixture
def env(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[Path, FakeInfo]]:
    clean_env.setenv("COPYLAB_DATA_DIR", str(tmp_path / "dados"))
    clean_env.chdir(tmp_path)
    info = fake_info()
    clean_env.setattr(cli, "_info_provider", lambda: info)
    clean_env.setattr(cli, "_archive", btc_archive)
    yield tmp_path, info


def run(*args: str) -> Any:
    return CliRunner().invoke(cli.app, ["ingest", *args])


# ─── Guarda (RF-SEL-05 CA-05.4) ──────────────────────────────────────────────


@pytest.mark.unit
def test_evaluation_ingest_requires_freeze(env: tuple[Path, FakeInfo]) -> None:
    root, info = env
    result = run("fills", "--route", "A", "--window", "evaluation", "--params", PARAMS)
    assert result.exit_code == 1
    assert "preregistro/rota-a.json" in result.output.replace("\\", "/")
    assert info.calls == []

    # Com o congelamento, a guarda deixa passar; o comando para adiante, porque a lista de
    # elegíveis vem do congelamento, que chega com T-066.
    (root / "preregistro").mkdir()
    (root / "preregistro" / "rota-a.json").write_text("{}", encoding="utf-8")
    passed = run("fills", "--route", "A", "--window", "evaluation", "--params", PARAMS)
    assert passed.exit_code == 1
    assert "T-066" in passed.output
    assert info.calls == []


@pytest.mark.unit
def test_market_ingest_of_evaluation_window_requires_freeze(env: tuple[Path, FakeInfo]) -> None:
    _, info = env
    result = run("market", "--route", "A", "--window", "evaluation", "--params", PARAMS)
    assert result.exit_code == 1
    assert "Recusado" in result.output
    assert info.calls == []


@pytest.mark.unit
@pytest.mark.parametrize("command", ["fills", "market"])
def test_route_b_selection_ingest_requires_route_a_freeze(
    env: tuple[Path, FakeInfo], command: str
) -> None:
    _, info = env
    result = run(
        command,
        "--route",
        "B",
        "--window",
        "selection",
        "--cutoff",
        "2026-10-20",
        "--params",
        PARAMS,
    )
    assert result.exit_code == 1
    assert "congelamento da Rota A" in result.output
    assert info.calls == []


# ─── Dado faltante (RF-CLI-01 CA-01.2) ───────────────────────────────────────


@pytest.mark.unit
def test_missing_data_fails_with_actionable_message_and_exit_code(
    env: tuple[Path, FakeInfo],
) -> None:
    result = run("fills", "--route", "A", "--window", "selection", "--params", PARAMS)
    assert result.exit_code == 1
    assert "copylab ingest leaderboard" in result.output

    assert run("leaderboard").exit_code == 0
    market = run(
        "market", "--route", "A", "--window", "selection", "--params", PARAMS, "--assets", ASSETS
    )
    assert market.exit_code == 1
    assert "copylab ingest fills --route A --window selection --block 0" in market.output


# ─── De ponta a ponta, com falha parcial (RF-ING-07 CA-07.2) ─────────────────


@pytest.mark.unit
def test_wallet_failure_does_not_abort_and_sets_exit_code(env: tuple[Path, FakeInfo]) -> None:
    root, _ = env
    assert run("leaderboard").exit_code == 0
    result = run("fills", "--route", "A", "--window", "selection", "--params", PARAMS)
    assert result.exit_code == 2
    assert B in result.output

    repo = ParquetRepository(ParquetStore(root / "dados"))
    statuses = {a: repo.coverage(a, W0, W1).item(0, "status") for a in (A, B, C)}
    assert statuses == {A: "ok", B: "falha", C: "ok"}
    # Nada de setembro: nenhuma consulta passou do corte.
    assert all(call[3] <= W1 for call in env[1].calls if call[0] == "user_fills")


@pytest.mark.unit
def test_market_after_fills_ingests_btc_proxy_and_funding(
    env: tuple[Path, FakeInfo],
) -> None:
    root, info = env
    assert run("leaderboard").exit_code == 0
    info.failing = frozenset()
    assert run("fills", "--route", "A", "--window", "selection", "--params", PARAMS).exit_code == 0
    result = run(
        "market", "--route", "A", "--window", "selection", "--params", PARAMS, "--assets", ASSETS
    )
    assert result.exit_code == 0, result.output
    repo = ParquetRepository(ParquetStore(root / "dados"))
    assert repo.proxy("BTC", W0, W1).height == 62
    assert repo.funding("BTC", W0, W1).height == 62 * 24
    assert "ingest.market.done" in result.output


# ─── Janelas ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_windows_come_from_parameters_and_route_b_cutoff() -> None:
    # Rota A, seleção: [2026-07-01, 2026-09-01), que termina exatamente no corte: nada de
    # setembro. Rota B, seleção com corte 2026-10-20: os 62 dias antes dele, a partir de
    # 2026-08-19 (20 de outubro menos 62 dias).
    loaded = load_params(Path(PARAMS))
    a = window_span("A", "selection", loaded, None)
    assert (a.start, a.end) == (parse_utc_date("2026-07-01"), parse_utc_date("2026-09-01"))
    assert a.end == loaded.route_a.cutoff
    b = window_span("B", "selection", loaded, parse_utc_date("2026-10-20"))
    assert (b.start, b.end) == (parse_utc_date("2026-08-19"), parse_utc_date("2026-10-20"))
    with pytest.raises(ConfigError, match="--cutoff"):
        window_span("B", "selection", loaded, None)
    with pytest.raises(ConfigError, match="Bloco H"):
        window_span("B", "evaluation", loaded, parse_utc_date("2026-10-20"))
