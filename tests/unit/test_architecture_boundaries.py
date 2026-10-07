"""Fronteiras entre pacotes do design §2.1, provadas por AST sobre `src/copylab/**`.

Este arquivo guarda os testes de arquitetura que dependem de *quem* usa o quê, e não só
do quê é usado. Por isso o detector resolve import relativo para o nome absoluto:
`from .. import clock` dentro de `copylab.selection.x` é `copylab.clock`.

- `test_architecture_time_boundary` (RNF-07): só `timeutil` importa `datetime`; só
  `clock` importa `time`; só `collector`, `ingestion` e `cli` importam `clock`; `asyncio`
  só no `collector`. O plano (T-002) pede, no mínimo, `clock` proibido em `leader`,
  `selection`, `sim` e `analytics`; a regra aqui é a lista de permissão do design,
  que contém essa proibição.
- `test_architecture_storage_isolation` (ADR-0006): fora de `storage`, ninguém importa
  biblioteca de Parquet, chama leitura ou escrita de Parquet, nem toca o diretório de
  dados (`data_dir` ou `COPYLAB_DATA_DIR`). `config` declara o campo e é a exceção.
- `test_architecture_logic_packages_are_pure` (design §2.1): `leader`, `selection`, `sim`
  e `analytics` não importam `storage`, `ingestion`, `collector`, `clock` nem `cli`, nem
  módulo de rede, de sistema de arquivos ou de processo, e não chamam `open` nem
  funções `read_*`, `scan_*`, `write_*` e `sink_*`. `io` fica permitido: o gráfico
  devolve a imagem em memória (`BytesIO`).

A varredura é estática: nada é importado nem executado. Import dinâmico com argumento
calculado, e acesso por `getattr` com nome calculado, não são decidíveis por AST e passam
(mesmo limite do teste de RNF-09).

Prova de dente de `test_architecture_time_boundary`, feita à mão em 2026-10-07 e
restaurada (os arquivos plantados foram apagados):

- `src/copylab/sim/_dente.py` com `import datetime`: falhou, apontando
  `sim/_dente.py:1 usa datetime`.
- `src/copylab/storage/_dente.py` com `from time import monotonic`: falhou
  (`time`).
- `src/copylab/selection/_dente.py` com `from .. import clock`: falhou
  (`copylab.clock`), o que prova que o import relativo é resolvido.
- `src/copylab/leader/_dente.py` com `from copylab import clock` e
  `import asyncio`: falhou nas duas linhas.
- `src/copylab/ingestion/_dente.py` com `from copylab.clock import now` e
  `from copylab.timeutil import Ms`: não falhou, como deve ser.
- `source_files` trocado por `glob` (só o primeiro nível), com os arquivos acima ainda
  plantados: `test_architecture_time_boundary` passou cego, e os guardas
  `test_boundary_scan_covers_every_module_the_interpreter_can_find` e
  `test_scan_tree_resolves_modules_from_paths` falharam. É para isso que eles existem.

Prova de dente de `test_architecture_storage_isolation` e de
`test_architecture_logic_packages_are_pure`, feita à mão em 2026-10-07 e restaurada,
com seis arquivos plantados de uma vez:

- `ingestion/_dente.py` com `pl.scan_parquet("x")` e `import pyarrow.parquet`;
  `copylab/cli_dente.py` com `get_settings().data_dir`; `collector/_dente.py` com
  `os.environ["COPYLAB_DATA_DIR"]`. O teste de isolamento falhou nas quatro linhas.
- `sim/_dente.py` com `import pathlib`, `from copylab.storage import ParquetStore`,
  `import httpx`, `from .. import ingestion` e `open("x")`; `leader/_dente.py` com
  `pl.read_csv("x")`. O teste de pureza falhou nas seis linhas.
- `analytics/_dente.py` com `io.BytesIO()`: não falhou, como deve ser.
"""

import ast
import importlib.util
import pkgutil
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import pytest

import copylab

SRC_ROOT: Final = Path(__file__).resolve().parents[2] / "src" / "copylab"

Kind = Literal["import", "identifier", "constant"]


def _is_under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


@dataclass(frozen=True, slots=True)
class Rule:
    """Quem pode usar ``target``.

    Com ``owners``, só eles podem; com ``banned_in``, todos podem menos eles. ``kind``
    diz o que ``target`` é: um módulo importado (e tudo abaixo dele), uma expressão
    regular sobre identificadores (nomes, atributos, argumentos nomeados e nomes
    importados) ou um texto literal exato.
    """

    target: str
    why: str
    owners: tuple[str, ...] = ()
    banned_in: tuple[str, ...] = ()
    kind: Kind = "import"

    def forbids(self, current: str) -> bool:
        if self.owners:
            return not any(_is_under(current, owner) for owner in self.owners)
        return any(_is_under(current, banned) for banned in self.banned_in)

    def matches(self, kind: Kind, value: str) -> bool:
        if kind != self.kind:
            return False
        if kind == "import":
            return _is_under(value, self.target)
        if kind == "identifier":
            return re.fullmatch(self.target, value) is not None
        return value == self.target


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    line: int
    used: str
    rule: Rule

    def render(self) -> str:
        where = self.path.relative_to(SRC_ROOT) if self.path.is_absolute() else self.path
        return f"  {where}:{self.line} usa {self.used} ({self.rule.why})"


TIME_RULES: Final = (
    Rule("datetime", "só timeutil converte instante em calendário", owners=("copylab.timeutil",)),
    Rule("time", "só clock lê o relógio da máquina", owners=("copylab.clock",)),
    Rule(
        "copylab.clock",
        "só collector, ingestion e cli carimbam com o relógio",
        owners=("copylab.clock", "copylab.collector", "copylab.ingestion", "copylab.cli"),
    ),
    Rule("asyncio", "asyncio é permitido só no coletor", owners=("copylab.collector",)),
)

_STORAGE: Final = ("copylab.storage",)
_KNOWS_DATA_DIR: Final = ("copylab.storage", "copylab.config")

STORAGE_RULES: Final = (
    Rule("pyarrow", "só storage lê e escreve Parquet", owners=_STORAGE),
    Rule("fastparquet", "só storage lê e escreve Parquet", owners=_STORAGE),
    Rule(
        r"(read|scan|write|sink)_parquet\w*",
        "só storage lê e escreve Parquet",
        owners=_STORAGE,
        kind="identifier",
    ),
    Rule(
        "data_dir",
        "só storage conhece o diretório de dados",
        owners=_KNOWS_DATA_DIR,
        kind="identifier",
    ),
    Rule(
        "COPYLAB_DATA_DIR",
        "só storage conhece o diretório de dados",
        owners=_KNOWS_DATA_DIR,
        kind="constant",
    ),
)

LOGIC_PACKAGES: Final = ("copylab.leader", "copylab.selection", "copylab.sim", "copylab.analytics")

#: Módulos que a lógica não importa, com o motivo.
_IMPURE_MODULES: Final = {
    "copylab.storage": "lógica lê por copylab.ports, não pelo armazenamento",
    "copylab.ingestion": "lógica não fala com a API",
    "copylab.collector": "lógica não fala com o coletor",
    "copylab.clock": "lógica não lê o relógio",
    "copylab.cli": "as setas apontam para dentro: a CLI usa a lógica, não o contrário",
    **dict.fromkeys(
        ("socket", "ssl", "http", "urllib", "httpx", "requests", "websockets", "aiohttp"),
        "lógica não usa rede",
    ),
    "asyncio": "lógica não usa laço de eventos",
    **dict.fromkeys(
        ("os", "pathlib", "shutil", "tempfile", "glob", "fileinput", "sqlite3", "pickle", "shelve"),
        "lógica não usa arquivo",
    ),
    "subprocess": "lógica não roda processo",
}

PURITY_RULES: Final = (
    *(Rule(m, why, banned_in=LOGIC_PACKAGES) for m, why in _IMPURE_MODULES.items()),
    Rule("open", "lógica não abre arquivo", banned_in=LOGIC_PACKAGES, kind="identifier"),
    Rule(
        r"(read|scan|write|sink)_\w+",
        "lógica não lê nem grava arquivo",
        banned_in=LOGIC_PACKAGES,
        kind="identifier",
    ),
)


# ─── Detector ────────────────────────────────────────────────────────────────


def module_name(path: Path, root: Path = SRC_ROOT) -> tuple[str, bool]:
    """Nome absoluto do módulo em ``path`` e se ele é um pacote (``__init__``)."""
    parts = path.relative_to(root.parent).with_suffix("").parts
    is_package = parts[-1] == "__init__"
    return ".".join(parts[:-1] if is_package else parts), is_package


def _resolve(module: str | None, level: int, current: str, is_package: bool) -> str:
    if level == 0:
        return module or ""
    base = current.split(".") if is_package else current.split(".")[:-1]
    base = base[: len(base) - (level - 1)]
    return ".".join([*base, module] if module else base)


def _dynamic_import_target(node: ast.Call) -> str | None:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name not in {"__import__", "import_module"} or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def imported_names(source: str, current: str, is_package: bool) -> Iterator[tuple[int, str]]:
    """Cada nome absoluto que ``source`` importa, com a linha.

    ``from a import b`` produz ``a`` e ``a.b``: ``b`` pode ser um submódulo
    (``from copylab import clock``).
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(node.module, node.level, current, is_package)
            yield node.lineno, base
            for alias in node.names:
                yield node.lineno, f"{base}.{alias.name}"
        elif isinstance(node, ast.Call):
            target = _dynamic_import_target(node)
            if target is not None:
                yield node.lineno, target


def usages(source: str, current: str, is_package: bool) -> Iterator[tuple[int, Kind, str]]:
    """Imports, identificadores e textos literais de ``source``, com a linha."""
    for line, name in imported_names(source, current, is_package):
        yield line, "import", name
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            yield node.lineno, "identifier", node.attr
        elif isinstance(node, ast.Name):
            yield node.lineno, "identifier", node.id
        elif isinstance(node, ast.keyword) and node.arg is not None:
            yield node.lineno, "identifier", node.arg
        elif isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                yield node.lineno, "identifier", alias.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, "constant", node.value


def violations_in(
    source: str, current: str, is_package: bool, rules: tuple[Rule, ...], path: Path
) -> list[Violation]:
    active = [rule for rule in rules if rule.forbids(current)]
    found: list[Violation] = []
    seen: set[tuple[int, str]] = set()
    for line, kind, value in usages(source, current, is_package):
        for rule in active:
            if rule.matches(kind, value) and (line, rule.target) not in seen:
                seen.add((line, rule.target))
                found.append(
                    Violation(path, line, value if kind != "import" else rule.target, rule)
                )
    return sorted(found, key=lambda v: (v.line, v.used))


def source_files(root: Path) -> list[Path]:
    """Todo ``.py`` abaixo de ``root``, em ordem estável."""
    return sorted(root.rglob("*.py"))


def scan_tree(root: Path, rules: tuple[Rule, ...]) -> list[Violation]:
    found: list[Violation] = []
    for path in source_files(root):
        current, is_package = module_name(path, root)
        found.extend(
            violations_in(path.read_text(encoding="utf-8"), current, is_package, rules, path)
        )
    return found


def _check(
    source: str, current: str, rules: tuple[Rule, ...], is_package: bool = False
) -> list[str]:
    return [v.used for v in violations_in(source, current, is_package, rules, Path("x.py"))]


def _assert_clean(rules: tuple[Rule, ...], label: str) -> None:
    violations = scan_tree(SRC_ROOT, rules)
    report = "\n".join(v.render() for v in violations)
    assert not violations, f"{label}:\n{report}"


# ─── O detector, caso a caso: tempo ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "source", "expected"),
    [
        ("copylab.sim.engine", "import datetime", ["datetime"]),
        ("copylab.sim.engine", "from datetime import date", ["datetime"]),
        ("copylab.params", "import datetime as dt", ["datetime"]),
        ("copylab.storage.files", "import time", ["time"]),
        ("copylab.storage.files", "from time import monotonic", ["time"]),
        ("copylab.analytics.x", "__import__('time')", ["time"]),
        ("copylab.selection.pool", "from copylab import clock", ["copylab.clock"]),
        ("copylab.selection.pool", "from copylab.clock import now", ["copylab.clock"]),
        ("copylab.selection.pool", "from .. import clock", ["copylab.clock"]),
        ("copylab.selection.pool", "from ..clock import now", ["copylab.clock"]),
        ("copylab.leader.ledger", "from .. import clock", ["copylab.clock"]),
        ("copylab.storage", "import copylab.clock", ["copylab.clock"]),
        ("copylab.params", "from copylab import clock", ["copylab.clock"]),
        ("copylab.sim.loop", "import asyncio", ["asyncio"]),
        ("copylab.ingestion.x", "import asyncio", ["asyncio"]),
        ("copylab.sim.x", "def f() -> None:\n    import datetime\n", ["datetime"]),
    ],
)
def test_time_detector_flags_forbidden_imports(
    current: str, source: str, expected: list[str]
) -> None:
    assert _check(source, current, TIME_RULES) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "source"),
    [
        ("copylab.timeutil", "from datetime import UTC, date, datetime"),
        ("copylab.clock", "import time"),
        ("copylab.clock", "from copylab.timeutil import Ms"),
        ("copylab.collector.recorder", "import asyncio\nfrom copylab import clock"),
        ("copylab.ingestion.budget", "from copylab.clock import now"),
        ("copylab.cli", "from copylab import clock"),
        ("copylab.sim.engine", "from copylab.timeutil import Ms, hour_floor"),
        ("copylab.sim.engine", "import timeit_fake\nimport datetimes"),
        ("copylab.selection.pool", "from . import clock"),
        ("copylab.sim.engine", "# import datetime\ntexto = 'import time'"),
    ],
)
def test_time_detector_allows_permitted_imports(current: str, source: str) -> None:
    assert _check(source, current, TIME_RULES) == []


@pytest.mark.unit
def test_relative_import_is_resolved_from_the_package() -> None:
    """Num `__init__`, `from . import x` é o próprio pacote; num módulo, o pacote pai."""
    assert dict(imported_names("from . import clock", "copylab", True)) == {1: "copylab.clock"}
    names = [n for _, n in imported_names("from . import x", "copylab.sim.loop", False)]
    assert names == ["copylab.sim", "copylab.sim.x"]


@pytest.mark.unit
def test_scan_tree_resolves_modules_from_paths(tmp_path: Path) -> None:
    root = tmp_path / "copylab"
    (root / "sim").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "sim" / "__init__.py").write_text("from .. import clock\n", encoding="utf-8")
    (root / "timeutil.py").write_text("import datetime\n", encoding="utf-8")

    found = scan_tree(root, TIME_RULES)
    assert [(v.path.relative_to(root).as_posix(), v.used) for v in found] == [
        ("sim/__init__.py", "copylab.clock")
    ]


# ─── O detector, caso a caso: armazenamento ──────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "source", "expected"),
    [
        ("copylab.ingestion.fills", "import polars as pl\npl.read_parquet('x')", ["read_parquet"]),
        ("copylab.ingestion.fills", "df.write_parquet('x')", ["write_parquet"]),
        ("copylab.collector.compact", "pl.scan_parquet('x')", ["scan_parquet"]),
        ("copylab.cli", "pl.read_parquet_metadata(p)", ["read_parquet_metadata"]),
        ("copylab.cli", "from polars import read_parquet", ["read_parquet"]),
        ("copylab.selection.x", "import pyarrow.parquet as pq", ["pyarrow"]),
        ("copylab.cli", "root = settings.data_dir", ["data_dir"]),
        ("copylab.cli", "Store(data_dir=x)", ["data_dir"]),
        ("copylab.ingestion.x", "os.environ['COPYLAB_DATA_DIR']", ["COPYLAB_DATA_DIR"]),
    ],
)
def test_storage_detector_flags_parquet_and_data_dir_outside_storage(
    current: str, source: str, expected: list[str]
) -> None:
    assert _check(source, current, STORAGE_RULES) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "source"),
    [
        ("copylab.storage.files", "pl.read_parquet(p)\nframe.write_parquet(p)"),
        ("copylab.storage", "root = settings.data_dir"),
        ("copylab.config", "data_dir: Path | None = None"),
        ("copylab.ingestion.x", "msg = 'defina COPYLAB_DATA_DIR antes'"),
        ("copylab.ingestion.x", "store.write('fills', p, frame, span=s, instant='t')"),
    ],
)
def test_storage_detector_allows_storage_itself_and_unrelated_code(
    current: str, source: str
) -> None:
    assert _check(source, current, STORAGE_RULES) == []


# ─── O detector, caso a caso: pureza da lógica ───────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "source", "expected"),
    [
        ("copylab.sim.loop", "from copylab.storage import ParquetStore", ["copylab.storage"]),
        ("copylab.selection.x", "from .. import ingestion", ["copylab.ingestion"]),
        ("copylab.leader.ledger", "from ..collector import x", ["copylab.collector"]),
        ("copylab.analytics.x", "from copylab import cli", ["copylab.cli"]),
        ("copylab.sim.loop", "import httpx", ["httpx"]),
        ("copylab.sim.loop", "import urllib.request", ["urllib"]),
        ("copylab.sim.loop", "from pathlib import Path", ["pathlib"]),
        ("copylab.analytics.plot", "import os", ["os"]),
        ("copylab.analytics.plot", "with open('x.png', 'wb') as f: pass", ["open"]),
        ("copylab.analytics.plot", "import io\nio.open('x')", ["open"]),
        ("copylab.leader.ledger", "pl.read_csv('x')", ["read_csv"]),
        ("copylab.selection.x", "frame.write_json('x')", ["write_json"]),
        ("copylab.selection.x", "path.read_text()", ["read_text"]),
    ],
)
def test_purity_detector_flags_io_in_logic_packages(
    current: str, source: str, expected: list[str]
) -> None:
    assert _check(source, current, PURITY_RULES) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("current", "source"),
    [
        ("copylab.analytics.plot", "import io\nbuffer = io.BytesIO()\nfig.savefig(buffer)"),
        ("copylab.selection.pool", "from copylab.ports import BoundedRepository"),
        ("copylab.sim.engine", "from copylab.timeutil import Ms\nimport polars as pl"),
        ("copylab.selection.x", "from copylab.exceptions import LookaheadError"),
        ("copylab.ingestion.x", "import httpx\nfrom pathlib import Path\nopen('x')"),
        ("copylab.storage.files", "import os\nos.replace(a, b)"),
    ],
)
def test_purity_detector_allows_pure_code_and_io_outside_logic(current: str, source: str) -> None:
    assert _check(source, current, PURITY_RULES) == []


# ─── A árvore real ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_architecture_time_boundary() -> None:
    _assert_clean(TIME_RULES, "RNF-07 violado (design §2.1)")


@pytest.mark.unit
def test_architecture_storage_isolation() -> None:
    _assert_clean(STORAGE_RULES, "ADR-0006 violado: Parquet ou diretório de dados fora de storage")


@pytest.mark.unit
def test_architecture_logic_packages_are_pure() -> None:
    _assert_clean(PURITY_RULES, "Pacote de lógica impuro (design §2.1)")


@pytest.mark.unit
def test_boundary_scan_covers_every_module_the_interpreter_can_find() -> None:
    """Tudo o que o `pkgutil` enumera precisa estar no que foi varrido.

    Sem isto, mover um módulo para fora do alcance de `source_files` faria os testes
    de fronteira passarem varrendo nada.
    """
    scanned = {path.resolve() for path in source_files(SRC_ROOT)}
    discovered = {name for _, name, _ in pkgutil.walk_packages(copylab.__path__, prefix="copylab.")}
    expected = {"copylab.timeutil", "copylab.clock", "copylab.config", "copylab.storage"}
    assert expected | set(LOGIC_PACKAGES) <= discovered
    for name in discovered:
        spec = importlib.util.find_spec(name)
        assert spec is not None
        assert spec.origin is not None
        assert Path(spec.origin).resolve() in scanned, f"{name} não foi varrido"


@pytest.mark.unit
def test_module_name_matches_the_interpreter() -> None:
    """O nome que o detector atribui a um arquivo é o nome com que ele é importado."""
    for path in source_files(SRC_ROOT):
        name, _ = module_name(path)
        spec = importlib.util.find_spec(name)
        assert spec is not None, name
        assert spec.origin is not None
        assert Path(spec.origin).resolve() == path.resolve()
