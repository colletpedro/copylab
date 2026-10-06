# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

O estado dos gates mora em [`specs/README.md`](../specs/README.md). Este arquivo diz
**onde o trabalho está**, não repete a tabela de gates.

## Onde estamos

**Fase 0 concluída (2026-10-05). Verificação de dados (RF-VER-01 a RF-VER-04) executada em
2026-10-06**, com relatório em [`docs/verificacao-de-dados.md`](verificacao-de-dados.md). **Emenda 1.1
dos requisitos proposta, aguardando aprovação** (2026-10-06): ela resolve os dez pontos em que a
verificação contradisse a spec e acrescenta RF-VER-05. Nenhum código de domínio existe em `src/`.
O repositório está publicado em `https://github.com/colletpedro/copylab`, e o primeiro CI passou.
Detalhe, decisões e pendências em [`HANDOFF.md`](../HANDOFF.md).

| Item | Estado |
|---|---|
| Requisitos da Fase 1 | 🟡 1.0 aprovada; **emenda 1.1 proposta, aguardando aprovação** |
| ADRs 0001 a 0005 | ✅ aceitos; 0001, 0003 e 0004 com errata de 2026-10-06 (corpo inalterado) |
| Fundação (Fase 0) | ✅ `make check` verde; CI verde no GitHub |
| Verificação de dados (§4.1) | ✅ RF-VER-01 a 04 executadas: 8 `ok`, 1 `a emendar`, 2 `reprova`, 1 `não medido` |
| Verificação complementar (RF-VER-05) | ⬜ proposta na emenda 1.1; execução em curso |
| Design da Fase 1 | ⬜ aguarda a aprovação da emenda 1.1 |
| Plano de tarefas | ⬜ |
| Implementação | ⬜ |
| Coletor prospectivo | ⬜ (primeira coisa a entrar em operação, ADR-0004) |

## Próximo

1. Rodar a verificação complementar RF-VER-05 (quebras e paginação, divergência de PnL sobre o notional,
   funding, ativos e F9). Ela alimenta a decisão sobre a emenda.
2. **Conversa de arquitetura:** decidir a aprovação da emenda 1.1, com o relatório e a seção de RF-VER-05.
   Nada é implementado com base na emenda enquanto ela estiver só proposta.

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
