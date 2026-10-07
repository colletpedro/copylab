"""Fronteiras entre pacotes do design §2.1, provadas por AST sobre `src/copylab/**`.

Este arquivo guarda os testes de arquitetura que dependem de *quem* importa o quê, e não
só do quê é importado. Por isso o detector resolve import relativo para o nome
absoluto: `from .. import clock` dentro de `copylab.selection.x` é `copylab.clock`.

- `test_architecture_time_boundary` (RNF-07): só `timeutil` importa `datetime`; só
  `clock` importa `time`; só `collector`, `ingestion` e `cli` importam `clock`; `asyncio`
  só no `collector`. O plano (T-002) pede, no mínimo, `clock` proibido em `leader`,
  `selection`, `sim` e `analytics`; a regra aqui é a lista de permissão do design,
  que contém essa proibição.

A varredura é estática: nada é importado nem executado. Import dinâmico com argumento
calculado não é decidível por AST e passa (mesmo limite do teste de RNF-09).

Prova de dente de `test_architecture_time_boundary`, feita à mão em 2026-10-07 e
restaurada (os arquivos plantados foram apagados):

- `src/copylab/sim/_dente.py` com `import datetime`: falhou, apontando
  `sim/_dente.py:1 importa datetime`.
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
"""

import ast
import importlib.util
import pkgutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

import copylab

SRC_ROOT: Final = Path(__file__).resolve().parents[2] / "src" / "copylab"


@dataclass(frozen=True, slots=True)
class Rule:
    """``module`` (e tudo abaixo dele) só pode ser importado pelos donos listados."""

    module: str
    owners: tuple[str, ...]
    why: str


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    line: int
    imported: str
    rule: Rule

    def render(self) -> str:
        where = self.path.relative_to(SRC_ROOT) if self.path.is_absolute() else self.path
        return f"  {where}:{self.line} importa {self.imported} ({self.rule.why})"


TIME_RULES: Final = (
    Rule("datetime", ("copylab.timeutil",), "só timeutil converte instante em calendário"),
    Rule("time", ("copylab.clock",), "só clock lê o relógio da máquina"),
    Rule(
        "copylab.clock",
        ("copylab.clock", "copylab.collector", "copylab.ingestion", "copylab.cli"),
        "só collector, ingestion e cli carimbam com o relógio",
    ),
    Rule("asyncio", ("copylab.collector",), "asyncio é permitido só no coletor"),
)


# ─── Detector ────────────────────────────────────────────────────────────────


def _is_under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


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


def violations_in(
    source: str, current: str, is_package: bool, rules: tuple[Rule, ...], path: Path
) -> list[Violation]:
    found: list[Violation] = []
    seen: set[tuple[int, str]] = set()
    for line, name in imported_names(source, current, is_package):
        for rule in rules:
            if not _is_under(name, rule.module):
                continue
            if any(_is_under(current, owner) for owner in rule.owners):
                continue
            if (line, rule.module) not in seen:
                seen.add((line, rule.module))
                found.append(Violation(path, line, rule.module, rule))
    return found


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
    return [v.imported for v in violations_in(source, current, is_package, rules, Path("x.py"))]


# ─── O detector, caso a caso ─────────────────────────────────────────────────


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
    assert [(v.path.relative_to(root).as_posix(), v.imported) for v in found] == [
        ("sim/__init__.py", "copylab.clock")
    ]


# ─── A árvore real ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_architecture_time_boundary() -> None:
    violations = scan_tree(SRC_ROOT, TIME_RULES)
    report = "\n".join(v.render() for v in violations)
    assert not violations, f"RNF-07 violado (design §2.1):\n{report}"


@pytest.mark.unit
def test_boundary_scan_covers_every_module_the_interpreter_can_find() -> None:
    """Tudo o que o `pkgutil` enumera precisa estar no que foi varrido.

    Sem isto, mover um módulo para fora do alcance de `source_files` faria os testes
    de fronteira passarem varrendo nada.
    """
    scanned = {path.resolve() for path in source_files(SRC_ROOT)}
    discovered = {name for _, name, _ in pkgutil.walk_packages(copylab.__path__, prefix="copylab.")}
    assert {"copylab.timeutil", "copylab.clock", "copylab.leader", "copylab.sim"} <= discovered
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
