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

---

# HANDOFF — Publicação, emenda 1.1 e verificação complementar (prompt 03)

**Data:** 2026-10-06
**Escopo entregue:** repositório publicado com o CI verde; emenda 1.1 aplicada **como proposta**; RF-VER-05
executada e seção nova no fim de `docs/verificacao-de-dados.md`.
**Escopo deliberadamente não entregue:** aprovar a emenda, implementar qualquer coisa com base nela,
editar o conteúdo dos cinco arquivos dela.

## 1. O que foi feito

### Parte 1 — publicar
- `origin` = `https://github.com/colletpedro/copylab.git` e `git push -u origin main`. O prompt trazia
  `<URL_DO_REPOSITORIO>` literal; usei a URL que você tinha dado no prompt 02.
- **Primeira execução do CI: verde nos dois jobs** (`Lint, tipos e testes` e `Auditoria de dependências`,
  13 s cada). Só houve avisos de depreciação do Node 20 nas actions `setup-uv@v6` e `upload-artifact@v4` e um
  aviso de migração do `ubuntu-latest` para o Ubuntu 26 em 2026-10-19. Nada foi alterado no workflow.
- Assim que o repositório recebeu o `dependabot.yml`, o Dependabot abriu duas execuções (`uv` e
  `github-actions`). Não toquei em nenhum PR dele.

### Parte 2 — emenda 1.1
- **O que o prompt descrevia não era o que estava em disco.** Os cinco arquivos não estavam "por cima" das
  versões anteriores na raiz: estavam numa pasta `Emenda 1.1/` (não rastreada), com a mesma estrutura de
  caminhos. Como o destino de cada um é inequívoco, **copiei** os cinco para os mesmos caminhos (sem editar) e
  conferi o diff. Se a intenção era outra, é só dizer.
- `git diff --stat` mostrou **exatamente cinco arquivos**: `CLAUDE.md`, os requisitos e os ADRs 0001, 0003 e
  0004.
- **Nos três ADRs, 0 linhas removidas**; os acréscimos estão todos no fim, sob `## Errata — 2026-10-06`.
- Commits, um por assunto: requisitos (`c653897`), erratas (`4dd20d4`), `CLAUDE.md` (`60e9929`) e índices
  (`6499f78`: `specs/CHANGELOG.md`, `specs/README.md` e `docs/STATE.md`).
- **Decisões minhas nos índices:** na tabela de ADRs do `specs/README.md`, o status dos três passou a "aceito, com
  errata de 2026-10-06"; no roadmap, a linha de verificação e a de 1A passaram a dizer que a emenda está
  proposta. As entradas do CHANGELOG resumem a história de versões do próprio documento de requisitos.
- **Sobras não commitadas, de propósito:** `AGENTS.md` (já estava na pasta, não rastreado, e difere do
  `CLAUDE.md`) e a pasta `Emenda 1.1/`. Apague ou guarde, como preferir.

### Parte 3 — RF-VER-05
Os quatro critérios têm status `ok`. Os números e as seções "O que contradiz a spec" e "O que não foi possível
medir" estão no fim do relatório. Em uma frase cada:

| Critério | Resultado |
|---|---|
| CA-05.1 | A coleta paginou com início inclusivo e deduplicação. Recoletei as 7 carteiras com quebra com as fronteiras de página registradas: idênticas à primeira coleta. 0 de 100 quebras caem numa fronteira; 0 de 100 reconsultas (10 sorteadas + 90 de complemento) devolveram fill ausente. **A paginação não explica nenhuma quebra; a coleta não foi alterada** e as taxas de quebra seguem 0,82% e 0,16% |
| CA-05.2 | 978 episódios: mediana 0,002 bps, p95 0,40, p99 1,41, máximo 3,26; **1,7% acima de 1 bp** (abaixo dos 5% da emenda). Por carteira: **7 de 39 (17,9%)** teriam um episódio acima de 1 bp |
| CA-05.3 | `fundingHistory` devolveu 168 registros em 168 horas, um por hora; `time` cai de 0 a 127 ms depois do início da hora |
| CA-05.4 | F9 passa em 6 de 54 carteiras com BTC, ETH e SOL e em 24 de 54 com os 27 listados que têm equivalente na Binance. CASHCAT (9º) e PURR não têm equivalente |

## 2. Verificação

| Critério de pronto | Estado |
|---|---|
| `make check` verde | ✅ 105 testes, `mypy --strict` e `ruff` limpos |
| CI do GitHub verde | ✅ primeira execução, nos dois jobs |
| `pre-commit run --all-files` | ✅ |
| Cinco arquivos da emenda, sem edição | ✅ `git diff` conferido; ADRs só com acréscimos |
| Nada de `data/` no git | ✅ |

## 3. O que deu errado no caminho — registrado, não maquiado

- **Defeito na minha reconsulta.** A primeira versão somava as páginas sem deduplicar o milissegundo da fronteira.
  O complemento chegou a mostrar "4 consultas devolveram fill que faltava", todas de uma carteira com 10.694
  fills, e isso quase virou conclusão de que a coleta perdia fills. Era contagem em duplicata. Corrigi
  (`db946ac`), com teste de regressão que cai com o defeito, e **reexecutei** a RF-VER-05. Os números do
  relatório são os da versão corrigida.
- **Linha de base injusta.** A primeira comparação "quebras que atravessam fronteira" contra "pares íntegros que
  atravessam" misturava vãos de 1 posição com vãos de horas. Passou a comparar por faixa de vão.
- **Instrumentação da coleta.** `collect_fills` ganhou `boundaries`, `max_pages` e `truncated`. A coleta original
  não guardava as fronteiras; a instrumentação só acrescenta dado, e a recoleta idêntica nas 7 carteiras é a
  prova de que o comportamento não mudou.
- **Pipes em tabelas Markdown.** A regra de CA-05.2 trazia `|...|` dentro de uma célula e quebrava a tabela.
  Corrigi no gerador.

## 4. Em aberto

1. **A decisão sobre a emenda 1.1** (a conversa de arquitetura). A RF-VER-05 deixou quatro pontos para ela, listados
   em `docs/STATE.md` §"Próximo".
2. **Erratas versus supersedência.** O CLAUDE.md §2 diz que, quando uma decisão muda, escreve-se um ADR novo que
   declara supersedência. A errata do ADR-0001 diz que "deixa de valer" uma consequência do corpo (exclusão de
   carteiras com mais de 10.000 fills) e a substitui por outra. O corpo não foi editado, como o prompt exigia, mas
   vale decidir se isso é errata ou revogação.
3. **Os pontos 1 a 4 do HANDOFF da Fase 0 seguem valendo** (tolerância ao exit 5 em `make test-integration`,
   templates com `quantlab`, cobertura trivial); o CI nunca rodado deixou de valer, porque agora rodou e passou.
4. **Avisos do CI.** Node 20 deprecado nas actions e migração do `ubuntu-latest` em 2026-10-19. O Dependabot deve
   propor as atualizações.
5. **`AGENTS.md` e `Emenda 1.1/`** continuam não rastreados.

## 5. Próximo passo

Levar a seção nova de `docs/verificacao-de-dados.md` à conversa de arquitetura **junto com a decisão sobre a
emenda 1.1**. Só depois da aprovação, o gate 2 (design).

---

# HANDOFF — Requisitos 1.2, design 0.1 e ADRs 0006 a 0008 (prompt 04)

**Data:** 2026-10-06
**Escopo entregue:** os oito arquivos da entrega nos seus lugares, sem edição; índices e estado atualizados;
conferência cruzada dos documentos (§3 abaixo).
**Escopo deliberadamente não entregue:** qualquer implementação, dependência nova, `preregistro/`, `config/` ou
diretório de dados; mudança de status dos requisitos, do design ou dos ADRs 0006 a 0008. O gate é do Pedro.

## 1. O que foi feito

- A entrega estava em `entrega-04/`, com os caminhos do repositório. Copiei os oito arquivos e removi a pasta.
  `git diff --stat` mostrou quatro modificados (`CLAUDE.md`, requisitos, ADR-0002, ADR-0003) e quatro novos
  (design, ADRs 0006 a 0008), e nada mais.
- ADRs 0001, 0004 e 0005 sem diff. Nos ADRs 0002 e 0003, **0 linhas removidas**: um único bloco acrescentado
  depois da última linha (`@@ -72,0 +73,7` e `@@ -81,0 +82,4`).
- `specs/README.md`: tabela de estado (1.2 proposta, design 0.1 em revisão, tarefas não iniciadas), ADRs 0006 a
  0008 como propostos, 0002 e 0003 anotados como refinados por 0007 e 0008, regra de errata copiada de
  `CLAUDE.md` §2 sem reescrita, roadmap (verificação concluída; 1A aguarda o gate de design).
- `specs/CHANGELOG.md`: entradas de 2026-10-06 para requisitos 1.2, design 0.1, erratas, ADRs 0006 a 0008 e
  `CLAUDE.md`. O resumo dos requisitos sai da linha 1.2 do histórico do próprio documento.
- `Emenda 1.1/` removida: não versionada, cinco arquivos, todos idênticos (`cmp`) aos do `HEAD`.

## 2. Verificação

| Critério | Estado |
|---|---|
| `make check` | ✅ 105 testes, `ruff` e `mypy --strict` limpos (ver nota sobre `Phase 1 Design.md`) |
| Oito arquivos sem edição | ✅ copiados com `cp`; diff dos ADRs aceitos só com acréscimo |
| Nada implementado, nenhuma dependência | ✅ `src/`, `pyproject.toml` e `uv.lock` intocados |

**Nota.** Havia na raiz um `Phase 1 Design.md` não rastreado, que o prompt não cita, idêntico byte a byte ao
`fase-1-design.md` entregue. Ele derruba o `make lint` local (o `ruff format` tenta formatar o bloco Python dele;
`specs/` está excluída do formatador, a raiz não). Não está no git, então o CI não é afetado. Tirei-o da raiz só
para rodar o `make check` e o devolvi; não apaguei. Pergunta em aberto (§4).

## 3. Conferência cruzada

### 3.1 Itens mecânicos

1. **Critérios de RF-ING a RF-CLI no mapa de §8.2:** 112 critérios nos requisitos, 112 linhas no mapa. Nenhum
   critério sem linha; nenhuma linha que cite critério inexistente.
2. **Nomes de teste dos ADRs 0001 a 0008 em §8:** todos aparecem, escritos igual.
3. **Nome repetido no mapa para critérios diferentes:** nenhum.

Observações laterais: `test_evaluation_ingest_requires_freeze` (§8.1) não tem critério nos requisitos, porque a
guarda da ingestão só existe no texto de RF-CLI-01; e RF-COL-04 CA-04.2 ("dado 45 dias de execução, o disco está
dentro do orçamento") é uma aceitação operacional que o teste mapeado, de projeção, não prova sozinho.

### 3.2 Leitura do design contra os requisitos e os ADRs

> **Respondida (2026-10-07).** Cada item desta lista foi decidido na conversa de arquitetura e está
> respondido pelo design 0.2 e pelos requisitos 1.3 (ver o histórico dos dois documentos e o prompt 05 abaixo).

Em ordem decrescente de impacto, dentro de cada grupo.

**Contradições entre documentos**

1. **Redução pelo teto sem preço.** Design §4.3 passo 6: se a fonte não tem observação de `j` em `τ`, a redução
   "não é enviada e é contada". RF-SIM-02 CA-02.7 diz que "a única redução que fica sem enviar é a que cai abaixo
   da ordem mínima"; a errata do ADR-0002 e o `CLAUDE.md` §2 dizem o mesmo. O teste
   `test_cap_reduction_without_price_is_counted`, mapeado a CA-02.7, prova um caso que o critério diz não existir.
2. **Leitura de mercado da janela de avaliação antes do congelamento.** Design §3.3 isenta proxy e funding da
   guarda; §4.1 passo 3 e o exemplo de RF-CLI-01 (`ingest market --from 2026-07-01 --to 2026-09-30`) baixam
   setembro antes do congelamento da Rota A. ADR-0004 (pré-registro "antes de qualquer leitura da janela de
   avaliação"), o glossário (Congelamento), o DoD da Parte 1A e o `CLAUDE.md` §2 não fazem essa exceção. Falta
   decidir, por escrito, que ingerir dado de mercado não é "ler a janela", e o que impede de lê-lo.
3. **Hash de fills sem `seq` e resultado que depende de `seq`.** §3.2 exclui `seq` do hash "para não depender da
   ordem em que a API devolve os fills de um mesmo milissegundo". Mas `LeaderEvent.px` é o preço do *último* fill
   do evento (§3.5), e a continuidade (RF-ING-03 CA-03.1) percorre os fills na ordem de `seq`. Dois conjuntos com
   o mesmo hash podem dar eventos, `N*` e quebras diferentes, e `check_freeze` (RF-SEL-05 CA-05.2) não vê a
   diferença. O risco 10 de §7 cita a ordem, mas não essa consequência.
4. **Pacotes de lógica "recebem dados já materializados"** (§2.1, ADR-0006 decisão 7, `CLAUDE.md` §2), mas
   `candidate_assets`, `wallet_facts` e `check_freeze` (§3.6) recebem um `Repository`/`BoundedRepository` e leem
   sob demanda. Para tipar, `selection` importaria o protocolo de `storage`.
5. **`analytics/plot.py` grava arquivo** (§2.1), contra "quem grava é a CLI" (`CLAUDE.md` §2, ADR-0006) e contra o
   enunciado de `test_architecture_logic_packages_are_pure` ("não importam ... arquivo"). Devolver os bytes da
   imagem resolveria sem exceção.
6. **Limite de peso.** RF-ING-07 CA-07.1: "limite configurado (default 1.200)". Design §3.3: "o limite de trabalho
   é 1.000 por minuto". Não fica dito qual é o default configurado.
7. **Glossário desatualizado nos requisitos.** "Teto de alavancagem: máximo que o seguidor pode ter logo após
   executar as ordens de um evento". Depois de CA-02.7 (1.2), o excesso pode sobreviver a um evento.
8. **RF-SIM-03 CA-03.3** ainda diz "reavaliado no próximo evento"; CA-02.4 passou a "próximo evento daquele líder
   naquele ativo", e o design (§4.3 passo 9) segue CA-02.4. Profundidade excedida num aumento não é reavaliada num
   evento de outro ativo.
9. **Janela de seleção da Rota B.** §7.2: "os 62 dias anteriores ao congelamento". Design §4.1 passo 7: "os 62 dias
   que terminam no corte", com o corte antes do congelamento.
10. **Nomes de teste que descrevem o enunciado antigo.** `test_mutating_future_does_not_change_orders_decided_before_cutoff`
    prova agora "ordens executadas até c + Δ" (ADR-0008); `test_gross_exposure_never_exceeds_cap_after_event`
    prova agora "nenhuma ordem que aumenta passa do teto", e o excesso depois de um evento é permitido. Manter os
    nomes preserva a rastreabilidade com os ADRs aceitos, mas quem ler o nome entende outra coisa.
11. **Teste de RNF-09.** Design §2.1 e ADR-0001 chamam de `test_architecture_no_order_or_signing_imports` um teste
    "já existente". O existente se chama `test_source_tree_has_no_order_or_signing_imports`
    (`tests/unit/test_architecture_read_only.py`).
12. **`LookaheadError`.** O `CLAUDE.md` §3 já manda usá-la, mas ela não existe em `copylab.exceptions` (o design a
    cria). A docstring atual de `DataError` diz cobrir "leitura proibida", que se sobrepõe a ela.

**Assinaturas e tabelas de §3 que não sustentam um critério**

13. **`window open` decide o início da Rota B pelo relógio de quem roda** (§4.4 passo 1, `clock.now()`). Rodar o
    comando um dia depois do `push` muda o início da janela, contra a decisão 21 ("o início não pode ser escolha
    de quem roda") e RF-SEL-05 CA-05.3 ("posterior à publicação"). O git não registra o instante do `push`.
14. **Custos da Rota B.** `custos.json` é gravado uma vez e o comando recusa sobrescrevê-lo (§3.9). Ativos que
    entram no coletor no passo 7 de §4.1, para a Rota B, nunca terão meio-spread, e falham em RF-SEL-08 CA-08.1 (v);
    a perna do proxy de RF-SIM-03 CA-03.4 também precisa do slippage deles. Se a intenção é que o universo da Rota B
    seja subconjunto dos ativos medidos antes da Rota A, isso precisa estar escrito. Também não está dito que
    `costs measure` cobre BTC, de que o benchmark da Rota A precisa.
15. **Veredito da Rota A para o gate.** `pilot_gate(route_a: Verdict, ...)` precisa da condição (i), mas
    `evaluate` só grava relatório em texto. Não há artefato do veredito da Rota A definido para o `gate` ler.
16. **Métricas sem definição.** RF-ANA-01 lista "número de episódios copiados", "taxa de acerto por episódio" e
    "giro"; §3.8 não define nenhum, e RF-ANA-07 CA-07.1 depende de "episódios copiados". Em RF-ANA-04, não está
    dito qual notional do líder se atribui a uma ordem parcialmente cortada (mínimo, teto, profundidade). O "excesso
    contado" de CA-02.7 não tem unidade (eventos, dólares ou tempo).
17. **Composição da grade** (RF-SIM-08): fatorial (Δ × slippage × capital, 27 cenários) ou um fator por vez em
    torno do primário. Muda o custo das coortes de controle (§3.8) e o que o relatório mostra.
18. **`timeutil` não converte texto em instante.** `--cutoff 2026-10-20`, `--from/--to` (RF-CLI-01) e as datas de
    §7.2 no `parametros.toml` (o `tomllib` devolve `datetime.date`) precisam de conversão, e "só `timeutil` importa
    `datetime`". §3.1 só tem a direção contrária (`iso`).
19. **`clock` só tem `now() -> Ms`.** `WeightBudget` recebe um relógio `float` e um `sleep`; o coletor precisa de
    temporizador para os 10 s de silêncio e para o ping. Não está dito de onde vêm sem violar
    `test_architecture_time_boundary`, nem o que exatamente esse teste proíbe (`time`, relógio do laço `asyncio`).
20. **Relógio das lacunas.** Lacunas nascem do recebimento local (desconexão, silêncio), mas `BookSource` compara
    instantes da corretora (decisão 20). A tabela `gaps` não diz em que relógio estão `start_ms` e `end_ms`, nem se
    a lacuna por silêncio começa na última mensagem ou 10 s depois.
21. **Quais janelas um congelamento "cobre"** (§3.2). Só a de seleção, ou também a de avaliação? Na Rota B a
    janela de avaliação é ingerida dia a dia; uma reingestão depois do relatório mudaria o resultado sem que nada
    recusasse.
22. **`Freeze`** não tem campos definidos, e a "versão do código" de RF-SEL-05 CA-05.1 não tem fonte (SHA do
    `HEAD`? árvore suja recusada?).
23. **Ativos candidatos e download do proxy.** §4.1 passo 3 baixa o proxy "dos ativos candidatos", mas não diz que
    conjunto é esse, nem como se confere a condição (i) ("dados em todos os dias da janela") antes de baixar.
24. **Instantes futuros no laço.** `next_wake` e `available_from` devolvem instantes de eventos e observações
    posteriores a `τ − Δ`. RF-SIM-01 CA-01.3 diz que pedir "um evento do líder posterior a `τ − Δ`" levanta exceção.
    O design argumenta que só o instante vaza e que o teste de mutação o cobre; o critério, como escrito, não admite
    a exceção.
25. **Algoritmo de sorteio.** A semente está pré-registrada, mas o gerador, o embaralhamento e a derivação de um
    fluxo por rótulo (§3.6) não. Como o pool é pré-registrado, o algoritmo também precisa estar fixado antes da
    primeira seleção, ou vira um grau de liberdade.

**Passos de §4.3 que eu não saberia implementar sem perguntar**

26. **Passo 6 com sinais opostos.** O seguidor está comprado em `j` e `alvo_j` é negativo. "Redução até `alvo_j`"
    cruza o zero e abre posição num ativo sem evento, o que CA-02.2 proíbe ("só redução"). Reduz até zero, ou até
    `alvo_j`?
27. **Passo 6, quanto reduzir.** A redução vai até `alvo_j` inteiro, e não até o mínimo que devolve a carteira ao
    teto. CA-02.2 fala em "redução exigida pelo teto". Ir até o alvo gera o giro por deriva que a decisão 4 quer
    evitar. Confirmar qual das duas.
28. **Passo 8, valoração de `c`.** "Com `c` ao preço médio da ordem": a posição que já existia em `c` também é
    reavaliada a esse preço, em `P` e em `O`, como a fórmula de um nível sugere ("com `c` à cotação"), ou só a parte
    nova?
29. **Funding em §4.2.** No instante `H`, aplica-se o registro com `hour_ms = H` (pago em `H`, pela hora
    `[H − 1 h, H)`)? E no teste de mutação, "funding posterior" é julgado por `hour_ms` ou por `time_ms`, que cai
    de 0 a 127 ms depois da hora (RF-VER-05 CA-05.3)?

## 4. Em aberto

1. **O gate de design**: requisitos 1.2, design 0.1 e ADRs 0006 a 0008, com a lista de §3.2 acima.
2. **`AGENTS.md`**: não rastreado, mesmo conteúdo de abertura do `CLAUDE.md`. Perguntei se é seu; não versionei nem
   apaguei.
3. **`Phase 1 Design.md`** na raiz: cópia idêntica do design, não rastreada, derruba o `make lint` local. Aguarda
   confirmação para apagar.
4. **PRs do Dependabot** abertos, todos com CI verde nos dois jobs, sem merge: `actions/checkout` 5 → 7 (#1),
   `astral-sh/setup-uv` 6 → 7 (#2), `actions/upload-artifact` 4 → 7 (#3).
5. Os pontos herdados dos HANDOFFs anteriores continuam valendo (tolerância ao exit 5 em `make test-integration`,
   templates com `quantlab`, cobertura trivial, avisos do CI).

## 5. Próximo passo

Gate de design na conversa de arquitetura. Só depois dele, o plano de tarefas (`fase-1-tasks.md`).

---

# HANDOFF — Revisão do design: requisitos 1.3 e design 0.2 (prompt 05)

**Data:** 2026-10-07
**Escopo entregue:** os cinco arquivos da entrega nos seus lugares, sem edição; índices e estado; conferência
mecânica; limpeza da raiz; merge dos três PRs do Dependabot.
**Escopo deliberadamente não entregue:** qualquer implementação, inclusive as duas que o design 0.2 promete para a
primeira tarefa (renomear o teste de somente leitura e criar `LookaheadError`); dependência nova; `preregistro/`,
`config/` ou diretório de dados; mudança de status. O gate de design continua do Pedro.

## 1. O que foi feito

- A entrega estava em `entrega-05/`. Copiei os cinco arquivos e removi a pasta. `git diff --stat` mostrou cinco
  modificados e nada mais: `CLAUDE.md`, requisitos, design, ADR-0002 e ADR-0006.
- ADR-0002: **0 linhas removidas**, um bloco acrescentado depois da última linha (`@@ -79,0 +80,6`), sob
  `## Errata — 2026-10-07`. ADR-0006 (proposto): uma frase do item 7 da Decisão. ADRs 0001, 0003, 0004, 0005, 0007 e
  0008 sem diff.
- `specs/README.md` (1.3 proposta, 0.2 em revisão; ADR-0002 com duas erratas), `specs/CHANGELOG.md` (entradas de
  2026-10-07, resumidas das linhas 1.3 e 0.2 dos históricos) e `docs/STATE.md`.
- A lista de §3.2 do prompt 04 ficou marcada como respondida.
- **Limpeza.** `Phase 1 Design.md` e `AGENTS.md` apagados: nenhum dos dois era rastreado, e o Pedro não disse o
  contrário nesta sessão. Com isso o `make lint` local voltou a passar.
- **Dependabot.** Merge (squash) de um PR por vez, esperando o CI da `main` depois de cada um. Nenhum entrou em
  conflito, e o CI passou nos três:

| PR | Mudança | Commit na `main` | CI da `main` |
|---|---|---|---|
| #1 | `actions/checkout` 5 → 7 | `5971542` | ✅ |
| #2 | `astral-sh/setup-uv` 6 → 7 | `d17d9ad` | ✅ |
| #3 | `actions/upload-artifact` 4 → 7 | `0f6aa47` | ✅ |

## 2. Conferência mecânica

1. **Critérios de RF-ING a RF-CLI no mapa de §8.2:** 113 nos requisitos (entrou RF-SEL-05 CA-05.4), 113 linhas no
   mapa. Nenhum faltando, nenhum inexistente, nenhuma linha sem teste.
2. **Nomes de teste dos ADRs 0001 a 0008 em §8:** todos aparecem, escritos igual.
3. **Nome repetido no mapa para critérios diferentes:** nenhum.

**Fora disso, uma coisa saltou aos olhos (não corrigida).** O design 0.2 (§4.4, decisão 26) toma como instante de
publicação da Rota B o do commit do congelamento, lido do git. A data de um commit é a do relógio de quem commita
e pode ser escolhida (`GIT_COMMITTER_DATE`). O prazo de `window open` ("recusa a partir da primeira meia-noite UTC
posterior") limita o atraso, mas não impede um commit datado para trás. Talvez valha conferir a data do commit
contra o instante em que `window open` o vê no remoto.

## 3. Verificação

| Critério | Estado |
|---|---|
| `make check` local, inclusive `make lint` | ✅ 105 testes, `ruff` e `mypy --strict` limpos |
| Cinco arquivos sem edição | ✅ copiados com `cp`; ADR-0002 só com acréscimo |
| CI da `main` depois de cada merge | ✅ nos três |

## 4. Em aberto

1. **O gate de design**: requisitos 1.3, design 0.2 e ADRs 0006 a 0008.
2. Os pontos herdados dos HANDOFFs anteriores (tolerância ao exit 5 em `make test-integration`, templates com
   `quantlab`, cobertura trivial). O aviso de Node 20 nas actions deve ter sumido com os três PRs; conferir no
   próximo CI.

## 5. Próximo passo

Gate de design na conversa de arquitetura. Só depois dele, o plano de tarefas (`fase-1-tasks.md`), cuja primeira
tarefa renomeia o teste de somente leitura e cria `LookaheadError`.

---

# HANDOFF — Aprovações e Bloco 0 (prompt 06)

**Data:** 2026-10-07
**Escopo:** registrar as aprovações do gate de design e do plano de tarefas; implementar o Bloco 0 do plano
(T-001 a T-005).
**Fora do escopo, de propósito:** tudo do Bloco A em diante (coletor, clientes HTTP e WebSocket, simulador).

## 1. Parte 1 — documentos

- A entrega estava em `entrega-06/`, com os caminhos do repositório. Copiei os seis arquivos e removi a pasta.
  `git diff --stat` mostrou cinco modificados (requisitos, design, ADRs 0006 a 0008) e um novo
  (`fase-1-tasks.md`), e nada mais.
- Nos três ADRs, o diff é só a linha de status (`proposto — ...` para `aceito (2026-10-07, ...)`).
- No plano de tarefas, a única edição: status `aprovado — gate 3 em 2026-10-07`.
- Índices: `specs/README.md` (requisitos 1.3 e design 1.0 aprovados, tarefas aprovadas, implementação em
  andamento; ADRs 0006 a 0008 aceitos; roadmap 1A em implementação), `specs/CHANGELOG.md` e `docs/STATE.md`.
- **`Phase 1 Tasks.md` na raiz**, não rastreado: idêntico ao `fase-1-tasks.md` entregue, exceto pela linha de
  status que eu editei depois. Não apaguei (ver §Em aberto).

## 2. Parte 2 — Bloco 0

| Tarefa | Entrega | Testes com nome do design | Prova de dente |
|---|---|---|---|
| T-001 | Teste de RNF-09 renomeado; `LookaheadError`; docstring de `DataError`; subpacote `leader`; `copylab.leader` em `source_pkgs` | `test_architecture_no_order_or_signing_imports` | refeita com o nome novo |
| T-002 | `timeutil` (assinaturas de §3.1) e `clock` (`now`, `monotonic`, `sleep`) | `test_architecture_time_boundary` | sim |
| T-003 | `ports`: `Repository` e `BoundedRepository` | `test_selection_reading_at_or_after_cutoff_raises` (parte do repositório; a parte da seleção chega com T-066) | sim |
| T-004 | `polars` por `uv add`; `COPYLAB_DATA_DIR`; `storage`: diretório, partições, escrita atômica, hash de conteúdo, `Writer`, trechos gravados e janelas congeladas | `test_content_hash_ignores_file_bytes_and_row_order`, `test_interrupted_write_leaves_previous_table_intact`, `test_frozen_rows_are_never_rewritten`, `test_architecture_storage_isolation`, `test_architecture_logic_packages_are_pure` | sim, nos cinco |
| T-005 | `preregistro/parametros.toml` e `params.py` | (o teste de comportamento dos limiares, `test_thresholds_come_only_from_parameter_file`, é de T-063) | transcrição e hash |

Cada prova de dente está na docstring do arquivo de teste: a mutação, o que caiu e o que não caiu.
Duas mutações sobreviveram na primeira tentativa e mudaram o código ou os testes, e não a docstring:

- No hash de conteúdo, tirar a normalização de `-0.0` em `_canonical_float` não derrubava nada:
  a normalização que importa é a de antes da ordenação, e o ramo era código morto. Saiu, e a
  mutação passou a ser feita onde vale.
- Em `params`, tirar `sort_keys` do hash não derrubava nada: o dump segue a ordem dos campos no
  modelo, não a do arquivo. Entrou `test_hash_is_the_documented_canonical_json`, que fixa a
  codificação e cai com a mutação.

## 3. Decisões que tomei onde o design não decidia — revise

Em ordem decrescente de impacto.

1. **Trecho já coletado (T-004) — perguntei.** O design diz que, em janela congelada, "mudar ou
   inserir linha num trecho já coletado" não é permitido, mas não diz como o núcleo genérico sabe o
   que foi coletado. **O Pedro escolheu:** storage registra os trechos. Cada escrita declara o
   intervalo `[início, fim)` que descreve por inteiro e substitui as linhas dele; a partição guarda
   os trechos gravados nos metadados do próprio Parquet (`copylab.spans`), para o registro e os
   dados mudarem na mesma troca de nome. Na interseção de janela congelada com trecho já gravado,
   o gravado fica; o que diverge volta em `WriteOutcome` (`frozen_kept`, `frozen_rejected`, como
   multiconjuntos de linhas inteiras) e é logado. A tabela `divergences`, com campo a campo, é de
   T-023.
2. **Hash de conteúdo, versão 1.** O design fixa o princípio; a codificação é minha e está na
   docstring de `storage/hashing.py`: SHA-256; linhas ordenadas pelas chaves e, no desempate, pelas
   demais colunas por nome; serialização por coluna, com os nomes das colunas, uma letra de
   categoria de tipo, um byte de validade por linha e os valores (inteiros em 64 bits com sinal,
   flutuantes em IEEE 754 com `-0.0` normalizado *antes* da ordenação e NaN canônico, textos com
   prefixo de tamanho). Tipos fora disso são `DataError`. **Desempenho:** sem `numpy` (o design o
   permite só em `sim` e `analytics`), a conversão é pela `array` da biblioteca padrão, em blocos
   de 2²⁰ linhas. Para o livro, com centenas de milhões de linhas, pode ficar lento; medir em
   T-012 ou T-072.
3. **`test_architecture_time_boundary` segue a lista de permissão do design**, que é mais estrita
   que o mínimo do prompt: `clock` só em `collector`, `ingestion` e `cli` (e não só "proibido nos
   quatro de lógica"), e `asyncio` só no coletor, que está na mesma frase de §2.1.
4. **Pureza da lógica.** Proibidos em `leader`, `selection`, `sim` e `analytics`: `storage`,
   `ingestion`, `collector`, `clock`, `cli`; rede (`socket`, `ssl`, `http`, `urllib`, `httpx`,
   `requests`, `websockets`, `aiohttp`, `asyncio`); arquivo (`os`, `pathlib`, `shutil`,
   `tempfile`, `glob`, `fileinput`, `sqlite3`, `pickle`, `shelve`); `subprocess`; a chamada `open`
   e qualquer identificador `read_*`, `scan_*`, `write_*` e `sink_*`. **`io` fica permitido**,
   porque o gráfico devolve a imagem por `BytesIO`. Isolamento do armazenamento: fora de `storage`,
   nada de `pyarrow`, `fastparquet`, `*_parquet*`, `data_dir` ou o texto `COPYLAB_DATA_DIR`;
   `config` pode declarar `data_dir`.
5. **Os três testes de arquitetura novos ficam num arquivo só**
   (`test_architecture_boundaries.py`), com um detector que resolve import relativo
   (`from .. import clock`) e olha identificadores e textos, além de imports. O de RNF-09 continua
   no arquivo dele.
6. **`polars` em `ports` só sob `TYPE_CHECKING`.** O protocolo não precisa dele em tempo de
   execução, e o plano põe `polars` em T-004, depois de T-003. Ele continua também no grupo
   `verify` (duplicata inofensiva).
7. **`COPYLAB_DATA_DIR` sem default.** Sem a variável, abrir o armazenamento é `ConfigError`, em
   vez de gravar num diretório escolhido por acaso.
8. **Arquivos.** `<diretório>/<tabela>/<partes>.parquet`, zstd, temporário oculto na mesma pasta,
   `fsync` do arquivo e da pasta. Nome de tabela pode ter `/` (`raw/leaderboard`); nenhuma parte
   pode ser vazia, começar por ponto ou conter separador. As linhas ficam em ordem de instante,
   estável dentro do mesmo instante.
9. **`BoundedRepository`.** Levanta com `end > cutoff` (com janela semiaberta, `end == cutoff` lê
   só instantes < T). `content_hash` é cortado pelo nome da tabela, e tabela fora de
   `leaderboard`, `meta` e `roles` é cortada, inclusive uma que ainda não exista.
10. **`timeutil`.** `iso` no formato `2026-09-01T00:00:00.123Z`. `parse_utc_date` só aceita
    `AAAA-MM-DD`. `from_date` recusa o que não for exatamente uma data (um `datetime` é subclasse
    de `date`). Erros de data são `ConfigError`, porque vêm de argumento ou do arquivo de
    parâmetros.
11. **`parametros.toml`.**
    - Chaves em inglês, como o resto do código; comentários em português, citando a linha da spec.
      Unidade no nome da chave; porcentagens como a spec as escreve (`_pct = 95.0`), e não como
      fração.
    - As janelas da Rota A estão como a spec as escreve (primeiro e último dia, e o número de dias),
      e o carregador confere as contagens e converte em `[início, fim)`. A grade de capital traz K
      por extenso (1/2/5) e é conferida contra a fórmula de D14.
    - Δ em segundos, como na spec, com propriedades em ms.
    - F3 não tem chave própria: usa `ingestion.max_fills_per_wallet` e
      `reconciliation.pnl_tolerance_bps`.
    - F1 é `"user"`, o valor que a API devolve para usuário comum (medido na verificação).
    - A composição da grade de cenários é estrutura, não valor, e fica no código de T-052.
    - Tipos estritos: texto, booleano ou float no lugar de inteiro são `ConfigError`; inteiro num
      campo de dinheiro é aceito como float, com o mesmo hash. Chave desconhecida é erro.
    - Hash: SHA-256 de um marcador e do JSON canônico do modelo (chaves em ordem, datas em `Ms`).
12. **Regra de nomes da Binance.** Só o prefixo `k` minúsculo vira `1000` (`KAITO` não muda).
    **Lista de exceções vazia**: os 27 ativos da verificação seguem a regra.

## 4. Verificação

| Critério | Estado |
|---|---|
| `make check` | ✅ 290 testes, `ruff` e `mypy --strict` limpos, piso de cobertura atingido (trivial: os quatro pacotes medidos ainda estão vazios) |
| Testes de invariante novos com a mutação na docstring | ✅ os sete do Bloco 0 |
| Commits por caminho, sem `git add .`/`-A`/`commit -a` | ✅ |
| Nada do Bloco A em diante | ✅ nenhum cliente HTTP ou WebSocket, nenhum simulador |
| CI depois do `push` | ✅ execução 37642547677, sobre `9269f89`: os dois jobs verdes |

**O que deu errado no caminho.** O commit de T-003 foi feito uma vez com o `make lint` vermelho: o
`grep` no fim do encadeamento engoliu o código de saída do `make`. O commit ainda não estava
publicado; corrigi o teste e fiz `--amend`. A partir dali, todo commit ficou condicionado ao
código de saída do `make check`.

O `push` foi recusado quatro vezes pelo GitHub com `remote rejected (Internal Server Error)`, inclusive com um
único commit de documentação, com o status do GitHub normal e o `--dry-run` passando. Na quinta tentativa,
minutos depois, passou sem nenhuma mudança. Foi do lado do servidor.

## 5. Em aberto — perguntas para a conversa de arquitetura

1. **Limiares fora de §7.2 e §7.3.** O design diz que nenhum limiar aparece como literal no
   código, e o prompt mandou pôr no arquivo só §7.2 e §7.3. Ficaram de fora, por isso: os 95% de
   cobertura da medida de custo (RF-COL-05 CA-05.2), os 10 s de silêncio que fazem lacuna
   (RF-COL-02 CA-02.2), o limite de peso de 1.000 por minuto (RF-ING-07 CA-07.1, "limite
   configurado"), a página de 2.000 fills e a reserva de 120 de peso (design §3.3), os 45 dias da
   projeção de disco e os 30 GB de RNF-10. Eles vão para `parametros.toml` (e entram no hash do
   congelamento) ou para `Settings`? O primeiro a precisar disso é o coletor (10 s), em T-012.
2. **F6, fronteiras.** "Entre 1 hora e 7 dias": inclusivo nas duas pontas? T-063 precisa saber.
3. **Exceções de nome da Binance.** Lista vazia, porque a verificação não achou nenhuma. Confirmar.
4. **`Phase 1 Tasks.md`** na raiz, não rastreado, cópia do plano entregue. Apago?
5. **`README.md` está desatualizado desde a Fase 0** ("Estado atual — Fase 0", árvore com
   "aguarda o design", "não há banco... decisão do design"). Não o reescrevi, porque não estava no
   escopo. O DoD da Parte 1C pede o README final; vale um acerto antes disso?
6. Herdados: a tolerância ao exit 5 em `make test-integration` e os templates com `quantlab`.

## 6. Próximo passo

Responder as perguntas de §5, em especial a 1, e então o Bloco A (coletor), para ligar o coletor
(M-A) o quanto antes.

---

# HANDOFF — Respostas do Bloco 0 e Bloco A, coletor (prompt 07)

**Data:** 2026-10-07
**Escopo:** Parte 0 (respostas às perguntas do Bloco 0) e Bloco A do plano (T-010 a T-014).
**Fora do escopo, de propósito:** ingestão, seleção, simulador, `costs measure`, conferência do livro
contra o proxy. O coletor **não ficou rodando**: quem liga é o Pedro, pelo roteiro.

## 1. Parte 0

| Item | Feito |
|---|---|
| 1. Design 1.1 | Copiado; diff com os quatro trechos (§2.2, §3.6, §3.9, histórico) e a linha de versão. `entrega-07/` removida. Índices atualizados |
| 2. Onde mora cada número | `parametros.toml`, seção `[book_record]`: `max_book_silence_s = 10` e `cost_min_day_coverage_pct = 95.0` (a cobertura em porcentagem, como `route_b.min_book_coverage_pct`; é o 0,95 do prompt). `Settings`: `weight_limit_per_minute` (1.000, recusa acima de 1.200), `disk_budget_gb` (30) e `disk_projection_days` (45). A página de 2.000 fills fica para o provedor (Bloco B) |
| 3. F6 inclusivo | Comentário no `parametros.toml`; a regra entra no código com T-063 |
| 4. Exceções da Binance | Lista vazia, comentário com a confirmação |
| 5. `Phase 1 Tasks.md` | Apagado (não era rastreado) |
| 6. README | Só a seção de estado, em poucas linhas, com ponteiro para `specs/README.md` |
| 7. Hash de conteúdo | **0,160 s** para 500 mil linhas com as colunas de `bbo` (melhor de 3; dado sintético com semente). Abaixo de 2 s: **não vetorizei e `numpy` não entrou**. Para referência, 500 mil linhas de `trades`, com dois endereços em texto por linha: 0,434 s |

## 2. Bloco A

| Tarefa | Entrega | Testes com nome do design |
|---|---|---|
| T-010 | `storage/segments.py` (segmentos brutos) e `collector/recorder.py` (gravador) | `test_recorder_writes_bbo_and_fast_book_with_both_timestamps_compressed`, `test_restart_neither_duplicates_nor_corrupts_segments` |
| T-011 | Reconexão com recuo dobrado (1 s até 60 s) e evento por desconexão | `test_disconnect_reconnects_and_records_gap_per_asset` (de ponta a ponta, com a compactação) |
| T-012 | `collector/compact.py`: `bbo`, `book`, `trades` e `gaps` | `test_gaps_are_recorded_in_exchange_time`, `test_book_silence_over_10s_is_gap_and_trades_silence_is_not`, `test_trades_are_recorded_with_both_addresses_and_timestamps` |
| T-013 | `collector/status.py` | `test_status_reports_gap_free_fraction_per_asset`, `test_latency_report_gives_median_p95_p99`, `test_status_projects_disk_usage_against_budget` |
| T-014 | `config/collector_assets.toml` (27 ativos, conferidos contra a tabela de CA-05.4 e a lista do prompt), `collector/assets.py`, `collector/service.py`, comandos `collect`, `collect status`, `collect compact`, `docs/coletor.md` para Windows | `test_collector_list_is_the_27_assets_of_the_verification` (BTC na lista, RF-SEL-08 CA-08.5 na parte do coletor) |

Formato e limites conferidos na documentação oficial da Hyperliquid antes do código: assinatura
`{"method":"subscribe","subscription":{...}}`; `l2Book` com `"fast": true` dá 5 níveis; `users` é
`[comprador, vendedor]`; ping `{"method":"ping"}`, e a corretora fecha a conexão com 60 s sem mensagem do
cliente; por IP, 1.000 assinaturas, 10 conexões e 30 conexões novas por minuto.

Cada teste de invariante tem a mutação na docstring. Uma mutação sobreviveu na primeira tentativa (status
com `live_conn=None`): o cenário só tinha reconexão; entrou o caso de uma conexão que continua viva.

## 3. Decisões que tomei onde o design não decidia — revise

Em ordem decrescente de impacto.

1. **Partição das tabelas do livro pelo dia de recebimento.** O design diz "ativo, dia" sem dizer o
   relógio. Perguntei, sem resposta. Segui o texto de §3.4 ("converte os segmentos fechados
   de um dia nas tabelas"): os segmentos são horas de recebimento, então a partição é o dia deles. Assim a
   compactação é idempotente e a contagem bate linha a linha. Quem ler pelo instante da corretora (T-080)
   lê também a partição seguinte e filtra por `time_ms`. **Confirmar.**
2. **Coluna `conn_ms` nas três tabelas**, além das do design: o instante de abertura da conexão que
   trouxe a linha. A regra de lacuna precisa saber se houve desconexão entre duas mensagens do livro,
   inclusive na virada do dia, e depois da compactação a tabela é o único registro. Sem a coluna, a
   desconexão sumiria com os segmentos.
3. **Identidade da conexão = instante em que ela abriu**, gravado em cada registro do segmento.
   Desconexão entre duas mensagens é troca de conexão entre elas, inclusive queda do processo.
4. **Segmentos em `storage`**, não no coletor: só `storage` conhece o diretório de dados e o formato
   (ADR-0006, `test_architecture_storage_isolation`). O coletor entrega bytes e instantes. Registro
   `<recebimento>\t<conexão>\t<tamanho>\t<bytes>\n`, com o tamanho explícito para não depender de a
   mensagem não ter quebra de linha. Cada descarga é um membro gzip completo, com CRC e `fsync`;
   "bloco íntegro" é membro que descomprime e confere. Nome `<hora>.<abertura>.jsonl.gz`, com sufixo
   `.open` em escrita: dois segmentos da mesma hora (reinício no meio dela) nunca colidem.
5. **Família de eventos** (`_events`): conexões, desconexões, paradas e as mensagens da corretora que não
   são de um ativo assinado (resposta de assinatura, `pong`, erro), intactas. A compactação não as
   apaga: são pequenas e são a única memória dos motivos de cada queda.
6. **Primeira mensagem de cada assinatura**: é a primeira de um ativo e canal trazida por uma conexão.
   A conexão viva na virada do dia é lida da última linha gravada do dia anterior. **Caso de borda
   aceito:** se uma conexão aberta segundos antes da meia-noite só trouxe o retrato naquele canal antes
   dela, a primeira mensagem dela no dia seguinte também é descartada. Perde-se uma mensagem, não se
   inventa nenhuma.
7. **Lacuna no fim da gravação.** A lacuna termina na primeira mensagem *mantida* depois dela (o retrato
   da reconexão é descartado). No status, o silêncio desde a última mensagem do livro, acima do limite,
   conta como lacuna em curso: com o coletor parado, a cobertura cai, como deve.
8. **Números de operação novos em `Settings`** (design 1.1 §3.9): descarga a cada 5 s, conexão dada por
   morta com 30 s sem mensagem, recuo de 1 s a 60 s. O ping a cada 20 s e a espera de 1 s pelo
   fechamento da conexão são constantes com a fonte no comentário. A espera de 1 s entrou depois do
   primeiro teste do roteiro: o padrão de 10 s do `websockets` atrasava cada parada em 10 s, e numa
   reconexão viraria lacuna.
9. **Um gravador por diretório de dados**, com trava (`fcntl`; `msvcrt` no Windows). Compactação só de dias encerrados e sem
   segmento aberto (um segmento deixado por queda é fechado pelo gravador ao reiniciar).
10. **Projeção de disco**: bytes de segmentos e tabelas, divididos pelo tempo desde o primeiro evento
    gravado, vezes o horizonte. Latência por posto mais próximo, sem interpolação.
11. **Sem job de integração no CI.** O comentário do workflow dizia que ele entraria com o primeiro
    teste de integração. O único fala com a corretora real; num runner dos EUA, país que a Hyperliquid
    restringe, deixaria o CI dependente de rede externa. Roda à mão com `make test-integration`, que
    perdeu a tolerância a "nada coletado" e passou a usar `-s` para mostrar o log.
12. **Saída dos comandos** pelo structlog, uma linha por ativo, como manda o CLAUDE.md. Erro de
    configuração ou de dado sai com código 1 e mensagem, sem traceback.
13. **Windows nativo** (a resposta do Pedro, que chegou no fim da sessão). Quatro adaptações, sem mudar o
    comportamento em macOS e Linux: trava com `msvcrt`; parada por `Ctrl+C` como cancelamento do laço,
    porque o asyncio do Windows não aceita tratador de sinal (a parada fica registrada e os segmentos
    fecham); pasta não sincronizada depois da troca de nome, que o Windows não permite; e troca de nome
    retentada por até 2 s quando outro processo segura o arquivo (status, antivírus, indexador), com a
    espera dada pelo coletor, porque `storage` não lê o relógio. `:` saiu dos nomes aceitos de segmento.
    Encerrar a tarefa pelo Agendador mata o processo: perde-se o não descarregado (até 5 s), e a próxima
    subida recupera o segmento.
14. **Job de Windows no CI**, só com a suíte unitária: é o único lugar onde os caminhos acima rodam. Na
    primeira execução ele achou três defeitos dos testes (queda simulada com o arquivo ainda aberto no
    próprio processo; porta fechada, que no Windows demora ~2 s a recusar; logging escrevendo no stdout
    fechado do `CliRunner`), todos corrigidos. A queda agora é de verdade, num processo filho.

## 4. Verificação

| Critério | Estado |
|---|---|
| `make check` | ✅ 348 testes, `ruff` e `mypy --strict` limpos |
| Integração (60 s de BTC na corretora real) | ✅ rodou duas vezes; a segunda com `-s`, só para ver os números (a primeira passou, mas o log ficou capturado). Mensagens: `bbo` 480, livro 110 (1,8/s, a assinatura rápida), negócios 72 (149 negócios), eventos 7. Nenhuma lacuna. Latência mediana dos negócios: 306 ms |
| Roteiro seguido do zero | 🟡 **em macOS, não em Windows**: não tenho uma máquina Windows. Segui, num clone limpo, a parte comum a todos os sistemas: instalar, `.env`, `collect --duration-seconds 120`, `collect status` (cobertura de 100% nos 27 ativos), `collect` parado por `SIGTERM` (parada limpa, código 0), `collect compact` (nada a fazer: o dia não fechou). Nenhum processo ficou rodando. **A seção 6 (Agendador de Tarefas, `powercfg`, compactação agendada) não foi executada por ninguém ainda**: o código dela roda na suíte do runner Windows, mas os comandos de PowerShell do roteiro, não |
| CI | ✅ execução 37682403020, sobre `9553a15`: lint, tipos e testes; Windows; auditoria |

**Disco: risco que o M-A precisa medir.** Dois minutos dos 27 ativos ocuparam 0,94 MB de segmentos gzip,
o que projeta **28,5 GB em 45 dias**, contra um orçamento de 30 GB. Compactados numa cópia, os mesmos dados
deram 0,87 MB em Parquet (28,2 GB projetados), mas com 2 minutos por arquivo o custo fixo de cada Parquet
pesa muito, e a medida não decide nada. O número que vale é o do fim do primeiro dia, com partições do dia
inteiro, depois da primeira compactação: é a regra do M-A (passou de 30 GB, volta para a arquitetura).

## 5. Em aberto — perguntas para a conversa de arquitetura

1. **A seção 6 do roteiro nunca rodou num Windows.** O Pedro respondeu Windows no fim da sessão. O código
   foi adaptado e passa no runner Windows, mas a tarefa do Agendador, o `powercfg` e a compactação agendada
   precisam ser conferidos na máquina, na primeira vez que forem seguidos. Se algum comando falhar, é para
   corrigir o roteiro antes de qualquer outra coisa.
2. **Partição pelo dia de recebimento** (§3, item 1): confirmar ou mandar trocar antes do M-A, enquanto não
   há dado compactado.
3. **Coluna `conn_ms`** (§3, item 2): o design §3.2 lista as colunas; esta é uma a mais. Vale uma linha no
   design.
4. **Janelas congeladas na compactação.** A CLI abre o armazenamento sem janelas congeladas, porque ainda
   não existe congelamento nem leitor deles (T-066). Quando existir, `collect compact` precisa recebê-las.
5. **Conferência da cópia por hash** (design §3.4): o roteiro usa `rsync --checksum` até a leitura do
   livro existir (T-080).
6. O Bloco A não tem a medida de custo (`costs measure`, T-062), que depende de três dias de gravação.

## 6. O que o Pedro precisa fazer para ligar o coletor

1. Na máquina secundária (Windows), seguir `docs/coletor.md` das seções 1 a 4: instalar Git e `uv`, clonar
   em `C:\copylab`, `uv sync`, criar o `.env` com `COPYLAB_DATA_DIR=C:/copylab-dados` (30 GB livres) e
   `COPYLAB_ENV=prod`, rodar o teste de dois minutos e conferir o status.
2. Seção 6, num PowerShell como administrador: registrar a tarefa `copylab-coletor` (sobe com a máquina,
   volta se cair), desligar a suspensão com `powercfg` e registrar a tarefa `copylab-compactacao` (00:15
   UTC). Conferir com `Get-ScheduledTaskInfo` e com o log em `C:\copylab-dados\logs\coletor.log`.
3. No fim do primeiro dia, depois da primeira compactação, rodar `uv run copylab collect status` e anotar
   `projected_gb` (M-A). Acima de 30 GB, volta para a conversa de arquitetura.
