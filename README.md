# copylab

Estudo de simulação de copy trading na Hyperliquid.

O objetivo do projeto **não** é achar um trader lucrativo. É construir um
**instrumento de medição confiável** e emitir um veredito mecânico contra um critério
fixado antes de os dados serem lidos: quanto do resultado de um trader sobrevive quando
ele é copiado por uma conta pequena, com atraso de segundos, taxas, funding, ordem
mínima e teto de alavancagem de 1x. "Copiar não compensa depois dos custos" é um
resultado válido e será reportado como tal.

Tudo aqui é somente leitura e simulado. Nenhuma chave privada, nenhuma assinatura e
nenhum endpoint de ordem existem no código, e um teste de arquitetura sobre os imports
garante isso (RNF-09).

---

## Estado atual

Fase 1 em implementação, pelo plano de tarefas aprovado. O que existe: a base (tempo,
relógio, protocolo de leitura com corte, armazenamento em Parquet com hash de conteúdo,
parâmetros pré-registrados em [`preregistro/parametros.toml`](preregistro/parametros.toml)),
o coletor do livro e dos negócios (`copylab collect`, roteiro em
[`docs/coletor.md`](docs/coletor.md)) e os scripts da verificação de dados. O que ainda não
existe: ingestão, livro-razão do líder, seleção, simulador, métricas e relatórios. Nenhum
resultado foi produzido.

O estado de cada gate e o roadmap estão em [`specs/README.md`](specs/README.md); onde o
trabalho está, em [`docs/STATE.md`](docs/STATE.md).

## Como rodar

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e `make`.

```bash
cp .env.example .env
```

```bash
make install
```

```bash
uv run python -m copylab version
```

O único comando que existe é `version`. Os de RF-CLI-01 (`ingest`, `collect`,
`select`, `evaluate`, `gate`) são escopo da Fase 1.

### Alvos do Makefile

| Alvo | O que faz |
|---|---|
| `make install` | Instala dependências de runtime e de desenvolvimento |
| `make test` | Suíte default com cobertura (integração desmarcada) |
| `make test-unit` / `make test-integration` | Recortes por marcador |
| `make lint` / `make format` | `ruff check` / `ruff format` |
| `make typecheck` | `mypy --strict` |
| `make audit` | `pip-audit` nas dependências instaladas |
| `make check` | **Portão local:** lint + typecheck + test — o mesmo que o CI roda |
| `make clean` | Remove caches e artefatos |

Não há `make up`, `down` nem `logs`: ainda não existe serviço.

## Estrutura

```
copylab/
├── CLAUDE.md                  # regras de trabalho e invariantes dos ADRs
├── CONTRIBUTING.md            # fluxo spec-driven e gates
├── HANDOFF.md                 # o que foi feito, decisões tomadas e pendências
├── docs/STATE.md              # mapa do projeto
├── specs/                     # fonte da verdade — leia antes de codar
│   ├── README.md              # fluxo, gates, índice de ADRs, roadmap
│   ├── CHANGELOG.md           # histórico de versões das specs
│   ├── 00-plataforma/         # requisitos da Fase 1
│   ├── adr/                   # decisões arquiteturais 0001 a 0005, imutáveis
│   └── _templates/            # esqueletos de requirements, design, tasks e ADR
├── src/copylab/
│   ├── cli.py                 # app Typer (comando `version`)
│   ├── config.py              # Settings via env (prefixo COPYLAB_)
│   ├── logging.py             # structlog: JSON ou console
│   ├── exceptions.py          # CopylabError, DataError, ConfigError, SimulationError
│   ├── ingestion/             # vazio — aguarda o design
│   ├── collector/             # vazio — aguarda o design
│   ├── storage/               # vazio — aguarda o design
│   ├── selection/             # vazio — aguarda o design
│   ├── sim/                   # vazio — aguarda o design
│   └── analytics/             # vazio — aguarda o design
└── tests/
    ├── conftest.py            # fixtures de infraestrutura
    └── unit/                  # rodam sempre, offline
```

## Specs e decisões

A pasta [`specs/`](specs/) é a fonte da verdade. Cinco decisões arquiteturais estão
fechadas e o código precisa respeitá-las:

- **[ADR-0001](specs/adr/0001-hyperliquid-como-fonte-de-sinal.md)** — fills públicos da
  Hyperliquid como fonte de sinal, somente leitura.
- **[ADR-0002](specs/adr/0002-espelhamento-por-exposicao-relativa-com-teto.md)** — o
  seguidor espelha a exposição relativa do líder, com teto de 1x.
- **[ADR-0003](specs/adr/0003-execucao-em-t-mais-delta-ao-pior-preco.md)** — o seguidor
  executa em t + Δ, ao pior preço observado. Invariante, não convenção.
- **[ADR-0004](specs/adr/0004-protocolo-de-avaliacao-em-duas-rotas.md)** — triagem
  retrospectiva e veredito prospectivo, com pré-registro.
- **[ADR-0005](specs/adr/0005-gate-do-piloto-por-consistencia.md)** — o gate do piloto é
  uma verificação de consistência, não evidência de que a cópia rende.

## Limitações conhecidas

Declaradas aqui porque um estudo que esconde suas premissas é pior que nenhum.

**Da Fase 0 (estado atual)**

- **Ainda não há resultado.** Nenhum dado foi ingerido, nenhuma carteira foi
  selecionada, nenhuma cópia foi simulada. Qualquer número que apareça neste
  repositório antes de existirem o design, o simulador e o congelamento não é um
  resultado do estudo.
- Nenhuma funcionalidade de negócio existe. O único comando é `version`.
- O piso de cobertura de 85% está configurado e escopado a `selection/`, `sim/` e
  `analytics/`, mas é **trivialmente satisfeito** enquanto esses pacotes estiverem
  vazios: com zero linhas medidas, o relatório de cobertura marca 100%. O piso só passa
  a significar alguma coisa quando houver código lá.
- Não há banco, serviço nem `docker-compose.yml`: a escolha de banco é decisão do
  design, que ainda não existe.
- O CI não foi executado: não há repositório remoto.

**Do desenho da Fase 1, já assumidas** (os requisitos, §6, e RF-ANA-06 têm a lista
completa)

- **Viés de sobrevivência** na lista de candidatas: o leaderboard é o de hoje.
- **Preço proxy e slippage por premissa** na Rota A.
- **Janela única de 30 dias**, dependente do regime de mercado, sem correção para
  múltiplas hipóteses.
- **Sem impacto de mercado** nem efeito de outros copiadores.
- **Custos fixos** de entrada e saída de capital não são modelados.
- **Coorte de uma única carteira** no cenário primário: um resultado positivo é
  indício, não prova.
