# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

O estado dos gates mora em [`specs/README.md`](../specs/README.md). Este arquivo diz
**onde o trabalho está**, não repete a tabela de gates.

## Onde estamos

**Fase 0 concluída (2026-10-05). Verificação de dados (RF-VER-01 a RF-VER-05) concluída em
2026-10-06**, com relatório em [`docs/verificacao-de-dados.md`](verificacao-de-dados.md). **Em
2026-10-07, os requisitos 1.3, o design 1.0, os ADRs 0006 a 0008 e o plano de tarefas 0.1 foram
aprovados**, e a implementação começou pelo Bloco 0 do plano (`specs/00-plataforma/fase-1-tasks.md`).
O repositório está publicado em `https://github.com/colletpedro/copylab`.
Detalhe, decisões e pendências em [`HANDOFF.md`](../HANDOFF.md).

| Item | Estado |
|---|---|
| Requisitos da Fase 1 | ✅ 1.3 aprovada (2026-10-07) |
| ADRs 0001 a 0005 | ✅ aceitos; 0001 e 0004 com errata de 2026-10-06, 0002 com erratas de 2026-10-06 e 2026-10-07, 0003 com duas de 2026-10-06 (corpo inalterado) |
| ADRs 0006 a 0008 | ✅ aceitos em 2026-10-07, com o gate de design. 0007 refina o 0002 (`N*`), 0008 refina o 0003 (execução sem preço em t + Δ) |
| Fundação (Fase 0) | ✅ `make check` verde; CI verde no GitHub |
| Verificação de dados (§4.1) | ✅ RF-VER-01 a 04 executadas: 8 `ok`, 1 `a emendar`, 2 `reprova`, 1 `não medido` |
| Verificação complementar (RF-VER-05) | ✅ executada em 2026-10-06: 4 `ok` |
| Design da Fase 1 | ✅ 1.0 aprovado (gate 2, 2026-10-07) |
| Plano de tarefas | ✅ 0.1 aprovado (gate 3, 2026-10-07) |
| Implementação | 🟡 Bloco 0 (T-001 a T-005) em andamento |
| Coletor prospectivo | ⬜ Bloco A, logo depois do Bloco 0 (ADR-0004) |

## Próximo

**Bloco 0 do plano de tarefas** (T-001 a T-005): acertos na fundação, `timeutil` e `clock`, `ports`,
núcleo de `storage` e `params`. Depois dele, o Bloco A (coletor), que precisa entrar em operação o quanto
antes.

## O que existe no código

- `src/copylab/{cli,config,logging,exceptions}.py` — infraestrutura, sem domínio.
- `src/copylab/{ingestion,collector,storage,selection,sim,analytics}/` — vazios, só
  `__init__.py` com uma docstring. Vazios **de propósito** (CLAUDE.md §1).
- `scripts/verify/` — código exploratório da verificação de dados (`run.py`, um script por
  requisito, gravador de WebSocket, gerador do relatório). Fora do `mypy` e da cobertura.
- `tests/unit/` — fumaça, `config`, `logging`, o teste de arquitetura de RNF-09 (agora também
  sobre `scripts/**`) e os testes das ferramentas de medição.
- `data/verify/` (fora do git, ~200 MB) — amostras brutas da verificação e resultados em JSON.

## Números

- 105 testes unitários, todos offline.
- Cobertura medida: 0 linhas em `selection`, `sim` e `analytics` (pacotes vazios). O
  100% reportado é trivial.
