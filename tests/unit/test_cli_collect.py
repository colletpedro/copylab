"""Comandos do coletor e lista de ativos (T-014).

O `collect` roda contra um servidor de WebSocket falso, numa thread, com a API síncrona do
`websockets`, porque o comando chama `asyncio.run` na thread do teste. Nada fala com a
corretora.
"""

import json
import logging
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner
from websockets.sync.server import ServerConnection, serve

from copylab import cli, clock
from copylab.collector.assets import DEFAULT_ASSETS_PATH, load_assets
from copylab.exceptions import ConfigError
from copylab.storage.segments import Record, SegmentStore
from copylab.timeutil import Ms

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOK = (
    '{"channel":"l2Book","data":{"coin":"BTC","time":1791261051777,"levels":'
    '[[{"px":"85560.0","sz":"5.6","n":21}],[{"px":"85561.0","sz":"2.2","n":23}]],"fast":true}}'
)


# ─── Lista de ativos ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_collector_list_is_the_27_of_the_verification_plus_the_route_a_candidates() -> None:
    """RF-SEL-08 CA-08.5 na parte do coletor: BTC está na lista. Os 27 são os da tabela de
    RF-VER-05 CA-05.4 com equivalente na Binance, na ordem dela. BNB e TAO,
    candidatos da Rota A que o coletor não gravava, vêm ao fim."""
    coins = load_assets(REPO_ROOT / DEFAULT_ASSETS_PATH)
    assert coins == (
        "HYPE", "BTC", "ETH", "ZEC", "PUMP", "SOL", "LIT", "ENA", "INJ", "DOGE",
        "ASTER", "TRUMP", "PENGU", "VVV", "AAVE", "FARTCOIN", "XRP", "NEAR", "ADA",
        "XMR", "UNI", "kBONK", "SYRUP", "WLD", "kPEPE", "LINK", "AVAX", "BNB", "TAO",
    )  # fmt: skip
    assert "BTC" in coins


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('coins = ["ETH", "SOL"]', "BTC"),
        ('coins = ["BTC", "BTC"]', "repetidos"),
        ('coins = ["BTC", "xyz:TSLA"]', "primeiro dex"),
        ('coins = ["BTC", "@107"]', "primeiro dex"),
        ("coins = []", "não vazia"),
        ('coins = ["BTC"]\nextra = 1', "única chave"),
        ("coins = [", "TOML"),
    ],
)
def test_bad_collector_list_is_config_error(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "ativos.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_assets(path)
    with pytest.raises(ConfigError, match="não existe"):
        load_assets(tmp_path / "nada.toml")


# ─── CLI ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def data_env(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    clean_env.setenv("COPYLAB_DATA_DIR", str(tmp_path / "dados"))
    clean_env.chdir(REPO_ROOT)
    yield tmp_path / "dados"


@pytest.fixture
def fake_exchange(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, object]]]:
    """Servidor falso: guarda as assinaturas e manda um livro de BTC por assinatura."""
    received: list[dict[str, object]] = []

    def handler(ws: ServerConnection) -> None:
        for message in ws:
            payload = json.loads(message)
            if payload.get("method") == "subscribe":
                received.append(payload["subscription"])
                ws.send(BOOK)

    # O servidor loga numa thread própria, depois que o `CliRunner` já fechou o stdout que a
    # CLI deu ao logging; um logger que não propaga evita escrever num arquivo fechado.
    quiet = logging.getLogger("tests.fake_exchange")
    quiet.propagate = False
    quiet.addHandler(logging.NullHandler())
    with serve(handler, "127.0.0.1", 0, logger=quiet) as server:
        port = server.socket.getsockname()[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setattr(cli, "WS_URL", f"ws://127.0.0.1:{port}")
        yield received
        server.shutdown()


@pytest.mark.unit
def test_collect_records_then_status_and_compact_run(
    data_env: Path, fake_exchange: list[dict[str, object]], tmp_path: Path
) -> None:
    """`collect` grava por um segundo contra o servidor falso; `status` lê os arquivos."""
    assets = tmp_path / "ativos.toml"
    assets.write_text('coins = ["BTC", "ETH"]', encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(cli.app, ["collect", "--assets", str(assets), "--duration-seconds", "1"])
    assert result.exit_code == 0, result.output
    assert len(fake_exchange) == 6
    channels = {(r.coin, r.channel) for r in SegmentStore(data_env).segments()}
    assert ("BTC", "book") in channels
    assert ("_events", "events") in channels

    status = runner.invoke(cli.app, ["collect", "status", "--assets", str(assets)])
    assert status.exit_code == 0, status.output
    assert "collector.status.asset" in status.output
    assert "collector.status.disk" in status.output

    compact = runner.invoke(cli.app, ["collect", "compact"])
    assert compact.exit_code == 0, compact.output
    assert "collector.compact.nothing_to_do" in compact.output  # o dia de hoje não fechou


@pytest.mark.unit
def test_compacting_today_is_refused(data_env: Path) -> None:
    from copylab.timeutil import iso

    today = iso(clock.now())[:10]
    result = CliRunner().invoke(cli.app, ["collect", "compact", "--day", today])
    assert result.exit_code == 1
    assert "ainda não terminou" in result.output


@pytest.mark.unit
def test_status_prints_coverage_per_utc_day(
    data_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`collect status` mostra, por ativo, a cobertura de cada dia UTC.

    BTC com um segmento ainda em escrita no dia 2026-10-06 (D0 = 1.791.244.800.000 ms): o
    retrato em D0 + 100 é descartado, e o livro vem em D0 + 1 s e D0 + 5 s. Agora, D0 + 8 s:
    o dia é o de hoje, incompleto, com 8 s decorridas = 0,0022 h. Antes do primeiro livro
    foi 1 s que não se gravou, e não há lacuna: cobertura do dia = 1 - 1.000 / 8.000 =
    87,5%.
    """
    d0 = 1_791_244_800_000
    conn = d0 + 100
    writer = SegmentStore(data_env).open_writer("BTC", "book", Ms(d0), Ms(conn))
    for recv, time in ((conn + 5, conn), (d0 + 1_300, d0 + 1_000), (d0 + 5_300, d0 + 5_000)):
        data = {"coin": "BTC", "time": time, "levels": [[], []], "fast": True}
        message = {"channel": "l2Book", "data": data}
        writer.append(Record(Ms(recv), Ms(conn), json.dumps(message).encode()))
    writer.flush()
    monkeypatch.setattr(clock, "now", lambda: Ms(d0 + 8_000))
    assets = tmp_path / "ativos.toml"
    assets.write_text('coins = ["BTC"]', encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["collect", "status", "--assets", str(assets)])
    assert result.exit_code == 0, result.output
    line = next(x for x in result.output.splitlines() if "collector.status.days" in x)
    assert "coin=BTC" in line
    assert "today=2026-10-06" in line
    assert "today_pct=87.5" in line


@pytest.mark.unit
def test_missing_data_dir_fails_with_actionable_message(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RF-CLI-01 CA-01.2: código de saída diferente de zero e mensagem que diz o que fazer."""
    clean_env.chdir(REPO_ROOT)
    for args in (["collect", "status"], ["collect", "compact"]):
        result = CliRunner().invoke(cli.app, args)
        assert result.exit_code == 1, args
        assert "COPYLAB_DATA_DIR" in result.output
