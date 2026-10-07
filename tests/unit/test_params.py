"""Parâmetros pré-registrados (design §3.9, T-005).

`test_parameter_file_holds_every_value_of_7_2_and_7_3` confere o arquivo real contra a
spec, valor por valor: é a segunda transcrição, feita de novo a partir dos requisitos
1.3, e não copiada do TOML. As janelas em `Ms` são contadas à mão a partir do corte da
Rota A, 2026-09-01 = 1.788.220.800.000 ms (derivação em `test_timeutil.py`), com
1 dia = 86.400.000 ms:

- início da seleção, 2026-07-01: 62 dias antes do corte.
  62 * 86.400.000 = 5.356.800.000; 1.788.220.800.000 - 5.356.800.000 = 1.782.864.000.000.
- fim da avaliação, 2026-10-01 (exclusivo): 30 dias depois do corte.
  30 * 86.400.000 = 2.592.000.000; 1.788.220.800.000 + 2.592.000.000 = 1.790.812.800.000.

Os outros testes trabalham sobre cópias do arquivo real com uma alteração cada.

Prova de dente, feita à mão em 2026-10-07 e restaurada:

- `f9_min_universe_notional_pct` de 50.0 para 40.0 no arquivo real: falhou
  `test_parameter_file_holds_every_value_of_7_2_and_7_3`.
- `sort_keys=False` em `canonical_hash`: passou `test_hash_ignores_comments_order_and_formatting`,
  porque a ordem do dump é a dos campos no modelo e não a do arquivo, e falhou
  `test_hash_is_the_documented_canonical_json`, que existe por causa disso.
"""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from copylab.exceptions import ConfigError
from copylab.params import DEFAULT_PATH, Params, load_params

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_FILE = REPO_ROOT / DEFAULT_PATH


def variant(tmp_path: Path, old: str, new: str) -> Path:
    """Cópia do arquivo real com uma substituição, que precisa acontecer exatamente uma vez."""
    text = REAL_FILE.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} aparece {text.count(old)} vezes"
    path = tmp_path / "parametros.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def params() -> Params:
    return load_params(REAL_FILE)


@pytest.mark.unit
def test_parameter_file_holds_every_value_of_7_2_and_7_3(params: Params) -> None:
    # §7.2 Universo: no máximo 20 ativos, 2.000 fills, desvio 10 bps, nível 50 bps.
    assert params.universe.max_assets == 20
    assert params.universe.min_candidate_fills == 2_000
    assert params.universe.proxy_max_deviation_p95_bps == pytest.approx(10.0)
    assert params.universe.proxy_max_level_bps == pytest.approx(50.0)

    # §7.2 Rota A: seleção [2026-07-01, 2026-09-01), corte 2026-09-01,
    # avaliação [2026-09-01, 2026-10-01). Ms na docstring do módulo.
    route_a = params.route_a
    assert route_a.selection_start == 1_782_864_000_000
    assert route_a.cutoff == route_a.selection_end == 1_788_220_800_000
    assert route_a.evaluation_start == 1_788_220_800_000
    assert route_a.evaluation_end == 1_790_812_800_000
    assert (route_a.selection_days, route_a.evaluation_days) == (62, 30)

    # §7.2 Rota B: 62 dias de seleção, 30 de avaliação, 95%, extensão de 15 dias.
    assert params.route_b.selection_days == 62
    assert params.route_b.evaluation_days == 30
    assert params.route_b.min_book_coverage_pct == pytest.approx(95.0)
    assert params.route_b.max_extension_days == 15
    # §7.2 Semana ao vivo: 7 dias, extensão de 3.
    assert (params.live_week.days, params.live_week.max_extension_days) == (7, 3)

    # §7.2 Gate do piloto: perda de 10%, diferença de 1 pp, capital real de US$ 50.
    assert params.pilot_gate.max_week_loss_pct == pytest.approx(10.0)
    assert params.pilot_gate.max_source_difference_pp == pytest.approx(1.0)
    assert params.pilot_gate.max_real_capital_usd == pytest.approx(50.0)

    # §7.2 Pool: blocos de 3.000, semente 20261005, até 20 elegíveis.
    assert (params.pool.block_size, params.pool.seed, params.pool.min_eligible) == (
        3_000,
        20_261_005,
        20,
    )
    # §7.2 Teto de fills: 20.000. Tolerância de PnL: 10 bps.
    assert params.ingestion.max_fills_per_wallet == 20_000
    assert params.reconciliation.pnl_tolerance_bps == pytest.approx(10.0)

    # §7.2 K = min(5, ⌊capital / 50⌋), mínimo 1. Capital primário 50; grade 50/100/500
    # com K = 1/2/5.
    assert params.cohort.max_k == 5
    assert params.cohort.capital_per_wallet_usd == pytest.approx(50.0)
    assert params.cohort.min_k == 1
    assert params.capital.primary_usd == pytest.approx(50.0)
    assert params.capital.grid_usd == pytest.approx((50.0, 100.0, 500.0))
    assert params.capital.grid_k == (1, 2, 5)

    # §7.2 Δ: primário 5 s; grade 1/5/30 s.
    assert params.delay.primary_s == 5
    assert params.delay.grid_s == (1, 5, 30)
    assert params.delay.primary_ms == 5_000
    assert params.delay.grid_ms == (1_000, 5_000, 30_000)

    # §7.2 Slippage (Rota A): o maior entre 2 bps e a mediana medida em ao menos 3 dias;
    # sensibilidade zero e o dobro.
    assert params.slippage.floor_bps == pytest.approx(2.0)
    assert params.slippage.min_measured_days == 3
    assert params.slippage.sensitivity_multipliers == pytest.approx((0.0, 2.0))

    # §7.2 Taxa 4,5 bps; teto 1,0; pico 1,0; ordem mínima US$ 10.
    assert params.fees.taker_bps == pytest.approx(4.5)
    assert params.mirror.leverage_cap == pytest.approx(1.0)
    assert params.mirror.peak_exposure == pytest.approx(1.0)
    assert params.mirror.min_order_usd == pytest.approx(10.0)

    # §7.2 Ranking pelo Sharpe diário; 1.000 coortes de controle, semente 20261005; √365.
    assert params.ranking.metric == "daily_sharpe"
    assert (params.control.cohorts, params.control.seed) == (1_000, 20_261_005)
    assert params.metrics.annualization_days == 365

    # §7.3 F1 a F10 (F3 usa o teto de fills e a tolerância de PnL, conferidos acima).
    f = params.filters
    assert f.f1_role == "user"
    assert f.f2_min_account_value_usd == pytest.approx(30_000.0)
    assert f.f4_min_closed_episodes == 20
    assert (f.f5_blocks, f.f5_block_days, f.f5_min_active_blocks) == (8, 7, 6)
    # F6 entre 1 hora (3.600.000 ms) e 7 dias (7 * 86.400.000 = 604.800.000 ms).
    assert f.f6_min_median_duration_ms == pytest.approx(3_600_000)
    assert f.f6_max_median_duration_ms == pytest.approx(604_800_000)
    assert f.f7_min_taker_opening_pct == pytest.approx(50.0)
    assert f.f8_max_median_open_perps == 3
    assert f.f9_min_universe_notional_pct == pytest.approx(50.0)
    assert f.f10_max_liquidated_fills == 0

    # Design §3.3: USDT, k por 1000, sem exceções listadas.
    assert params.binance.quote == "USDT"
    assert params.binance.exceptions == ()


@pytest.mark.unit
def test_params_are_immutable(params: Params) -> None:
    with pytest.raises(ValidationError):
        params.fees.taker_bps = 0.0  # type: ignore[misc]  # o teste é a atribuição proibida
    with pytest.raises(ValidationError):
        params.fees = params.fees  # type: ignore[misc]
    assert isinstance(params.capital.grid_usd, tuple)


@pytest.mark.unit
def test_binance_name_rule(params: Params) -> None:
    """Os casos da verificação: BTC, HYPE, e os dois com prefixo k (RF-VER-05 CA-05.4)."""
    assert params.binance.symbol("BTC") == "BTCUSDT"
    assert params.binance.symbol("HYPE") == "HYPEUSDT"
    assert params.binance.symbol("kPEPE") == "1000PEPEUSDT"
    assert params.binance.symbol("kBONK") == "1000BONKUSDT"
    # Maiúsculo não é o prefixo; "k" sozinho não tem o que trocar.
    assert params.binance.symbol("KAITO") == "KAITOUSDT"
    assert params.binance.symbol("k") == "kUSDT"


@pytest.mark.unit
def test_binance_exception_wins_over_the_rule(tmp_path: Path) -> None:
    path = variant(
        tmp_path,
        "exceptions = []",
        '[[binance.exceptions]]\ncoin = "kPEPE"\nsymbol = "PEPEUSDT"',
    )
    binance = load_params(path).binance
    assert binance.symbol("kPEPE") == "PEPEUSDT"
    assert binance.symbol("kBONK") == "1000BONKUSDT"


@pytest.mark.unit
def test_duplicate_binance_exception_is_config_error(tmp_path: Path) -> None:
    entry = '[[binance.exceptions]]\ncoin = "X"\nsymbol = "XUSDT"\n'
    path = variant(tmp_path, "exceptions = []", entry + entry)
    with pytest.raises(ConfigError, match="repete ativo"):
        load_params(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("capital", "k"),
    # ⌊49/50⌋ = 0, sobe ao mínimo 1; ⌊100/50⌋ = 2; ⌊1000/50⌋ = 20, cai ao máximo 5.
    [(49.0, 1), (50.0, 1), (100.0, 2), (149.99, 2), (500.0, 5), (1_000.0, 5)],
)
def test_k_follows_d14(params: Params, capital: float, k: int) -> None:
    assert params.cohort.k_for(capital) == k


# ─── Hash canônico ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_hash_ignores_comments_order_and_formatting(tmp_path: Path, params: Params) -> None:
    text = REAL_FILE.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    sections = body.split("\n[")
    # Mesmas seções, em ordem inversa, sem comentários e com espaços a mais.
    reordered = "\n[".join([sections[0], *reversed(sections[1:])]).replace(" = ", "   =   ")
    path = tmp_path / "parametros.toml"
    path.write_text(reordered, encoding="utf-8")
    assert load_params(path).canonical_hash() == params.canonical_hash()


@pytest.mark.unit
def test_hash_is_the_documented_canonical_json(params: Params) -> None:
    """SHA-256 de `copylab/params-hash/v1` e do JSON com chaves em ordem e sem espaços.

    A ordem das chaves é a alfabética, e não a dos campos no código: reordenar campos
    do modelo numa refatoração não pode mudar o hash de um congelamento.
    """
    canonical = json.dumps(
        params.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    expected = hashlib.sha256(("copylab/params-hash/v1\n" + canonical).encode()).hexdigest()
    assert params.canonical_hash() == expected


@pytest.mark.unit
def test_hash_changes_with_any_value(tmp_path: Path, params: Params) -> None:
    path = variant(tmp_path, "taker_bps = 4.5", "taker_bps = 4.6")
    assert load_params(path).canonical_hash() != params.canonical_hash()


@pytest.mark.unit
def test_integer_written_for_a_float_has_the_same_value_and_hash(
    tmp_path: Path, params: Params
) -> None:
    """`10` e `10.0` num campo de dinheiro são o mesmo valor."""
    path = variant(tmp_path, "min_order_usd = 10.0", "min_order_usd = 10")
    assert load_params(path).canonical_hash() == params.canonical_hash()


# ─── Erros ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("taker_bps = 4.5\n", "", "fees.taker_bps"),  # ausente
        ("max_assets = 20", 'max_assets = "20"', "universe.max_assets"),  # texto
        ("max_assets = 20", "max_assets = 20.0", "universe.max_assets"),  # float por int
        ("min_k = 1", "min_k = true", "cohort.min_k"),  # booleano por int
        ('f1_role = "user"', "f1_role = 1", "filters.f1_role"),
        ('metric = "daily_sharpe"', 'metric = "sortino"', "ranking.metric"),
        ("taker_bps = 4.5", "taker_bps = 4.5\ntaker_bsp = 4.5", "taker_bsp"),  # chave a mais
        ("[fees]", "[taxas]", "taxas"),  # seção desconhecida
    ],
)
def test_missing_or_mistyped_value_is_config_error(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_params(variant(tmp_path, old, new))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "selection_last_day = 2026-08-31\nselection_days = 62",
            "selection_last_day = 2026-08-31\nselection_days = 61",
            "selection_days = 61",
        ),
        ("evaluation_last_day = 2026-09-30", "evaluation_last_day = 2026-09-29", "cobrem 29"),
        ("cutoff = 2026-09-01", "cutoff = 2026-08-31", "começar"),
        ("grid_k = [1, 2, 5]", "grid_k = [1, 2, 10]", "grid_k"),
        ("primary_usd = 50.0", "primary_usd = 75.0", "primary_usd"),
        ("primary_s = 5", "primary_s = 10", "primary_s"),
        ("cutoff = 2026-09-01", 'cutoff = "2026-09-01"', "sem hora"),
        ("cutoff = 2026-09-01", "cutoff = 2026-09-01T00:00:00Z", "sem hora"),
    ],
)
def test_incoherent_values_are_config_error(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_params(variant(tmp_path, old, new))


@pytest.mark.unit
def test_missing_or_broken_file_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="não existe"):
        load_params(tmp_path / "nada.toml")
    broken = tmp_path / "quebrado.toml"
    broken.write_text("[fees\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="não é TOML"):
        load_params(broken)
