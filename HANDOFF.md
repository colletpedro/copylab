# HANDOFF — Fase 0 (fundação)

**Data:** 2026-10-05
**Escopo entregue:** repositório, ambiente, CI, convenções, templates de processo e
esqueleto de pacote.
**Escopo deliberadamente não entregue:** qualquer lógica de domínio.

Os subpacotes `ingestion/`, `collector/`, `storage/`, `selection/`, `sim/` e
`analytics/` estão vazios porque o gate de design da Fase 1 não foi feito. Os
requisitos (versão 1.0) e os ADRs 0001 a 0005 estão aprovados; o design não existe.

---

## 1. O que foi criado

| Arquivo | Conteúdo |
|---|---|
| `.python-version`, `.gitignore` | Python 3.12. Ignora `.env`, caches, `data/` e `output/` |
| `pyproject.toml`, `uv.lock` | `hatchling`, layout `src/copylab`, script `copylab = "copylab.cli:app"`. Runtime: `typer`, `pydantic`, `pydantic-settings`, `structlog`. Dev: `pytest`, `pytest-cov`, `pytest-mock`, `mypy`, `ruff`, `pre-commit`, `pip-audit`, `pytest-randomly` |
| `Makefile` | `help install test test-unit test-integration lint format typecheck audit check clean`. Sem `up`, `down` e `logs` |
| `.env.example`, `.pre-commit-config.yaml`, `.github/dependabot.yml` | Adaptados do quantlab, prefixo `COPYLAB_` |
| `.github/workflows/ci.yml` | Jobs `quality` (lint, typecheck, test, artefato de cobertura) e `audit` (informativo). Sem integração |
| `.github/pull_request_template.md`, `CONTRIBUTING.md` | Checklist com os ADRs 0001 a 0005 e piso de 85% |
| `src/copylab/` | `__init__`, `__main__`, `py.typed`, `cli.py` (comando `version`), `config.py`, `logging.py`, `exceptions.py` |
| `src/copylab/{ingestion,collector,storage,selection,sim,analytics}/` | Só `__init__.py` com docstring de uma linha |
| `tests/` | `conftest.py`; `unit/test_smoke.py`, `test_config.py`, `test_logging.py`, `test_architecture_read_only.py` |
| `specs/_templates/` | Os quatro templates do quantlab, byte a byte (`cmp`) |
| `specs/CHANGELOG.md` | Entradas de 2026-10-05: requisitos 1.0 e ADRs 0001 a 0005 |
| `specs/README.md` | Só a linha da Fase 0 no roadmap |
| `README.md`, `docs/STATE.md`, `HANDOFF.md` | Estado, como rodar, limitações |

`CLAUDE.md`, os requisitos e os ADRs entraram no histórico exatamente como recebidos e
não foram editados.

## 2. Verificação final

Executada em 2026-10-05, macOS, Python 3.12.3 no venv do projeto, uv 0.11.15.

| # | Passo | Resultado |
|---|---|---|
| a | `rm -rf .venv && make install` | ✅ exit 0 |
| b | `UV_OFFLINE=1 make check` (depois de a) | ✅ exit 0: ruff limpo, `mypy --strict` sem erro em 17 arquivos, 57 testes, piso de 85% atingido |
| c | `uv run python -m copylab version` | ✅ `copylab.version version=0.1.0` |
| d | `uv run pre-commit run --all-files` | ✅ 8 hooks `Passed`, nenhum arquivo versionado modificado |
| e | `make audit` | ✅ nenhuma vulnerabilidade conhecida |
| f | Suíte com seeds 1, 42 e 999 do `pytest-randomly`, e em ordem fixa | ✅ 57 passaram em todas |
| g | `make test-unit`, `make test-integration` | ✅ 57 selecionados; integração informa "nenhum teste ainda" |

**O CI não foi executado.** Não há remote, e o prompt proibia criá-lo. O workflow foi
validado só por inspeção e porque invoca os mesmos alvos do Makefile que passaram acima.

### Prova de dente dos testes de invariante

CLAUDE.md §3 exige que um teste de invariante prove que cai quando deve. Feito à mão e
restaurado; os detalhes estão nas docstrings:

- **Arquitetura (RNF-09):** um arquivo `src/copylab/sim/_dente.py` com `import web3`,
  `from eth_account import Account`, `import eth_keys.datatypes`,
  `from hyperliquid.exchange import Exchange` e `from hyperliquid import exchange` fez
  `test_source_tree_has_no_order_or_signing_imports` falhar, apontando `sim/_dente.py:1`.
  `from hyperliquid.info import Info` não falhou, como deve ser.
- **Guardas de cobertura da varredura:** encolher `source_files` para ignorar
  `selection`, renomear `collector`, e trocar `rglob` por `glob` derrubaram os guardas.
- **Logging:** `cache_logger_on_first_use=True` derruba
  `test_reconfiguring_applies_to_a_logger_already_used`.

---

## 3. Decisões que tomei onde o prompt não decidia — revise

Em ordem decrescente de impacto.

### 3.1 O repositório não tinha `CLAUDE.md` nem `specs/` na raiz

O prompt dizia que o repositório "já contém `CLAUDE.md` e `specs/`". Em disco, eles
estavam em `copylab_base/`, e havia cinco `.md` soltos na raiz (cópias renomeadas dos
mesmos documentos e dos prompts 01 e 02). Perguntei, e a resposta foi:

- `copylab/` é a raiz do repositório. Movi com `mv` (nada apagado)
  `copylab_base/CLAUDE.md` e `copylab_base/specs/` para a raiz, e removi a pasta
  `copylab_base/`, já vazia.
- Os cinco `.md` soltos foram movidos para `../copylab_prompts/`, **fora** do
  repositório: `Copy Trading Automation.md` (cópia do `CLAUDE.md`),
  `Copy Trading Automation Requirements.md` (cópia dos requisitos),
  `Gate do Piloto Consistency.md` (cópia do ADR-0005), `Fundacao - Copy Trading
  Automation.md` (prompt 01) e `Data Verification.md` (prompt 02).

### 3.2 Cobertura com os pacotes medidos vazios

O quantlab resolveu isso na Fase 0 sem baixar o piso e sem tirar pacotes: o piso fica
configurado (`fail_under`, `source_pkgs`, `branch = true`) e `skip_empty = true` faz o
relatório pular os `__init__.py` sem instruções. Os pacotes medidos têm **zero
instruções**, então o total é 0/0 e o relatório marca 100%. O piso é satisfeito
**trivialmente** e só passa a significar algo quando houver código nos três pacotes.

Repliquei a mesma solução. `fail_under = 85` e `source_pkgs = ["copylab.selection",
"copylab.sim", "copylab.analytics"]` estão intactos. A saída mostra
`3 empty files skipped`, o que confirma que os três pacotes estão sendo medidos. A
limitação está declarada no `README.md`.

### 3.3 `Settings` e `logging.py` (diferem do quantlab de propósito)

- O quantlab lia `QUANTLAB_ENV` com `os.getenv` dentro de `logging.py`. CLAUDE.md §3
  proíbe `os.getenv` espalhado, então `env` virou campo de `Settings`, `Settings.json_logs`
  decide o formato, e `logging.py` **não lê o ambiente**: recebe `level` e `json_logs`.
- Nível de log inválido virou `ConfigError` ("Input should be 'DEBUG', 'INFO', ..."), em
  vez de cair em silêncio em `INFO` como no quantlab. Qualquer `ValidationError` de
  `Settings` vira `ConfigError` com o nome da variável `COPYLAB_*`.
- `Settings` só tem `log_level` e `env`. Nada de domínio: parâmetro pré-registrado vem do
  arquivo de parâmetros (RF-SEL-02 CA-02.2), e um campo aqui seria um segundo caminho
  para mudá-lo.
- `get_logger` devolve `FilteringBoundLogger`, que é o que `make_filtering_bound_logger`
  de fato entrega. O quantlab anotava `stdlib.BoundLogger`, o que não corresponde.
- `cache_logger_on_first_use=False`, como pedido.

### 3.4 Escolhas menores

- **Versão em dois lugares** (`pyproject.toml` e `__version__`), como no quantlab. Nada as
  sincroniza, então `test_version_in_code_matches_installed_metadata` impede a divergência.
- **Omiti do `pyproject.toml`** o `pythonpath = ["."]` e o override do `yfinance`, que
  eram do quantlab e não se aplicam, e os stubs `types-pyyaml` e `pandas-stubs`.
  `pytest-mock` ficou no grupo `dev` como no quantlab, ainda sem uso.
- **Pin do ruff no pre-commit** em `v0.16.10`, a mesma versão que o `uv.lock` resolveu. O
  molde tinha `v0.14.5`, que poderia formatar diferente do `make lint`. Ao atualizar o
  lock, atualize o pin.
- **Teste de arquitetura:** além de `import`/`from ... import`, ele cobre
  `__import__("x")` e `import_module("x")` com literal. Import dinâmico com argumento
  calculado **não é decidível por AST e passa**; está declarado na docstring.
- **CI:** mesmas versões de actions do quantlab (`checkout@v5`, `setup-uv@v6`,
  `upload-artifact@v4`) e `uv 0.11.15`. No quantlab, o Dependabot propôs versões novas
  logo no primeiro dia; espere o mesmo aqui.
- **`.gitignore`:** ignora `data/` e `output/`. Não repliquei `reports/`, `*.png`, `*.pdf`
  nem a exceção para `results/`, porque o relatório de veredito e o congelamento
  (`preregistro/`) são commitados de propósito.
- **Template de PR:** os itens de data naive do quantlab viraram "tempo é inteiro de
  milissegundos UTC" (RNF-07), e entraram exceções da hierarquia do projeto, parâmetro
  pré-registrado e a prova de dente.
- **`CHANGELOG`:** o texto das duas entradas sai do histórico do próprio documento de
  requisitos (§10) e dos ADRs; não acrescentei nada que eles não digam.
- **`# type: ignore[misc]`** em um único teste (`test_settings_are_immutable`), com
  comentário: mypy recusa a atribuição a um modelo `frozen`, e o teste prova que o runtime
  também recusa.
- **Sem `tests/__init__.py`**, como na Fase 0 do quantlab. Se aparecer um segundo
  `conftest.py` (integração), `explicit_package_bases` no mypy já está configurado.

---

## 4. O que deliberadamente NÃO foi feito

- Nenhum código nos subpacotes vazios, nem como esboço.
- `docker-compose.yml` e `Dockerfile`: a escolha de banco é decisão do design.
- Dependência de domínio: SDK da Hyperliquid, pandas, drivers de banco, clientes HTTP ou
  WebSocket.
- `scripts/verify/` e qualquer parte da verificação de dados (§4.1): é o prompt 02.
- `push` e repositório remoto. `git add .`, `git add -A` e `git commit -a` não foram usados.
- `CLAUDE.md`, requisitos e ADRs não foram alterados.

## 5. Em aberto

1. **Remover a tolerância ao exit 5 em `make test-integration`** quando entrar o primeiro
   teste de integração. Enquanto ela existir, apagar todos os testes de integração passaria
   despercebido. O alvo tem um comentário dizendo isso.
2. **Os templates `design.md` e `tasks.md` ainda citam `quantlab` e Mongo** em
   placeholders (`src/quantlab/<...>`, "Documentos Mongo", `quantlab.exceptions`). Foram
   copiados sem alteração, como pedido. Ajustar é decisão para quando o primeiro design
   for escrito.
3. **O CI nunca rodou.** A primeira execução real é quando houver remote.
4. **A cobertura de 85% é trivial** até haver código em `selection`, `sim` e `analytics`.
5. **`make typecheck` roda só em `src tests`.** `scripts/verify/` (prompt 02) ficaria fora
   do `mypy --strict` e dentro do `ruff`. Decidir, ao criá-lo, se entra no typecheck.
   Quase certamente exigirá dependências que o prompt 01 proibiu (cliente HTTP).
6. **`make install` não instala os hooks do git.** `uv run pre-commit install` é um
   comando à parte, documentado no CONTRIBUTING. Eu rodei `pre-commit run --all-files`,
   mas não instalei os hooks no `.git/hooks`.
7. **Um `ConfigError` no CLI aparece como traceback do Typer.** A mensagem é acionável,
   mas o ideal é o CLI capturá-la e sair com código 1. É decisão da spec do CLI
   (RF-CLI-01 CA-01.2).
8. **`../copylab_prompts/`** guarda os cinco `.md` soltos fora do repositório. Apague ou
   guarde, como preferir.

### Ideias anotadas, não implementadas (CLAUDE.md §1)

- Um teste de arquitetura análogo ao de RNF-09 para RNF-07 e RNF-01: nenhum `datetime`
  sem fuso e nenhuma chamada a `now()` fora de `collector/`. Só faz sentido quando houver
  código; hoje seria um teste que varre arquivos vazios.

## 6. Próximo passo

**Prompt 02 — verificação de dados** (§4.1 dos requisitos, RF-VER-01 a RF-VER-04), por
scripts em `scripts/verify/`, fora de `src/`. Pré-requisito atendido: `make check` está
verde. O relatório vai para `docs/` e é entrada do design.
