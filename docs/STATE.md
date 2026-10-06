# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

O estado dos gates mora em [`specs/README.md`](../specs/README.md). Este arquivo diz
**onde o trabalho está**, não repete a tabela de gates.

## Onde estamos

**Fase 0 (fundação) concluída em 2026-10-05.** Repositório, ambiente, CI, convenções,
templates de processo e esqueleto de pacote estão de pé. Nenhum código de domínio
existe. Detalhe, decisões e pendências em [`HANDOFF.md`](../HANDOFF.md).

| Item | Estado |
|---|---|
| Requisitos da Fase 1 | ✅ aprovados, versão 1.0 |
| ADRs 0001 a 0005 | ✅ aceitos |
| Fundação (Fase 0) | ✅ `make check` verde |
| Verificação de dados (§4.1) | ⬜ não iniciada |
| Design da Fase 1 | ⬜ aguarda a verificação de dados |
| Plano de tarefas | ⬜ |
| Implementação | ⬜ |
| Coletor prospectivo | ⬜ (primeira coisa a entrar em operação, ADR-0004) |

## Próximo

**Verificação de dados** (RF-VER-01 a RF-VER-04), por scripts em `scripts/verify/`, fora
de `src/`. É a única área que roda antes do design, porque o design depende do que ela
medir. O relatório vai para `docs/` e é entrada do design.

## O que existe no código

- `src/copylab/{cli,config,logging,exceptions}.py` — infraestrutura, sem domínio.
- `src/copylab/{ingestion,collector,storage,selection,sim,analytics}/` — vazios, só
  `__init__.py` com uma docstring. Vazios **de propósito** (CLAUDE.md §1).
- `tests/unit/` — fumaça, `config`, `logging` e o teste de arquitetura de RNF-09.

## Números

- 57 testes unitários, todos offline.
- Cobertura medida: 0 linhas em `selection`, `sim` e `analytics` (pacotes vazios). O
  100% reportado é trivial.
