# Contribuindo

copylab é **spec-driven**: `specs/` é a fonte da verdade, e código sem spec aprovada
não entra. Este documento descreve o fluxo e os gates. As convenções de código e os
invariantes estão em [CLAUDE.md](CLAUDE.md), que vale também para quem não é agente.

## O fluxo

Cada módulo passa por quatro etapas, nesta ordem:

| # | Etapa | Artefato | Template |
|---|---|---|---|
| 1 | **Requisitos** | O que o módulo faz, em linguagem de negócio, com critérios de aceitação testáveis em Dado/Quando/Então | [`specs/_templates/requirements.md`](specs/_templates/requirements.md) |
| 2 | **Design** | Arquitetura, interfaces públicas, schemas, decisões com alternativas descartadas | [`specs/_templates/design.md`](specs/_templates/design.md) |
| 3 | **Tarefas** | Tarefas pequenas, ordenadas por dependência, com critério de verificação | [`specs/_templates/tasks.md`](specs/_templates/tasks.md) |
| 4 | **Implementação** | Código e testes | — |

Antes de escrever código de um módulo, leia, nesta ordem: `specs/README.md`, o
`requirements.md` da fase, **todos** os ADRs em `specs/adr/`, e `docs/STATE.md` e
`HANDOFF.md`.

**Exceção declarada:** a verificação de dados (§4.1 dos requisitos da Fase 1) roda
antes do design, em `scripts/verify/`, fora de `src/`. Ela mede e reporta; não decide
nada e não altera spec.

## Os gates

Cada transição é um **gate check** explícito. Um gate reprovado volta para a etapa
anterior — não se avança com pendência aberta.

**Gate 1 — requisitos → design.** Todo critério de aceitação é falseável (dá para
imaginar o teste que o quebra). A seção de questões em aberto está vazia. Premissas e
vieses estão declarados.

**Gate 2 — design → tarefas.** Toda interface pública tem assinatura tipada e contrato.
Cada invariante tem um teste nomeado que o prova. Decisões caras de reverter viraram
ADR, não parágrafo.

**Gate 3 — tarefas → implementação.** Cada tarefa cabe em um commit, tem critério de
verificação objetivo e não depende de nada inexistente. Todo RF da spec é coberto por
ao menos uma tarefa.

**Gate 4 — implementação → merge.** O checklist do
[template de PR](.github/pull_request_template.md), integralmente: spec aprovada, os
ADRs 0001 a 0005 respeitados, testes que falhariam sem a mudança, e cobertura de pelo
menos 85%, com ramos, em seleção, simulador e analytics.

Descobrir no meio da implementação que a spec está errada é normal e esperado. O
caminho é **voltar, corrigir a spec, e só então mexer no código** — nunca ajustar o
código e deixar a spec desatualizada.

## ADRs

Decisão arquitetural cara de reverter vira um ADR em [`specs/adr/`](specs/adr/), a
partir de [`specs/_templates/adr.md`](specs/_templates/adr.md).

ADRs são **numerados e imutáveis**. Quando uma decisão muda, cria-se um ADR novo
declarando supersedência do anterior; o antigo não é editado nem removido. O histórico
de decisões revertidas faz parte do que este repositório demonstra.

Alternativa descartada precisa aparecer com a **sua força**, não como espantalho. Se
você não consegue escrever o que a alternativa tem de bom, você não a avaliou.

## Rodando localmente

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e `make`.

```bash
cp .env.example .env
```

```bash
make install
```

```bash
uv run pre-commit install
```

Depois disso, `make check` antes de cada commit. É o mesmo que o CI roda.

Dependências entram por `uv add` (ou `uv add --dev`), nunca editando `pyproject.toml`
na mão sem atualizar `uv.lock`.

A suíte default roda **offline** (RNF-06). Teste que precisa de rede ou serviço
externo leva `@pytest.mark.integration` e roda por `make test-integration`.

## Commits e PRs

- Commits pequenos, um assunto cada, mensagem no imperativo dizendo **por quê**.
- **Nunca `git add .`**, nem `git add -A`, nem `git commit -a` — adicione arquivo por
  arquivo, pelo caminho.
- Prefixos: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.
- Não commite dado de mercado nem `.env`. Arquivos de congelamento e relatórios de
  veredito são commitados de propósito.
- Não reescreva histórico já publicado.
- O PR aponta a spec e os critérios de aceitação que cobre. Sem isso, não há como
  revisar contra o quê.
- Atualize `specs/CHANGELOG.md` quando uma spec ou ADR mudar de versão ou status, e
  `specs/README.md` quando um gate mudar de estado.

## Uma regra sobre resultados

Este projeto mede uma estratégia de cópia. Um resultado ruim é um resultado: se a
cópia perde para comprar e manter BTC, reporte assim. Nunca ajuste uma premissa, uma
janela ou um limiar para melhorar um número, e nunca leia a janela de avaliação antes
do congelamento. Todo relatório declara seus vieses (RF-ANA-06) — é isso que separa um
instrumento de medição de uma peça de marketing. Um resultado bom demais merece mais
desconfiança que um ruim: suspeite primeiro de lookahead ou de erro de fator.
