"""`copylab costs measure` (T-062; RF-COL-05 CA-05.2). Dados sintéticos, em tabelas pequenas.

Os dias são os UTC 20.000 a 20.004 (``D0`` = 20.000 x 86.400.000 ms = 2024-10-04T00:00Z). O
dia 20.004 é "hoje" nos testes (agora = 20.004 às 12:00:05), e não entra na medida.

**BTC** tem livro desde o início do dia 20.000. Cobertura de cada dia, no relógio da corretora:

    20.000  sem lacuna                                  100%  -> qualifica
    20.001  lacuna de 5.184.000 ms (6% de 86.400.000)    94%  -> não qualifica
    20.002  lacuna de 4.320.000 ms (5% exatos)            95%  -> qualifica (limiar inclusivo)
    20.003  sem lacuna                                  100%  -> qualifica

Os três primeiros que qualificam são 20.000, 20.002 e 20.003, não seguidos. Uma observação por
dia (compra + venda = 200 em todas, então o meio-spread é (venda - compra) / 200 x 10^4, exato
em ponto flutuante), com o peso de cada uma sendo o tempo dela até o fim do dia, menos a lacuna:

    20.000  50 bps em +66.400.000        peso 86.400.000 - 66.400.000                 = 20.000.000
    20.002  25 bps em +40.000.000        peso 46.400.000 - lacuna de 4.320.000 dentro = 42.080.000
    20.003  12,5 bps em +24.320.000      peso 86.400.000 - 24.320.000                 = 62.080.000

Total 124.160.000; metade 62.080.000. Em ordem de valor, o 12,5 já acumula 62.080.000, que é a
metade (limiar inclusivo): a mediana ponderada inferior é 12,5 bps. Sem descontar a lacuna, o
peso do 25 seria 46.400.000, o total 128.480.000, a metade 64.240.000, e a mediana seria 25.

**ETH** tem livro desde o início do dia 20.002, sem lacuna: só 20.002 e 20.003 qualificam (20.004
é hoje), e falta 1 dia.

Prova de dente, feita à mão em 2026-10-13 e restaurada, uma mutação por vez (as mutações de
cada teste estão na docstring dele).
"""

import json
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from copylab import cli, clock
from copylab.storage import ParquetStore, Span
from copylab.storage.tables import BBO, BOOK, GAPS, SCHEMAS
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, Ms, day_start

REPO_ROOT = Path(__file__).resolve().parents[2]
DAY0 = 20_000
NOW = Ms(day_start(DAY0 + 4) + 12 * MS_PER_HOUR + 5_000)
QUOTES = {50.0: (99.5, 100.5), 25.0: (99.75, 100.25), 12.5: (99.875, 100.125)}


@pytest.fixture
def data_env(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    clean_env.setenv("COPYLAB_DATA_DIR", str(tmp_path / "dados"))
    clean_env.chdir(REPO_ROOT)
    clean_env.setattr(clock, "now", lambda: NOW)
    yield tmp_path / "dados"


def put_book(store: ParquetStore, coin: str, times: list[int]) -> None:
    """Linhas do livro nos instantes dados (só as colunas de tempo importam para o status)."""
    for t in times:
        row = dict.fromkeys(SCHEMAS[BOOK])
        row.update(time_ms=t, recv_ms=t, conn_ms=t - 1_000)
        day = t // MS_PER_DAY
        span = Span(day_start(day), day_start(day + 1))
        frame = pl.DataFrame([row], schema=SCHEMAS[BOOK], orient="row")
        store.write(BOOK, (coin, str(day)), frame, span=span, instant="recv_ms")


def put_bbo(
    store: ParquetStore, coin: str, day: int, half_spread: float, offset_ms: int = 0
) -> None:
    bid, ask = QUOTES[half_spread]
    t = day_start(day) + offset_ms
    row = dict.fromkeys(SCHEMAS[BBO])
    row.update(
        time_ms=t, recv_ms=t, conn_ms=t - 1_000, bid_px=bid, bid_sz=1.0, ask_px=ask, ask_sz=1.0
    )
    frame = pl.DataFrame([row], schema=SCHEMAS[BBO], orient="row")
    store.write(
        BBO,
        (coin, str(day)),
        frame,
        span=Span(day_start(day), day_start(day + 1)),
        instant="recv_ms",
    )


def put_gaps(store: ParquetStore, coin: str, spans: list[tuple[int, int]]) -> None:
    rows = [{"start_ms": a, "end_ms": b, "reason": "silence"} for a, b in spans]
    frame = pl.DataFrame(rows, schema=SCHEMAS[GAPS], orient="row")
    store.write(GAPS, (coin,), frame, span=Span(Ms(0), Ms(2**62)), instant="start_ms")


def build(data: Path, *, eth_first_day: int = DAY0 + 2) -> None:
    store = ParquetStore(data)
    last = day_start(DAY0 + 4) + 12 * MS_PER_HOUR
    put_book(store, "BTC", [day_start(DAY0), last])
    put_book(store, "ETH", [day_start(eth_first_day), last])
    put_gaps(
        store,
        "BTC",
        [
            (day_start(DAY0 + 1) + MS_PER_HOUR, day_start(DAY0 + 1) + MS_PER_HOUR + 5_184_000),
            (day_start(DAY0 + 2) + 50_000_000, day_start(DAY0 + 2) + 54_320_000),
        ],
    )
    put_gaps(store, "ETH", [])
    for day, value, offset in (
        (DAY0, 50.0, 66_400_000),
        (DAY0 + 2, 25.0, 40_000_000),
        (DAY0 + 3, 12.5, 24_320_000),
    ):
        put_bbo(store, "BTC", day, value, offset)
    for day in (DAY0 + 1, DAY0 + 2, DAY0 + 3):
        put_bbo(store, "ETH", day, 12.5)


def run(tmp_path: Path, costs: Path) -> tuple[int, str]:
    assets = tmp_path / "ativos.toml"
    assets.write_text('coins = ["BTC", "ETH"]', encoding="utf-8")
    result = CliRunner().invoke(
        cli.app, ["costs", "measure", "--assets", str(assets), "--costs", str(costs)]
    )
    return result.exit_code, result.output


@pytest.mark.unit
def test_half_spread_median_is_written_once_to_cost_parameters(
    data_env: Path, tmp_path: Path
) -> None:
    """RF-COL-05 CA-05.2: o primeiro `costs measure` mede BTC nos 3 primeiros dias que
    qualificam (os não seguidos 20.000, 20.002 e 20.003), grava o arquivo e diz que falta 1 dia
    para ETH; rodar de novo não mexe no arquivo.

    BTC: 12,5 bps, pela conta do cabeçalho do módulo. O dia 20.001, com 94% de cobertura, e o de
    hoje ficam de fora; o 20.002, com exatamente 95%, entra.

    Mutações: dia de hoje aceito (`if d.complete` trocado por `if True`): caiu. Limiar de
    cobertura exclusivo (`+ 1` no lado direito da comparação): o dia 20.002, de 95% exatos, saiu,
    só 2 dias qualificaram e BTC não foi medido; o teste caiu. Cobertura sem descontar a lacuna
    (`d.gap_ms` fora da conta): o dia 20.001 entrou e os dias usados mudaram; caiu. Sem as
    lacunas na conta do meio-spread (`()` no lugar delas), a mediana saiu 25: caiu.
    """
    build(data_env)
    costs = tmp_path / "custos.json"

    code, output = run(tmp_path, costs)

    assert code == 0, output
    written = json.loads(costs.read_text(encoding="utf-8"))
    assert list(written) == ["BTC"]
    assert written["BTC"]["half_spread_bps"] == pytest.approx(12.5)
    assert written["BTC"]["days"] == ["2024-10-04", "2024-10-06", "2024-10-07"]
    assert len(written["BTC"]["data_hash"]) == 64
    assert "coin=ETH" in output
    assert "days_missing=1" in output

    before = costs.read_bytes()
    code, output = run(tmp_path, costs)
    assert code == 0, output
    assert costs.read_bytes() == before


@pytest.mark.unit
def test_cost_file_adds_assets_and_never_changes_existing_value(
    data_env: Path, tmp_path: Path
) -> None:
    """RF-COL-05 CA-05.2: ativo que falta entra, e o valor gravado de BTC fica como estava,
    mesmo que o dado de hoje desse outro número (12,5 bps).

    ETH com livro desde 20.001 qualifica em 20.001, 20.002 e 20.003, sem lacuna, e o único
    valor é 12,5 bps.

    Mutação: `wanted` com todos os ativos da lista, inclusive os já gravados: BTC era medido
    outra vez e `add_new` o recusava, o comando saía com 1, e o teste caiu.
    """
    build(data_env, eth_first_day=DAY0 + 1)
    costs = tmp_path / "custos.json"
    original = {
        "BTC": {
            "half_spread_bps": 99.0,
            "days": ["2024-10-04"],
            "data_hash": "cd" * 32,
            "skipped_observations": 0,
        }
    }
    costs.write_text(json.dumps(original), encoding="utf-8")

    code, output = run(tmp_path, costs)

    assert code == 0, output
    written = json.loads(costs.read_text(encoding="utf-8"))
    assert written["BTC"] == original["BTC"]
    assert written["ETH"]["half_spread_bps"] == pytest.approx(12.5)
    assert written["ETH"]["days"] == ["2024-10-05", "2024-10-06", "2024-10-07"]


@pytest.mark.unit
def test_qualifying_day_without_compacted_bbo_asks_for_compaction(
    data_env: Path, tmp_path: Path
) -> None:
    """Um dia com cobertura mas sem `bbo` compactado é erro de dado (código 1), com o remédio."""
    build(data_env)
    # Apaga o bbo do dia 20.003 de BTC: o status ainda acha o dia coberto pelo livro.
    for path in (data_env / "bbo").rglob("*"):
        if path.is_file() and f"{DAY0 + 3}" in str(path) and "BTC" in str(path):
            path.unlink()
    code, output = run(tmp_path, tmp_path / "custos.json")
    assert code == 1
    assert "collect compact" in output
    assert not (tmp_path / "custos.json").exists()
