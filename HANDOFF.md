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

---

# HANDOFF — Verificação de dados (prompt 02)

**Data:** 2026-10-06
**Escopo entregue:** os scripts de §4.1 (RF-VER-01 a RF-VER-04), a execução completa e o relatório
[`docs/verificacao-de-dados.md`](docs/verificacao-de-dados.md).
**Escopo deliberadamente não entregue:** qualquer coisa em `src/`, e qualquer alteração em `specs/`,
`CLAUDE.md` ou nos ADRs. A verificação mede e reporta; as emendas que ela sugere são da conversa
de arquitetura.

## 1. O que foi criado

| Arquivo | Conteúdo |
|---|---|
| `scripts/verify/run.py` | Orquestrador. Sobe o gravador em segundo plano, roda v01 a v04 e gera o relatório. Retomável: cache por arquivo e `results/<etapa>.json`. `--smoke` reduz tudo (3 carteiras, 2 min de gravação, 1 dia) e isola a saída em `data/verify/_smoke/` |
| `scripts/verify/v01_schema.py` … `v04_budget.py` | Um script por requisito, cada um com `--smoke` |
| `scripts/verify/record.py` | Gravador descartável de WebSocket (`l2Book`, `bbo`, `trades`; BTC, ETH, SOL; os dois timestamps) |
| `scripts/verify/common.py`, `analysis.py` | Infraestrutura (orçamento de peso, cliente, paginação) e funções puras de medição |
| `scripts/verify/report.py` | Gera o relatório a partir de `data/verify/results/` |
| `tests/unit/test_verify_helpers.py` | Testes das ferramentas de medição, com fixtures de papel (37 testes) |
| `tests/unit/test_architecture_read_only.py` | Estendido para varrer `scripts/**/*.py`, com guardas e prova de dente |
| `pyproject.toml`, `uv.lock` | Grupo `verify` (`httpx`, `websockets`, `polars`); nada no runtime |
| `docs/verificacao-de-dados.md` | O relatório |

Como refazer: `uv run python scripts/verify/run.py` (cerca de 1 h 15 min; reaproveita o que está em
`data/verify/`). Para refazer do zero, apague `data/verify/`.

## 2. Resultado e verificação

| Critério de pronto | Estado |
|---|---|
| Relatório cobre os 12 critérios, sem nenhum sem status | ✅ 8 `ok`, 1 `a emendar`, 2 `reprova`, 1 `não medido` |
| `make check` verde | ✅ 97 testes, `mypy --strict` e `ruff` limpos |
| Nenhum arquivo de `specs/` alterado | ✅ `git diff cc93868 HEAD -- specs CLAUDE.md` vazio |
| Nada de `data/` no git | ✅ `data/` no `.gitignore` |

Os dois `reprova` e o `não medido` são consequência de o dado real não atender à regra escrita, não de
falha do script: ver o relatório. O rate limit foi respeitado (0 HTTP 429; pico de 1.000 contra um orçamento
de 1.000 e um teto de 1.200).

### Provas de dente
- **RNF-09 em `scripts/`:** `import web3`, `eth_account`, `eth_keys`, `hyperliquid.exchange` e
  `from hyperliquid import exchange` plantados em `scripts/verify/` derrubaram o teste; `hyperliquid.info`
  passou. Encolher a varredura (`glob`, ignorar `verify`, ignorar pasta nova) derrubou os guardas. Detalhe na
  docstring do teste.
- **Ferramentas de medição:** orçamento sem teto, reconstrução sem o sinal do short, taxa só de saída tratada
  como todas e paginação sem multiconjunto de fronteira derrubam testes (mutações feitas à mão).

## 3. Decisões que tomei onde o prompt não decidia — revise

1. **Escopo de `mypy` e cobertura (adendo 1).** `make typecheck` continua em `src tests`; `scripts/verify/` tem
   type hints e passa no `ruff`, mas fora do `mypy` e da cobertura. Os testes de `test_verify_helpers.py`
   carregam `common.py` e `analysis.py` por caminho (`importlib`), e não por `import`, justamente para o `mypy`
   não seguir os scripts.
2. **Dados brutos e a regra 2 ("nada de desempenho").** O leaderboard é guardado só com `ethAddress` e
   `accountValue`: `windowPerformances` (PnL, ROI, volume) só teve a estrutura confirmada. Já os fills da janela
   de seleção ficam em `data/verify/fills/` **como a API os devolveu**, o que inclui o campo `closedPnl` de cada
   fill. Os dois pedidos do prompt (gravar amostras brutas; não gravar PnL) colidem aí, e escolhi o bruto porque a
   conta de CA-01.4 precisa dele e porque o diretório fica fora do git. Nenhum PnL derivado foi gravado, e
   `concordance` só devolve contagens. Se você preferir `closedPnl` removido do disco, é só reprocessar.
3. **Fills fora da janela de seleção.** De antes de 2026-07-01 e depois de 2026-09-01 guardam-se só contagem e,
   para os anteriores, o instante do mais antigo. O conteúdo foi descartado em memória.
4. **O teto de 10.000 não existe na paginação por tempo**, então a contagem de retenção para cedo ao passar de
   10.000 (um fill a mais já prova). Isso mudou o desenho no meio do caminho (ver §4).
5. **Dois denominadores em RF-VER-02.** A spec não define "notional negociado"; reportei as duas bases (todos os
   fills; só perpétuos do primeiro dex) e nenhuma foi escolhida.
6. **Acréscimos que a spec não pede:** uma segunda conexão com `l2Book` `fast: true` (para medir a premissa de
   meio segundo do ADR-0003); uma terceira hipótese (`net_close`), uma escada de tolerâncias e a conferência fill
   a fill em CA-01.4; a mesma medição de continuidade e de `closedPnl` na amostra maior de RF-VER-02, sempre
   rotulada como complemento; a contagem de fills de BTC, ETH e SOL na janela inteira para dimensionar o déficit de
   CA-03.1.
7. **Status adotados.** `reprova` para CA-03.1 (o prompt pediu "não satisfeito" quando não chega a 10.000);
   `não medido` para CA-03.2 enquanto a amostra for menor que 10.000, em vez de `ok` sobre n = 20; `ok` para
   CA-01.4 quando uma hipótese vence a segunda por 50 pontos percentuais (critério do script, não da spec).
8. **Orçamento de peso de 1.000 por minuto**, 200 abaixo do teto de 1.200, com reserva pessimista de 120 por
   página de fills e acerto pelo peso real.
9. **Amostragem.** Os endereços são ordenados antes do sorteio, para a ordem do leaderboard (que pode embutir
   ranking) não influenciar a amostra. A amostra depende do snapshot, que muda de hora em hora; o `sha256` do
   snapshot está no relatório.
10. **`ruff`:** `scripts/verify` entra em `src` (isort) e `report.py` fica isento de `E501` (Markdown em strings).
11. **Exploração.** Antes de escrever os scripts, fiz chamadas exploratórias de formato (estrutura do leaderboard,
    um fill de uma carteira da amostra, mensagens de WebSocket) com scripts fora do repositório; de fills só
    olhei chaves e tipos, sem imprimir `closedPnl`.

## 4. O que deu errado no caminho — registrado, não maquiado

- **Retenção.** O primeiro desenho paginava todo o histórico de cada carteira a partir de 0; uma carteira com
  31.331 fills gastou ~2.000 de peso para nada. Descobri ali que o teto de 10.000 não vale e passei a parar a
  contagem cedo.
- **Snapshot da assinatura.** A latência de `trades` no smoke dava p95 de 30 s: era a primeira mensagem da
  assinatura (um lote de negócios antigos). Ela passou a ficar fora das medidas de atraso e intervalo e de CA-01.5.
- **Classificação de ativos.** A execução completa foi feita com o código `cc93868`, que tratava moedas `#N`
  (tokens de resultado) como "perpétuo fora do meta". Corrigi no commit `ab19d51` e **refiz a análise offline**
  sobre os mesmos dados (nenhuma requisição nova à API de informação). A coleta de rede foi uma só (04:30 a
  05:30 UTC de 2026-10-06); a análise foi refeita três vezes, e o relatório registra o hash da última.
- **Uso da API na reanálise.** A reanálise zerou a tabela de requisições e peso; os valores da coleta (lidos do
  primeiro relatório) estão em `data/verify/results/api_usage.json`, e o gerador os lê de lá.

## 5. Em aberto

1. **A conversa de arquitetura.** O relatório traz dez pontos de contradição com a spec; nenhum foi tratado.
   Cada um precisa virar emenda ou ADR novo antes do design.
2. **Push.** O repositório `https://github.com/colletpedro/copylab` existe, mas **não fiz `push` nem adicionei o
   remote**: não foi pedido. É só dizer.
3. **Segunda rodada de RF-VER-03.** Para validar o proxy com 10.000 fills por ativo, a amostra de líderes
   precisaria crescer de 4 a 9 vezes; isso é decisão de escopo, não do script.
4. **Os pontos 1 a 4 do HANDOFF da Fase 0 (§5) continuam valendo:** tolerância ao exit 5 em
   `make test-integration`, templates com `quantlab`, CI nunca executado, cobertura trivial. O ponto 5 (typecheck
   de `scripts/verify/`) está resolvido pelo adendo (item 1 de §3).
5. **`data/verify/` ocupa ~200 MB** e está fora do git. Os fills brutos são reaproveitáveis pelo design.

## 6. Próximo passo

Levar `docs/verificacao-de-dados.md` à conversa de arquitetura **antes de qualquer outra coisa ser construída**,
e decidir, ponto a ponto, o que vira emenda de requisitos e o que vira ADR. Só depois o gate 2 (design).
