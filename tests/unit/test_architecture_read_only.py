"""RNF-09 / ADR-0001: nenhuma chave, assinatura ou endpoint de ordem no código.

Varre por AST todo `src/copylab/**/*.py` e falha se algum arquivo importar
`hyperliquid.exchange` (cliente de ordens do SDK), `eth_account`, `eth_keys` ou
`web3` (chaves e assinatura). A varredura é estática: nada é importado nem
executado, então o teste vale mesmo sem essas bibliotecas instaladas.

Há três camadas de prova:

1. `forbidden_imports` é testado sobre trechos de código, uma forma de import
   por vez, com casos negativos (importar `hyperliquid.info` é permitido: é só
   leitura, e é o que ADR-0001 usa).
2. `scan_tree` é testado sobre uma árvore temporária, para provar que a
   caminhada de arquivos alcança subpacotes aninhados.
3. Guardas de cobertura falham se a varredura real deixar de enxergar algum
   módulo ou subpacote. Sem eles, mover os arquivos para outro lugar faria o
   teste passar varrendo nada.

Prova de dente (CLAUDE.md §3), feita à mão em 2026-10-05 sobre a árvore real:
um arquivo `src/copylab/sim/_dente.py` foi criado, o teste rodado, e o arquivo
removido. Resultado:

- `import web3`: `test_source_tree_has_no_order_or_signing_imports` falhou, com
  `sim/_dente.py:1` na mensagem.
- `from eth_account import Account`: falhou da mesma forma.
- `import eth_keys.datatypes`: falhou da mesma forma.
- `from hyperliquid.exchange import Exchange`: falhou da mesma forma.
- `from hyperliquid import exchange`: falhou da mesma forma.
- `from hyperliquid.info import Info`: não falhou, como deve ser.

Os guardas de cobertura também foram quebrados de propósito e restaurados:

- `source_files` ignorando o subpacote `selection`: falharam
  `test_scan_covers_every_expected_subpackage` e
  `test_scan_covers_every_module_the_interpreter_can_find`.
- Subpacote `collector` renomeado: os mesmos dois falharam.
- `source_files` com `glob` em vez de `rglob` (só o primeiro nível): falharam
  esses dois e `test_scan_tree_reaches_nested_subpackages`.

A varredura vale também para `scripts/**/*.py` (verificação de dados, §4.1), que falam
com a rede. Prova de dente, feita à mão em 2026-10-06 e restaurada: os mesmos cinco
imports proibidos plantados em `scripts/verify/_dente.py` (e `import web3` numa
subpasta nova) derrubaram `test_scripts_tree_has_no_order_or_signing_imports`;
`hyperliquid.info` passou. Encolher `source_files` (`glob` em vez de `rglob`, ignorar
`verify`, ou ignorar uma pasta nova) derrubou
`test_scripts_scan_covers_every_expected_script` e/ou
`test_scripts_scan_covers_every_python_file_on_disk`.

Limite conhecido: import dinâmico com argumento que não é literal (`import_module(nome)`
com `nome` calculado) não é decidível por AST e passa. O projeto não tem motivo
para importar dinamicamente, e uma revisão que o introduza deve ser lida com isso
em mente.
"""

import ast
import importlib.util
import os
import pkgutil
from pathlib import Path
from typing import Final

import pytest

import copylab

#: Módulos proibidos. Um módulo é proibido ele mesmo e tudo abaixo dele.
FORBIDDEN_MODULES: Final = ("hyperliquid.exchange", "eth_account", "eth_keys", "web3")

#: Subpacotes que a Fase 0 declara. Lista escrita à mão de propósito: remover um
#: deles exige editar este teste e, portanto, ser notado numa revisão.
EXPECTED_SUBPACKAGES: Final = (
    "ingestion",
    "collector",
    "storage",
    "selection",
    "sim",
    "analytics",
)

SRC_ROOT: Final = Path(__file__).resolve().parents[2] / "src" / "copylab"

#: Scripts exploratórios (verificação de dados, §4.1). Ficam fora de `src/`, mas
#: falam com a rede, então RNF-09 vale para eles também.
SCRIPTS_ROOT: Final = SRC_ROOT.parents[1] / "scripts"

#: Scripts que a verificação de dados declara, relativos a `scripts/`. Escritos à mão
#: de propósito, como `EXPECTED_SUBPACKAGES`: sumir com um exige editar este teste.
EXPECTED_SCRIPTS: Final = ("verify/common.py",)

#: (arquivo, linha, módulo proibido)
Violation = tuple[Path, int, str]


def _is_forbidden(module: str) -> bool:
    return any(module == bad or module.startswith(f"{bad}.") for bad in FORBIDDEN_MODULES)


def _dynamic_import_target(node: ast.Call) -> str | None:
    """Módulo literal de ``__import__("x")`` ou ``import_module("x")``, se houver."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name not in {"__import__", "import_module"} or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def forbidden_imports(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """Linhas e módulos proibidos importados em ``source``.

    Cobre ``import a.b``, ``from a import b`` (inclusive quando ``b`` é um
    submódulo proibido, como em ``from hyperliquid import exchange``) e import
    dinâmico com argumento literal. Import relativo é interno ao copylab e não
    conta. ``SyntaxError`` não é engolido: um arquivo que não parseia é falha.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, a.name) for a in node.names if _is_forbidden(a.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                continue
            if _is_forbidden(node.module):
                found.append((node.lineno, node.module))
                continue
            for alias in node.names:
                if _is_forbidden(f"{node.module}.{alias.name}"):
                    found.append((node.lineno, f"{node.module}.{alias.name}"))
        elif isinstance(node, ast.Call):
            target = _dynamic_import_target(node)
            if target is not None and _is_forbidden(target):
                found.append((node.lineno, target))
    return found


def source_files(root: Path) -> list[Path]:
    """Todo ``.py`` abaixo de ``root``, em ordem estável."""
    return sorted(root.rglob("*.py"))


def scan_tree(root: Path) -> list[Violation]:
    """Varre ``root`` e devolve cada import proibido encontrado."""
    return [
        (path, line, module)
        for path in source_files(root)
        for line, module in forbidden_imports(path.read_text(encoding="utf-8"), str(path))
    ]


# ─── 1. O detector, uma forma de import por vez ──────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "module"),
    [
        ("import web3", "web3"),
        ("import web3.eth", "web3.eth"),
        ("from web3 import Web3", "web3"),
        ("from web3.middleware import geth_poa_middleware", "web3.middleware"),
        ("import eth_account", "eth_account"),
        ("from eth_account import Account", "eth_account"),
        ("from eth_account.messages import encode_defunct", "eth_account.messages"),
        ("import eth_keys", "eth_keys"),
        ("import eth_keys.datatypes", "eth_keys.datatypes"),
        ("from eth_keys import keys", "eth_keys"),
        ("import hyperliquid.exchange", "hyperliquid.exchange"),
        ("from hyperliquid.exchange import Exchange", "hyperliquid.exchange"),
        ("from hyperliquid import exchange", "hyperliquid.exchange"),
        ("from hyperliquid import exchange as ex", "hyperliquid.exchange"),
        ("import web3 as w3", "web3"),
        ("def f() -> None:\n    import web3\n", "web3"),
        ("try:\n    import web3\nexcept ImportError:\n    pass\n", "web3"),
        ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import web3\n", "web3"),
        ("__import__('web3')", "web3"),
        ("import importlib\nimportlib.import_module('eth_account.signers')", "eth_account.signers"),
    ],
)
def test_detector_flags_every_form_of_forbidden_import(source: str, module: str) -> None:
    assert [m for _, m in forbidden_imports(source)] == [module]


@pytest.mark.unit
@pytest.mark.parametrize(
    "source",
    [
        "import hyperliquid.info",
        "from hyperliquid.info import Info",
        "from hyperliquid import info",
        "from hyperliquid.utils import constants",
        "import hyperliquid",
        "import web3_something_else",
        "import eth_account_fake",
        "from . import web3",
        "from .web3 import x",
        "import importlib\nimportlib.import_module('hyperliquid.info')",
        "import importlib\nimportlib.import_module(nome)",
        "web3 = 1\neth_keys = 2",
        "# import web3",
        "texto = 'import web3'",
    ],
)
def test_detector_does_not_flag_permitted_code(source: str) -> None:
    assert forbidden_imports(source) == []


@pytest.mark.unit
def test_detector_reports_the_line_number() -> None:
    assert forbidden_imports("import os\n\nimport web3\n") == [(3, "web3")]


@pytest.mark.unit
def test_unparseable_file_is_a_failure_not_a_silent_skip() -> None:
    with pytest.raises(SyntaxError):
        forbidden_imports("def (:\n")


# ─── 2. A caminhada de arquivos ──────────────────────────────────────────────


@pytest.mark.unit
def test_scan_tree_reaches_nested_subpackages(tmp_path: Path) -> None:
    clean = tmp_path / "ok" / "__init__.py"
    dirty = tmp_path / "pkg" / "deep" / "deeper" / "mod.py"
    clean.parent.mkdir(parents=True)
    dirty.parent.mkdir(parents=True)
    clean.write_text("import os\n", encoding="utf-8")
    dirty.write_text("x = 1\nfrom eth_keys import keys\n", encoding="utf-8")

    assert scan_tree(tmp_path) == [(dirty, 2, "eth_keys")]


# ─── 3. A varredura real, e os guardas de que ela enxerga tudo ───────────────


@pytest.mark.unit
def test_source_tree_has_no_order_or_signing_imports() -> None:
    violations = scan_tree(SRC_ROOT)
    report = "\n".join(
        f"  {path.relative_to(SRC_ROOT)}:{line} importa {module}"
        for path, line, module in violations
    )
    assert not violations, f"RNF-09 violado (ADR-0001):\n{report}"


@pytest.mark.unit
def test_scan_root_is_the_package_under_test() -> None:
    """A varredura olha o mesmo `copylab` que os outros testes importam."""
    assert (SRC_ROOT / "__init__.py").is_file()
    assert Path(copylab.__file__).resolve().parent == SRC_ROOT


@pytest.mark.unit
def test_scan_covers_every_expected_subpackage() -> None:
    """Cada subpacote declarado existe e tem ao menos um arquivo varrido."""
    scanned = set(source_files(SRC_ROOT))
    for name in EXPECTED_SUBPACKAGES:
        init = SRC_ROOT / name / "__init__.py"
        assert init in scanned, f"subpacote {name!r} não foi varrido (esperado {init})"
        assert any(SRC_ROOT / name in path.parents for path in scanned)


@pytest.mark.unit
def test_scan_covers_every_module_the_interpreter_can_find() -> None:
    """Visão independente: o que o `pkgutil` enumera precisa estar no que foi varrido.

    Cobre também subpacote novo que alguém crie e esqueça de listar em
    `EXPECTED_SUBPACKAGES`: ele aparece aqui mesmo assim.
    """
    scanned = set(source_files(SRC_ROOT))
    discovered = {name for _, name, _ in pkgutil.walk_packages(copylab.__path__, prefix="copylab.")}
    assert {f"copylab.{name}" for name in EXPECTED_SUBPACKAGES} <= discovered

    for name in discovered:
        spec = importlib.util.find_spec(name)
        assert spec is not None
        assert spec.origin is not None
        assert Path(spec.origin).resolve() in scanned, f"{name} não foi varrido"


# ─── 4. Os scripts de verificação (`scripts/**/*.py`) ────────────────────────


@pytest.mark.unit
def test_scripts_tree_has_no_order_or_signing_imports() -> None:
    violations = scan_tree(SCRIPTS_ROOT)
    report = "\n".join(
        f"  {path.relative_to(SCRIPTS_ROOT)}:{line} importa {module}"
        for path, line, module in violations
    )
    assert not violations, f"RNF-09 violado em scripts/ (ADR-0001):\n{report}"


@pytest.mark.unit
def test_scripts_scan_covers_every_expected_script() -> None:
    scanned = set(source_files(SCRIPTS_ROOT))
    assert scanned, "a varredura de scripts/ não encontrou nenhum arquivo"
    for name in EXPECTED_SCRIPTS:
        assert SCRIPTS_ROOT / name in scanned, f"script {name!r} não foi varrido"


@pytest.mark.unit
def test_scripts_scan_covers_every_python_file_on_disk() -> None:
    """Visão independente: `os.walk` enumera o que `rglob` deveria ter varrido.

    Pega um script novo que a varredura deixe de ver (por exemplo, por estar numa
    pasta que `source_files` passasse a filtrar).
    """
    on_disk = {
        (Path(folder) / name).resolve()
        for folder, _, names in os.walk(SCRIPTS_ROOT)
        for name in names
        if name.endswith(".py")
    }
    scanned = {path.resolve() for path in source_files(SCRIPTS_ROOT)}
    assert on_disk
    assert on_disk <= scanned, f"fora da varredura: {sorted(on_disk - scanned)}"
