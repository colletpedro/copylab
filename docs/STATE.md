# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

O estado dos gates mora em [`specs/README.md`](../specs/README.md). Este arquivo diz
**onde o trabalho está**, não repete a tabela de gates.

## Onde estamos

**Fase 0 concluída (2026-10-05). Verificação de dados (RF-VER-01 a RF-VER-05) concluída em
2026-10-06**, com relatório em [`docs/verificacao-de-dados.md`](verificacao-de-dados.md). **Requisitos
1.3 propostos, design 0.2 em revisão e ADRs 0006 a 0008 propostos** (2026-10-07): os quatro aguardam
o mesmo gate, o de design. Nenhum código de domínio existe em `src/`.
O repositório está publicado em `https://github.com/colletpedro/copylab`, e o primeiro CI passou.
Detalhe, decisões e pendências em [`HANDOFF.md`](../HANDOFF.md).

| Item | Estado |
|---|---|
| Requisitos da Fase 1 | 🟡 1.0 aprovada; **versão 1.3 proposta**, aguardando o gate de design |
| ADRs 0001 a 0005 | ✅ aceitos; 0001 e 0004 com errata de 2026-10-06, 0002 com erratas de 2026-10-06 e 2026-10-07, 0003 com duas de 2026-10-06 (corpo inalterado) |
| ADRs 0006 a 0008 | 🟡 propostos; passam a aceitos com a aprovação do design. O 0006 teve o item 7 da Decisão ajustado em 2026-10-07 (protocolo de leitura). 0007 refina o 0002 (`N*`), 0008 refina o 0003 (execução sem preço em t + Δ) |
| Fundação (Fase 0) | ✅ `make check` verde; CI verde no GitHub |
| Verificação de dados (§4.1) | ✅ RF-VER-01 a 04 executadas: 8 `ok`, 1 `a emendar`, 2 `reprova`, 1 `não medido` |
| Verificação complementar (RF-VER-05) | ✅ executada em 2026-10-06: 4 `ok` (seção no fim do relatório). Nenhuma quebra de continuidade é explicada pela paginação; 1,7% dos episódios passam de 1 bp do notional (7 de 39 carteiras com ao menos um) |
| Design da Fase 1 | 🟡 0.2 em revisão (`specs/00-plataforma/fase-1-design.md`), aguardando o gate 2 |
| Plano de tarefas | ⬜ |
| Implementação | ⬜ |
| Coletor prospectivo | ⬜ (primeira coisa a entrar em operação, ADR-0004) |

## Próximo

**Gate de design, na conversa de arquitetura.** Aprova-se ou devolve-se, no mesmo gate, os requisitos
1.3, o design 0.2 e os ADRs 0006 a 0008. A conferência cruzada do prompt 04 foi respondida pelo design
0.2 e pelos requisitos 1.3; a conferência mecânica do prompt 05 (no `HANDOFF.md`) não achou divergência. Nada é implementado enquanto o gate não for
feito; depois dele vem o plano de tarefas (`fase-1-tasks.md`), que é quem decide a entrada de `polars`
e das demais dependências.

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
