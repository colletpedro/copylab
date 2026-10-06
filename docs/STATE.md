# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

O estado dos gates mora em [`specs/README.md`](../specs/README.md). Este arquivo diz
**onde o trabalho está**, não repete a tabela de gates.

## Onde estamos

**Fase 0 (fundação) concluída em 2026-10-05. Verificação de dados (§4.1) executada em
2026-10-06**, com relatório em [`docs/verificacao-de-dados.md`](verificacao-de-dados.md). Nenhum
código de domínio existe em `src/`. Detalhe, decisões e pendências em
[`HANDOFF.md`](../HANDOFF.md).

| Item | Estado |
|---|---|
| Requisitos da Fase 1 | ✅ aprovados, versão 1.0 (nenhuma emenda feita: a verificação só reporta) |
| ADRs 0001 a 0005 | ✅ aceitos |
| Fundação (Fase 0) | ✅ `make check` verde |
| Verificação de dados (§4.1) | ✅ executada; **dos 12 critérios: 8 `ok`, 1 `a emendar`, 2 `reprova`, 1 `não medido`** (tabela no relatório) |
| Design da Fase 1 | ⬜ aguarda a conversa de arquitetura sobre o relatório |
| Plano de tarefas | ⬜ |
| Implementação | ⬜ |
| Coletor prospectivo | ⬜ (primeira coisa a entrar em operação, ADR-0004) |

## Próximo

**Conversa de arquitetura sobre o relatório de verificação**, antes de qualquer outra coisa ser
construída. O relatório lista, na seção "O que contradiz a spec", dez pontos em que o dado real
difere do que os requisitos ou os ADRs assumem (teto de 10.000 fills que não se aplica,
conciliação de `closedPnl` na tolerância de 1e-6, quebras de continuidade, cobertura do
universo, cadência do `l2Book`, entre outros). Eles precisam virar emenda de spec ou ADR novo
**antes** do design. A verificação não alterou nenhuma spec.

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

- 97 testes unitários, todos offline.
- Cobertura medida: 0 linhas em `selection`, `sim` e `analytics` (pacotes vazios). O
  100% reportado é trivial.
