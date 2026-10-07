"""Diretório de dados, partições, escrita atômica e janelas congeladas (ADR-0006, design §3.2).

Os instantes são pequenos e redondos, em ms, para a conta caber de cabeça. Todas as
escritas usam a coluna `t` como instante.

Prova de dente, feita à mão em 2026-10-07 e restaurada, uma mutação por vez em
`copylab.storage.files`:

- `test_interrupted_write_leaves_previous_table_intact`: `_replace` gravando direto em
  `path`, sem temporário. O teste falhou: a queda deixou lixo no lugar da partição
  anterior, a limpeza o apagou, e a leitura levantou "Partição ('p',) ... não existe".
- `test_frozen_rows_are_never_rewritten`: `protected = ()` (nenhum trecho protegido).
  Falharam este e `test_first_write_inside_frozen_window_is_accepted`: a linha alterada
  e a linha nova entraram, e a removida sumiu.
- `protected` sem a interseção com `collected` (toda a janela congelada protegida,
  gravada ou não): falhou só `test_first_write_inside_frozen_window_is_accepted`, porque
  a primeira coleta de um trecho congelado seria recusada.
"""

from pathlib import Path

import polars as pl
import pytest

from copylab.config import Settings
from copylab.exceptions import ConfigError, DataError
from copylab.storage import ParquetStore, Span
from copylab.timeutil import Ms

SCHEMA = {"t": pl.Int64, "id": pl.String, "px": pl.Float64}


def rows(*items: tuple[int, str, float]) -> pl.DataFrame:
    return pl.DataFrame(list(items), schema=SCHEMA, orient="row")


def span(start: int, end: int) -> Span:
    return Span(Ms(start), Ms(end))


def as_set(frame: pl.DataFrame) -> set[tuple[object, ...]]:
    return set(frame.rows())


# ─── Configuração e caminhos ─────────────────────────────────────────────────


@pytest.mark.unit
def test_data_dir_comes_from_copylab_data_dir(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env.setenv("COPYLAB_DATA_DIR", str(tmp_path / "dados"))
    store = ParquetStore.from_settings(Settings(_env_file=None))
    store.write("t", ("p",), rows((1, "a", 1.0)), span=span(0, 10), instant="t")
    assert (tmp_path / "dados" / "t" / "p.parquet").is_file()


@pytest.mark.unit
def test_missing_data_dir_is_an_actionable_config_error(settings: Settings) -> None:
    assert settings.data_dir is None
    with pytest.raises(ConfigError, match="COPYLAB_DATA_DIR"):
        ParquetStore.from_settings(settings)


@pytest.mark.unit
def test_data_dir_that_is_a_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "arquivo").write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="não é um diretório"):
        ParquetStore(tmp_path / "arquivo")


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", ".", "..", ".oculto", "a/b", "a\\b", "a\x00b"])
def test_partition_values_cannot_escape_the_table(tmp_path: Path, bad: str) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(DataError, match="inválido"):
        store.write("t", (bad,), rows(), span=span(0, 1), instant="t")


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", "..", "raw/../x", "/abs", "raw//x", ".x", "a\\b"])
def test_table_names_cannot_escape_the_data_dir(tmp_path: Path, bad: str) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(DataError, match="inválido"):
        store.partitions(bad)
    with pytest.raises(DataError, match="inválido"):
        store.write(bad, ("p",), rows(), span=span(0, 1), instant="t")


@pytest.mark.unit
def test_partitions_are_nested_listed_in_order_and_read_back(tmp_path: Path) -> None:
    """Partição de chave dupla, como a do proxy (ativo, dia)."""
    store = ParquetStore(tmp_path)
    store.write("proxy", ("ETH", "20697"), rows((5, "e", 2.0)), span=span(0, 10), instant="t")
    store.write("proxy", ("BTC", "20697"), rows((5, "b", 1.0)), span=span(0, 10), instant="t")
    store.write("raw/leaderboard", ("1",), rows((1, "x", 0.0)), span=span(0, 10), instant="t")

    assert store.partitions("proxy") == [("BTC", "20697"), ("ETH", "20697")]
    assert store.partitions("raw/leaderboard") == [("1",)]
    assert store.partitions("nada") == []
    assert store.exists("proxy", ("BTC", "20697"))
    assert not store.exists("proxy", ("SOL", "20697"))
    assert store.read("proxy", ("BTC", "20697")).rows() == [(5, "b", 1.0)]
    with pytest.raises(DataError, match="não existe"):
        store.read("proxy", ("SOL", "20697"))


# ─── Escrita por trecho ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_write_replaces_its_span_and_keeps_the_rest(tmp_path: Path) -> None:
    """Primeiro [0, 100) com linhas em 10 e 60; depois [50, 100) com uma linha em 70.

    Fica a linha de 10 (fora do segundo trecho) e entra a de 70; a de 60 sai, porque o
    segundo trecho se declara completo em [50, 100). Os trechos gravados continuam
    [0, 100), fundidos.
    """
    store = ParquetStore(tmp_path)
    store.write("t", ("p",), rows((60, "b", 2.0), (10, "a", 1.0)), span=span(0, 100), instant="t")
    outcome = store.write("t", ("p",), rows((70, "c", 3.0)), span=span(50, 100), instant="t")

    assert store.read("t", ("p",)).rows() == [(10, "a", 1.0), (70, "c", 3.0)]
    assert store.spans("t", ("p",)) == (span(0, 100),)
    assert outcome.rows == 2
    assert not outcome.diverged


@pytest.mark.unit
def test_rows_are_stored_in_instant_order_keeping_arrival_order_within_an_instant(
    tmp_path: Path,
) -> None:
    store = ParquetStore(tmp_path)
    frame = rows((20, "y", 1.0), (10, "b", 1.0), (10, "a", 1.0))
    store.write("t", ("p",), frame, span=span(0, 100), instant="t")
    assert store.read("t", ("p",))["id"].to_list() == ["b", "a", "y"]


@pytest.mark.unit
def test_empty_span_write_is_recorded(tmp_path: Path) -> None:
    """Uma carteira sem fills numa semana: nada a gravar, mas o trecho foi coletado."""
    store = ParquetStore(tmp_path)
    store.write("t", ("p",), rows(), span=span(0, 100), instant="t")
    assert store.read("t", ("p",)).height == 0
    assert store.spans("t", ("p",)) == (span(0, 100),)
    assert store.spans("t", ("q",)) == ()


@pytest.mark.unit
def test_row_outside_declared_span_is_refused(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    with pytest.raises(DataError, match="fora do trecho"):
        store.write("t", ("p",), rows((100, "a", 1.0)), span=span(0, 100), instant="t")
    assert not store.exists("t", ("p",))


@pytest.mark.unit
def test_schema_change_is_refused(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    store.write("t", ("p",), rows((1, "a", 1.0)), span=span(0, 10), instant="t")
    other = pl.DataFrame({"t": [2], "id": ["b"], "px": [1]})  # px inteiro
    with pytest.raises(DataError, match="Esquema"):
        store.write("t", ("p",), other, span=span(0, 10), instant="t")


@pytest.mark.unit
def test_instant_can_be_an_expression(tmp_path: Path) -> None:
    """O proxy guarda segundos; o instante em ms é `second * 1000`."""
    store = ParquetStore(tmp_path)
    frame = pl.DataFrame({"second": [1, 2], "last": [10.0, 11.0]})
    store.write("proxy", ("BTC",), frame, span=span(1_000, 3_000), instant=pl.col("second") * 1_000)
    with pytest.raises(DataError, match="fora do trecho"):
        store.write("proxy", ("BTC",), frame, span=span(0, 2_000), instant=pl.col("second") * 1_000)


@pytest.mark.unit
def test_file_without_span_record_is_a_data_error(tmp_path: Path) -> None:
    (tmp_path / "t").mkdir()
    rows((1, "a", 1.0)).write_parquet(tmp_path / "t" / "p.parquet")
    with pytest.raises(DataError, match="sem registro de trechos"):
        ParquetStore(tmp_path).spans("t", ("p",))


# ─── Escrita atômica ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_interrupted_write_leaves_previous_table_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0006 decisão 4. A gravação cai no meio, depois de escrever bytes parciais."""
    store = ParquetStore(tmp_path)
    before = rows((1, "a", 1.0), (2, "b", 2.0))
    store.write("t", ("p",), before, span=span(0, 10), instant="t")

    def crash(self: pl.DataFrame, file: str | Path, **_: object) -> None:
        Path(file).write_bytes(b"PAR1 metade de um arquivo")
        raise RuntimeError("queda simulada")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", crash)
    with pytest.raises(RuntimeError, match="queda simulada"):
        store.write("t", ("p",), rows((3, "c", 3.0)), span=span(0, 10), instant="t")
    monkeypatch.undo()

    assert store.read("t", ("p",)).equals(before)
    assert store.spans("t", ("p",)) == (span(0, 10),)
    assert sorted(path.name for path in (tmp_path / "t").iterdir()) == ["p.parquet"]


@pytest.mark.unit
def test_leftover_temporary_from_a_hard_crash_is_ignored(tmp_path: Path) -> None:
    """Uma queda de energia não deixa o `finally` rodar: sobra o temporário oculto."""
    store = ParquetStore(tmp_path)
    store.write("t", ("p",), rows((1, "a", 1.0)), span=span(0, 10), instant="t")
    (tmp_path / "t" / ".p.parquet.abc123.tmp").write_bytes(b"lixo")
    (tmp_path / "t" / ".oculto.parquet").write_bytes(b"lixo")

    assert store.partitions("t") == [("p",)]
    assert store.read("t", ("p",)).rows() == [(1, "a", 1.0)]


# ─── Janelas congeladas ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_frozen_rows_are_never_rewritten(tmp_path: Path) -> None:
    """Janela congelada [100, 200). Primeira coleta de [0, 200), depois uma reingestão.

    Primeira coleta: a (t=50), b (t=150, px 1.0), c (t=160). Grava tudo: nada estava
    coletado ainda.

    Reingestão do mesmo trecho: a' (t=50, px 9.0), b' (t=150, px 2.0), d (t=170); c some.

    - a' está fora da janela congelada: substitui a.
    - Em [100, 200), que está congelado e já coletado, o gravado fica: b e c. Linhas só
      do gravado: b e c (`frozen_kept`). Linhas só da coleta nova: b' e d
      (`frozen_rejected`).
    """
    store = ParquetStore(tmp_path, frozen=[span(100, 200)])
    first = rows((50, "a", 1.0), (150, "b", 1.0), (160, "c", 1.0))
    store.write("fills", ("0xabc",), first, span=span(0, 200), instant="t")

    again = rows((50, "a", 9.0), (150, "b", 2.0), (170, "d", 1.0))
    outcome = store.write("fills", ("0xabc",), again, span=span(0, 200), instant="t")

    assert store.read("fills", ("0xabc",)).rows() == [
        (50, "a", 9.0),
        (150, "b", 1.0),
        (160, "c", 1.0),
    ]
    assert outcome.diverged
    assert as_set(outcome.frozen_kept) == {(150, "b", 1.0), (160, "c", 1.0)}
    assert as_set(outcome.frozen_rejected) == {(150, "b", 2.0), (170, "d", 1.0)}


@pytest.mark.unit
def test_identical_reingestion_of_frozen_window_has_no_divergence(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path, frozen=[span(0, 100)])
    first = rows((10, "a", 1.0), (10, "a", 1.0), (20, "b", float("nan")))
    store.write("t", ("p",), first, span=span(0, 100), instant="t")
    outcome = store.write("t", ("p",), first.reverse(), span=span(0, 100), instant="t")
    assert not outcome.diverged
    assert outcome.rows == 3


@pytest.mark.unit
def test_first_write_inside_frozen_window_is_accepted(tmp_path: Path) -> None:
    """Janela congelada [100, 200). Coleta-se primeiro só [0, 120), depois [0, 200).

    Na segunda escrita, [100, 120) já estava coletado e fica como estava; [120, 200) é
    coletado pela primeira vez e entra. É o caso da janela de avaliação da Rota B,
    ingerida dia a dia depois do congelamento.
    """
    store = ParquetStore(tmp_path, frozen=[span(100, 200)])
    store.write("t", ("p",), rows((110, "a", 1.0)), span=span(0, 120), instant="t")
    outcome = store.write(
        "t", ("p",), rows((110, "a", 5.0), (150, "n", 1.0)), span=span(0, 200), instant="t"
    )

    assert store.read("t", ("p",)).rows() == [(110, "a", 1.0), (150, "n", 1.0)]
    assert as_set(outcome.frozen_kept) == {(110, "a", 1.0)}
    assert as_set(outcome.frozen_rejected) == {(110, "a", 5.0)}
    assert store.spans("t", ("p",)) == (span(0, 200),)


@pytest.mark.unit
def test_frozen_windows_are_normalized(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path, frozen=[span(50, 80), span(0, 60), span(90, 90)])
    assert store.frozen == (span(0, 80),)
