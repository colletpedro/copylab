"""Parâmetros pré-registrados, carregados de ``preregistro/parametros.toml`` (design §3.9).

O arquivo é a única fonte de parâmetro pré-registrado (RF-SEL-02 CA-02.2): nenhum limiar
aparece como literal no código. :func:`load_params` o lê num modelo imutável, e
:meth:`Params.canonical_hash` dá o hash dos valores carregados, que o congelamento grava
e a avaliação confere (RF-SEL-05).

Valor ausente, chave desconhecida, tipo errado ou contagem de dias que não bate com as
datas são :class:`~copylab.exceptions.ConfigError`. Chave desconhecida é erro, e não é
ignorada, porque um erro de digitação faria o código usar outro valor sem aviso.
"""

import hashlib
import json
import math
import tomllib
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from copylab.exceptions import ConfigError
from copylab.timeutil import MS_PER_DAY, MS_PER_HOUR, MS_PER_SECOND, Ms, from_date

__all__ = ["DEFAULT_PATH", "Params", "load_params"]

#: Caminho do arquivo, relativo à raiz do repositório.
DEFAULT_PATH: Final = Path("preregistro/parametros.toml")

_HASH_MAGIC: Final = "copylab/params-hash/v1\n"

Day = Annotated[Ms, BeforeValidator(from_date)]
"""Uma data do TOML, convertida na meia-noite UTC dela."""


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Universe(_Section):
    max_assets: StrictInt
    min_candidate_fills: StrictInt
    proxy_max_deviation_p95_bps: StrictFloat
    proxy_max_level_bps: StrictFloat


class RouteA(_Section):
    selection_first_day: Day
    selection_last_day: Day
    selection_days: StrictInt
    cutoff: Day
    evaluation_first_day: Day
    evaluation_last_day: Day
    evaluation_days: StrictInt

    @model_validator(mode="after")
    def _days_add_up(self) -> Self:
        """As datas escritas na spec e as contagens de dias têm de dizer a mesma coisa."""
        checks = {
            "selection_days": (self.selection_start, self.selection_end, self.selection_days),
            "evaluation_days": (self.evaluation_start, self.evaluation_end, self.evaluation_days),
        }
        for key, (start, end, days) in checks.items():
            if (end - start) != days * MS_PER_DAY:
                raise ConfigError(
                    f"route_a.{key} = {days}, mas as datas cobrem {(end - start) // MS_PER_DAY}."
                )
        if self.selection_end != self.cutoff or self.evaluation_start != self.cutoff:
            raise ConfigError(
                "route_a: a seleção tem de terminar no corte e a avaliação, começar nele."
            )
        return self

    @property
    def selection_start(self) -> Ms:
        return self.selection_first_day

    @property
    def selection_end(self) -> Ms:
        """Fim exclusivo da janela de seleção: a meia-noite seguinte ao último dia."""
        return Ms(self.selection_last_day + MS_PER_DAY)

    @property
    def evaluation_start(self) -> Ms:
        return self.evaluation_first_day

    @property
    def evaluation_end(self) -> Ms:
        """Fim exclusivo da janela de avaliação: a meia-noite seguinte ao último dia."""
        return Ms(self.evaluation_last_day + MS_PER_DAY)


class RouteB(_Section):
    selection_days: StrictInt
    evaluation_days: StrictInt
    min_book_coverage_pct: StrictFloat
    max_extension_days: StrictInt


class LiveWeek(_Section):
    days: StrictInt
    max_extension_days: StrictInt


class PilotGate(_Section):
    max_week_loss_pct: StrictFloat
    max_source_difference_pp: StrictFloat
    max_real_capital_usd: StrictFloat


class Pool(_Section):
    block_size: StrictInt
    seed: StrictInt
    min_eligible: StrictInt


class Ingestion(_Section):
    max_fills_per_wallet: StrictInt


class Reconciliation(_Section):
    pnl_tolerance_bps: StrictFloat


class Cohort(_Section):
    max_k: StrictInt
    capital_per_wallet_usd: StrictFloat
    min_k: StrictInt

    def k_for(self, capital_usd: float) -> int:
        """``min(max_k, ⌊capital / capital_por_carteira⌋)``, com mínimo ``min_k`` (D14)."""
        return max(
            self.min_k, min(self.max_k, math.floor(capital_usd / self.capital_per_wallet_usd))
        )


class Capital(_Section):
    primary_usd: StrictFloat
    grid_usd: tuple[StrictFloat, ...]
    grid_k: tuple[StrictInt, ...]


class Delay(_Section):
    primary_s: StrictInt
    grid_s: tuple[StrictInt, ...]

    @model_validator(mode="after")
    def _primary_in_grid(self) -> Self:
        if self.primary_s not in self.grid_s:
            raise ConfigError(
                f"delay.primary_s = {self.primary_s} não está na grade {self.grid_s}."
            )
        return self

    @property
    def primary_ms(self) -> int:
        return self.primary_s * MS_PER_SECOND

    @property
    def grid_ms(self) -> tuple[int, ...]:
        return tuple(s * MS_PER_SECOND for s in self.grid_s)


class Slippage(_Section):
    floor_bps: StrictFloat
    min_measured_days: StrictInt
    sensitivity_multipliers: tuple[StrictFloat, ...]


class Fees(_Section):
    taker_bps: StrictFloat


class Mirror(_Section):
    leverage_cap: StrictFloat
    peak_exposure: StrictFloat
    min_order_usd: StrictFloat


class Ranking(_Section):
    metric: Literal["daily_sharpe"]


class Control(_Section):
    cohorts: StrictInt
    seed: StrictInt


class Metrics(_Section):
    annualization_days: StrictInt


class BookRecord(_Section):
    max_book_silence_s: StrictInt
    cost_min_day_coverage_pct: StrictFloat

    @property
    def max_book_silence_ms(self) -> int:
        return self.max_book_silence_s * MS_PER_SECOND


class Filters(_Section):
    f1_role: StrictStr
    f2_min_account_value_usd: StrictFloat
    f4_min_closed_episodes: StrictInt
    f5_blocks: StrictInt
    f5_block_days: StrictInt
    f5_min_active_blocks: StrictInt
    f6_min_median_duration_h: StrictFloat
    f6_max_median_duration_days: StrictFloat
    f7_min_taker_opening_pct: StrictFloat
    f8_max_median_open_perps: StrictInt
    f9_min_universe_notional_pct: StrictFloat
    f10_max_liquidated_fills: StrictInt

    @property
    def f6_min_median_duration_ms(self) -> float:
        return self.f6_min_median_duration_h * MS_PER_HOUR

    @property
    def f6_max_median_duration_ms(self) -> float:
        return self.f6_max_median_duration_days * MS_PER_DAY


class BinanceException(_Section):
    coin: StrictStr
    symbol: StrictStr


class Binance(_Section):
    quote: StrictStr
    k_prefix: StrictStr
    k_replacement: StrictStr
    exceptions: tuple[BinanceException, ...]

    @model_validator(mode="after")
    def _one_exception_per_coin(self) -> Self:
        coins = [e.coin for e in self.exceptions]
        if len(coins) != len(set(coins)):
            raise ConfigError(f"binance.exceptions repete ativo: {sorted(coins)}.")
        return self

    def symbol(self, coin: str) -> str:
        """Nome do perpétuo na Binance para o ativo ``coin`` da Hyperliquid (design §3.3).

        A exceção listada vale primeiro. Senão, o prefixo ``k`` vira ``1000`` (``kPEPE`` é
        ``1000PEPEUSDT``), e o resto ganha o sufixo da cotação.
        """
        for exception in self.exceptions:
            if exception.coin == coin:
                return exception.symbol
        if coin.startswith(self.k_prefix) and len(coin) > len(self.k_prefix):
            coin = self.k_replacement + coin[len(self.k_prefix) :]
        return coin + self.quote


class Params(_Section):
    """Todos os valores de §7.2 e §7.3 dos requisitos, os limiares do livro gravado que o
    design 1.1 (§3.9) põe aqui e a regra de nomes da Binance."""

    universe: Universe
    route_a: RouteA
    route_b: RouteB
    live_week: LiveWeek
    pilot_gate: PilotGate
    pool: Pool
    ingestion: Ingestion
    reconciliation: Reconciliation
    cohort: Cohort
    capital: Capital
    delay: Delay
    slippage: Slippage
    fees: Fees
    mirror: Mirror
    ranking: Ranking
    control: Control
    metrics: Metrics
    book_record: BookRecord
    filters: Filters
    binance: Binance

    @model_validator(mode="after")
    def _capital_grid_follows_k_rule(self) -> Self:
        """A grade escreve K por extenso; ela tem de bater com a fórmula de D14."""
        capital = self.capital
        expected = tuple(self.cohort.k_for(c) for c in capital.grid_usd)
        if capital.grid_k != expected:
            raise ConfigError(
                f"capital.grid_k = {capital.grid_k}, mas a fórmula de cohort dá {expected}."
            )
        if capital.primary_usd not in capital.grid_usd:
            raise ConfigError(f"capital.primary_usd = {capital.primary_usd} não está na grade.")
        return self

    def canonical_hash(self) -> str:
        """SHA-256 dos valores carregados, em JSON canônico.

        Chaves em ordem, sem espaços, datas já em ``Ms``. Comentário, ordem das chaves no
        arquivo e formatação não entram; qualquer valor entra.
        """
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256((_HASH_MAGIC + canonical).encode()).hexdigest()


def _describe(error: Any) -> str:
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}"


def load_params(path: Path = DEFAULT_PATH) -> Params:
    """Lê e valida o arquivo de parâmetros.

    Raises:
        ConfigError: arquivo ausente, TOML inválido, valor ausente, chave desconhecida,
            tipo errado ou valores incoerentes entre si.
    """
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Arquivo de parâmetros {path} não existe.") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Arquivo de parâmetros {path} não é TOML válido: {exc}.") from exc
    try:
        return Params.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(_describe(error) for error in exc.errors())
        raise ConfigError(f"Parâmetros inválidos em {path}. {problems}") from exc
