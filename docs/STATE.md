# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

O estado dos gates mora em [`specs/README.md`](../specs/README.md). Este arquivo diz
**onde o trabalho está**, não repete a tabela de gates.

## Onde estamos

**Fase 0 concluída (2026-10-05). Verificação de dados (RF-VER-01 a RF-VER-05) concluída em
2026-10-06**, com relatório em [`docs/verificacao-de-dados.md`](verificacao-de-dados.md). **Em
2026-10-07, os requisitos 1.3, o design 1.0, os ADRs 0006 a 0008 e o plano de tarefas 0.1 foram
aprovados, e o Bloco 0 do plano (T-001 a T-005) foi implementado. Em seguida, o design 1.1
respondeu as perguntas do Bloco 0, e o Bloco A (coletor, T-010 a T-014) foi implementado e testado
contra a corretora real, mas ainda não está ligado na máquina secundária (marco M-A). Na mesma
data, o design 1.2 incorporou as decisões do Bloco A, e o Bloco B (ingestão, T-020 a T-027, mais
T-060 e a ordenação de ativos de T-061, adiantadas do Bloco F) foi implementado e testado contra a
API real em escala pequena; a ingestão completa (marco M-B) foi rodada em 2026-10-09.** O repositório está publicado em
`https://github.com/colletpedro/copylab`.
Detalhe, decisões e pendências em [`HANDOFF.md`](../HANDOFF.md).

| Item | Estado |
|---|---|
| Requisitos da Fase 1 | ✅ 1.3 aprovada (2026-10-07) |
| ADRs 0001 a 0005 | ✅ aceitos; 0001 e 0004 com errata de 2026-10-06, 0002 com erratas de 2026-10-06 e 2026-10-07, 0003 com duas de 2026-10-06 (corpo inalterado) |
| ADRs 0006 a 0008 | ✅ aceitos em 2026-10-07, com o gate de design. 0007 refina o 0002 (`N*`), 0008 refina o 0003 (execução sem preço em t + Δ) |
| Fundação (Fase 0) | ✅ `make check` verde; CI verde no GitHub |
| Verificação de dados (§4.1) | ✅ RF-VER-01 a 04 executadas: 8 `ok`, 1 `a emendar`, 2 `reprova`, 1 `não medido` |
| Verificação complementar (RF-VER-05) | ✅ executada em 2026-10-06: 4 `ok` |
| Design da Fase 1 | ✅ 1.2 (1.0 aprovado no gate 2, 2026-10-07; 1.1 responde as perguntas do Bloco 0; 1.2 incorpora as decisões do Bloco A) |
| Plano de tarefas | ✅ 0.1 aprovado (gate 3, 2026-10-07) |
| Bloco 0 — base (T-001 a T-005) | ✅ implementado em 2026-10-07; `make check` e CI verdes |
| Bloco A — coletor (T-010 a T-014) | ✅ código pronto e adaptado ao Windows nativo; `make check`, integração e CI (inclusive Windows) verdes; roteiro para Windows escrito, com a seção de serviço ainda não executada numa máquina Windows |
| M-A — coletor ligado | ⬜ com o Pedro, pelo roteiro |
| Bloco B — ingestão (T-020 a T-027) | ✅ código pronto; `make check` verde; integração (5 carteiras, 1 dia de proxy) rodada uma vez contra a API real |
| T-060 (pool) e ordenação de ativos de T-061 | ✅ adiantadas do Bloco F, em `selection` |
| M-B — ingestão do pool da Rota A | ✅ concluído (2026-10-09), `snapshot_ms=1791482136751`: 3.000 carteiras (2.972 `ok`, 28 `frequência incompatível`, 0 falhas), 3.581.682 fills; 20 ativos cumprem (i) e (ii), todos com proxy; 422 MB em disco |
| M-C — medida de custo | ⬜ depois de 3 dias UTC completos de gravação dos 20 ativos (BNB e TAO: a partir de 2026-10-13 00:00 UTC) |
| Demais blocos (C a H) | ⬜ |

## Próximo

**M-A: o Pedro liga o coletor** na máquina secundária (Windows), pelo roteiro
[`docs/coletor.md`](coletor.md); no fim do primeiro dia, `collect status` dá a projeção real de disco.
**M-B concluído** (2026-10-09): fills do bloco 0 (3.000 carteiras: 2.972 `ok`, 28 `frequência
incompatível`, 0 falhas; 3.581.682 fills) e proxy dos 20 ativos que cumprem (i) e (ii): BTC, ETH, HYPE,
SOL, ZEC, LIT, PUMP, XRP, NEAR, ENA, XMR, AAVE, DOGE, FARTCOIN, UNI, BNB, TAO, VVV, TRUMP, LINK.
BNB e TAO entraram na lista do coletor (reiniciar o coletor); detalhes no fim do `HANDOFF.md`.
**M-C, medida de custo:** pode rodar depois de 3 dias UTC completos de gravação dos 20; para BNB e
TAO, a partir de 2026-10-13 00:00 UTC, se começarem a gravar antes da virada de 2026-10-10. Em
paralelo, os Blocos C, D e E.

## O que existe no código

- `src/copylab/{cli,config,logging,exceptions}.py` — infraestrutura. `config` ganhou
  `COPYLAB_DATA_DIR`; `exceptions` ganhou `LookaheadError`.
- `src/copylab/timeutil.py` e `clock.py` — a única conversão de instante em calendário e a única
  leitura do relógio (T-002).
- `src/copylab/ports.py` — `Repository` e `BoundedRepository` (T-003).
- `src/copylab/storage/` — núcleo genérico: diretório de dados, partições Parquet, escrita
  atômica, hash de conteúdo, `Writer`, trechos gravados e janelas congeladas (T-004); os
  esquemas de todas as tabelas (`tables.py`); a leitura por janela que implementa o protocolo
  (`repository.py`), com as tabelas do coletor lidas pelo instante da corretora nas partições
  vizinhas (design 1.2); `create` para snapshots e `append` para o registro de divergências.
- `src/copylab/params.py` e `preregistro/parametros.toml` — parâmetros de §7.2 e §7.3 e a regra
  de nomes da Binance, num modelo imutável com hash canônico (T-005).
- `src/copylab/collector/` — gravador de WebSocket com reconexão, compactação em `bbo`, `book`,
  `trades` e `gaps`, status, lista de ativos e o processo (T-010 a T-014). Os segmentos brutos moram
  em `src/copylab/storage/segments.py`. Comandos `collect`, `collect status` e `collect compact`.
- `config/collector_assets.toml` — os 27 ativos do coletor. `docs/coletor.md` — roteiro de operação.
- `src/copylab/ingestion/` — orçamento de peso e provedor da API sobre `httpx`, com os falsos da
  suíte (`fake.py`); snapshots de leaderboard e lotes; fills com paginação, cobertura, retomada e
  reingestão; funding; proxy da Binance e percurso dos candidatos (`market.py`); tipo de conta;
  guarda da janela de avaliação. Comandos `ingest leaderboard`, `ingest fills` e `ingest market`.
- `src/copylab/selection/` — só o pool (`pool.py`, T-060) e a ordenação dos ativos candidatos
  (`assets.py`, metade de T-061). O resto do Bloco F não existe.
- `src/copylab/{leader,sim,analytics}/` — vazios, só `__init__.py` com uma docstring que diz qual
  bloco os preenche. Vazios **de propósito** (CLAUDE.md §1).
- `scripts/verify/` — código exploratório da verificação de dados. Fora do `mypy` e da cobertura.
- `tests/unit/` — fumaça, `config`, `logging`, ferramentas de medição; testes de `timeutil`,
  `clock`, `ports`, `storage`, `params`, coletor, ingestão, pool e ordenação de ativos; os quatro
  testes de arquitetura do design §2.1 (`test_architecture_read_only.py` e
  `test_architecture_boundaries.py`).
- `docs/ingestao.md` — roteiro do M-B.
- `data/verify/` (fora do git, ~200 MB) — amostras brutas da verificação e resultados em JSON.

## Números

- 439 testes unitários, todos offline, que o CI roda em Linux e em Windows, e 2 de integração
  (60 s do WebSocket real; ingestão de 5 carteiras e de um dia de proxy de BTC), fora da suíte
  default e do CI.
- Cobertura medida em `leader`, `selection`, `sim` e `analytics`: só `selection` tem código, com
  100% de linhas e ramos (`pool.py` e `assets.py`). `storage`, `ports`, `params`, `timeutil` e
  `ingestion` não entram no piso (RNF-02), mas têm testes próprios.
