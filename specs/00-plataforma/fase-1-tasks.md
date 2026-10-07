# Fase 1 (estudo de simulação) — Plano de tarefas

**Status:** aprovado — gate 3 em 2026-10-07
**Versão:** 0.1
**Data:** 2026-10-07
**Requisitos:** `fase-1-requirements.md`, versão 1.3 (aprovada)
**Design:** `fase-1-design.md`, versão 1.0 (aprovado)

> Este documento diz **em que ordem** a fase é construída e **como se sabe que cada parte está pronta**. O que construir está no design. Onde este texto e o design divergirem, vale o design.

---

## 1. Como ler

Cada tarefa tem um identificador, o que entrega, de quem depende e a prova de que está pronta. A prova é sempre uma lista de critérios de aceitação: os testes que os provam são os de §8.2 do design, com os nomes de lá.

Há dois tipos de linha:

- **Tarefa (T):** código e testes, feitos pelo Claude Code.
- **Marco operacional (M):** algo que roda no mundo real e leva tempo de calendário: ligar o coletor, ingerir 3.000 carteiras, esperar dias de gravação. Quem executa é o Pedro, com os comandos que as tarefas entregaram.

A ordem dos blocos segue o calendário, e não a ordem lógica do design. O coletor vem primeiro porque cada dia sem ele é um dia a menos de livro gravado, e três dias de gravação são pré-requisito da primeira seleção.

## 2. Pronto de uma tarefa

Uma tarefa só está pronta quando:

1. Os testes dos critérios citados existem, com os nomes do design, e passam.
2. Cada teste de invariante de §8.1 do design tocado pela tarefa provou que tem dente: o código foi quebrado de propósito, o teste caiu, o código foi restaurado e a mutação está na docstring.
3. Testes de seleção, simulador, analytics e livro-razão usam fixtures de papel, com a conta do valor esperado escrita no teste.
4. `make check` passa.
5. Nada além do escopo da tarefa foi implementado.
6. `docs/STATE.md` e `HANDOFF.md` refletem o que mudou.

Se a tarefa esbarrar numa lacuna do design, a resposta é parar e levar a pergunta à conversa de arquitetura. Não é preencher a lacuna com uma escolha própria.

## 3. Visão de calendário

```
dia 0        Bloco 0 e Bloco A prontos ─► M-A: coletor ligado
dia 0 a 2    Bloco B ─► M-B: ingestão do pool da Rota A (cerca de 15 horas)
             lista do coletor recebe os ativos candidatos que faltarem
em paralelo  Blocos C, D, E, F
dia 3+       M-C: 3 dias de coletor para todos os candidatos ─► custos medidos
depois       Bloco G ─► M-1A: seleção, congelamento e avaliação da Rota A
depois       Bloco H ─► M-1B: seleção e publicação da Rota B, semana ao vivo, gate
dia 30+      M-1C: veredito de 30 dias
```

Os dias são de calendário a partir do coletor ligado, e são piso, não promessa.

---

## 4. Tarefas

### Bloco 0 — Base

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-001 | Acertos na fundação: teste de somente leitura renomeado para o nome do ADR-0001; `LookaheadError` em `copylab.exceptions`; docstring de `DataError` sem "leitura proibida"; subpacote `leader` vazio; `copylab.leader` na medição de cobertura | — | RNF-09, RNF-02. O teste renomeado continua com dente |
| T-002 | `timeutil` e `clock`, e o teste de fronteira de tempo | T-001 | RNF-07. `test_architecture_time_boundary` |
| T-003 | `ports`: protocolo `Repository` e `BoundedRepository` | T-002 | RF-SEL-01 CA-01.1, na parte do repositório: leitura com fim depois do corte levanta `LookaheadError`; leaderboard, lotes e tipo de conta passam |
| T-004 | Núcleo de `storage`: diretório de dados, escrita atômica, leitura por partição, hash de conteúdo, interface `Writer`, registro de janelas congeladas | T-003 | ADR-0006: `test_content_hash_ignores_file_bytes_and_row_order`, `test_interrupted_write_leaves_previous_table_intact`, `test_frozen_rows_are_never_rewritten`, `test_architecture_storage_isolation`, `test_architecture_logic_packages_are_pure` |
| T-005 | `params` e `preregistro/parametros.toml`, com todos os valores de §7.2 e §7.3 dos requisitos e a regra de nomes da Binance | T-002 | Carrega, é imutável, expõe hash canônico. Valor ausente ou de tipo errado é `ConfigError` |

### Bloco A — Coletor

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-010 | Gravador: conexão, assinaturas dos três canais por ativo, ping, segmentos brutos de uma hora com instante de recebimento, descarga periódica, retomada depois de queda | T-004 | RF-COL-01 CA-01.1, RF-COL-03 CA-03.1, RF-COL-04 CA-04.1, contra um servidor de WebSocket falso |
| T-011 | Reconexão e registro de desconexões | T-010 | RF-COL-02 CA-02.1 |
| T-012 | Compactação: tabelas `bbo`, `book` e `trades`, e tabela `gaps` no relógio da corretora | T-011 | RF-COL-02 CA-02.2, `test_gaps_are_recorded_in_exchange_time`. Contagens conferidas antes de apagar segmento |
| T-013 | Status: cobertura por ativo, latência de recebimento, projeção de disco | T-012 | RF-COL-02 CA-02.3, RF-COL-03 CA-03.2, RF-COL-04 CA-04.2 |
| T-014 | `config/collector_assets.toml` com os 27 ativos da verificação; comandos `collect`, `collect status`, `collect compact`; `docs/coletor.md` com o roteiro de operação na máquina secundária | T-013 | RF-SEL-08 CA-08.5, na parte do coletor. O roteiro foi seguido uma vez, do zero |
| **M-A** | **Coletor ligado na máquina secundária.** No fim do primeiro dia, `collect status` dá a projeção real de disco | T-014 | Se a projeção passar de 30 GB, volta para a conversa de arquitetura antes de qualquer outra coisa (risco 9 do design) |

### Bloco B — Ingestão

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-020 | Orçamento de peso e provedor da API, com provedor falso para os testes | T-004 | RF-ING-07 CA-07.1 e CA-07.3 |
| T-021 | Snapshots de leaderboard e de lotes | T-020 | RF-ING-01 CA-01.1, RF-ING-05 CA-05.2, RF-SEL-01 CA-01.3 na parte da tabela derivada |
| T-022 | Fills: paginação, classificação, validação, teto de 20.000, cobertura e retomada | T-020 | RF-ING-02 CA-02.1 a CA-02.5, RF-ING-07 CA-07.2 |
| T-023 | Reingestão, divergências e janela congelada | T-022 | RF-ING-02 CA-02.2, RF-ING-08 CA-08.2 |
| T-024 | Funding | T-020 | RF-ING-05 CA-05.1 |
| T-025 | Preço proxy: download, checksum, série por segundo, percurso dos ativos candidatos | T-005, T-022 | RF-ING-06 CA-06.1 e CA-06.2 |
| T-026 | Tipo de conta | T-020 | Tabela `roles` gravada com instante de coleta |
| T-027 | Guarda da janela de avaliação e comandos `ingest` | T-021 a T-026 | RF-SEL-05 CA-05.4, RF-CLI-01 CA-01.2 |
| **M-B** | **Ingestão do pool da Rota A:** snapshot, sorteio, fills da janela de seleção, funding e proxy. Ativo candidato que faltar entra na lista do coletor | T-027, T-060 | Cobertura `ok` relatada por carteira. Nada de setembro foi baixado |

### Bloco C — Livro-razão do líder

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-030 | Posições, eventos por milissegundo, continuidade | T-005 | RF-ING-03 CA-03.1 |
| T-031 | Episódios e conferência de PnL | T-030 | RF-ING-04 CA-04.1 e CA-04.2 |
| T-032 | Diagnóstico das quebras | T-030 | RF-ING-03 CA-03.4 |

### Bloco D — Simulador

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-040 | Contabilidade da subconta e identidade de conciliação | T-005 | RF-SIM-04 CA-04.1, RF-SIM-06 CA-06.1 a CA-06.4 |
| T-041 | Cursor, fita do líder, tabela de funding e fonte de preço da Rota A | T-030 | RF-SIM-01 CA-01.3, RF-SIM-03 CA-03.1 |
| T-042 | Espelhamento: visão do líder, alvos, teto, reduções, lote e mínimo (§4.3 do design) | T-040, T-041 | RF-SIM-02 CA-02.1 a CA-02.8 |
| T-043 | Laço: ocorrências, funding, execução atrasada, pendentes | T-042 | RF-SIM-01 CA-01.1, CA-01.4 e CA-01.5, RF-SIM-05 CA-05.1 a CA-05.3, ADR-0008 |
| T-044 | **Teste de aceitação:** mutação do futuro | T-043 | RF-SIM-01 CA-01.2 |
| T-045 | Cópia ideal e variante só compras | T-043 | Invariantes dos ADRs 0002 e 0003: `test_ideal_copy_reproduces_leader_pnl_at_follower_scale`, `test_long_only_variant_equals_engine_with_shorts_dropped` |

### Bloco E — Analytics, primeira parte

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-050 | Métricas: retornos, Sharpe, drawdown, episódios copiados, taxa de acerto, giro | T-040 | RF-ANA-01 CA-01.1 a CA-01.4 |
| T-051 | Carteira, subcontas e benchmark | T-043, T-050 | RF-SIM-07 CA-07.1 e CA-07.2, RF-ANA-02 CA-02.1 |
| T-052 | Grade, referência com Δ = 0 e decomposição | T-051 | RF-SIM-08 CA-08.1, RF-SIM-04 CA-04.2, RF-ANA-02 CA-02.2, RF-ANA-03 CA-03.1 e CA-03.2 |
| T-053 | Contadores de não cópia e excesso sobre o teto | T-051 | RF-ANA-04 CA-04.1 |

### Bloco F — Seleção

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-060 | Pool por SHA-256 e blocos | T-021 | RF-SEL-07 CA-07.1 a CA-07.3 |
| T-061 | Ativos candidatos, conferência do proxy e universo | T-025, T-030 | RF-ING-06 CA-06.3 e CA-06.4, RF-SEL-08 CA-08.1 a CA-08.3 |
| T-062 | Medida de custo e comando `costs measure` | T-012 | RF-COL-05 CA-05.2, RF-SEL-01 CA-01.4 |
| T-063 | Fatos por carteira e filtros F1 a F10 | T-031, T-061 | RF-SEL-02 CA-02.1 a CA-02.3, RF-ING-03 CA-03.2 |
| T-064 | Referência de exposição | T-030 | RF-SEL-03 CA-03.1 e CA-03.2, ADR-0007 |
| T-065 | Ranking, coorte e coortes de controle | T-043, T-064 | RF-SEL-04 CA-04.1 a CA-04.4, RF-SEL-06 CA-06.1 a CA-06.3 |
| T-066 | Congelamento, comando `select` e relatório de seleção | T-062 a T-065 | RF-SEL-05 CA-05.1, RF-SEL-01 CA-01.1 e CA-01.3 |
| T-067 | **Teste de aceitação:** mutação da janela de avaliação | T-066 | RF-SEL-01 CA-01.2 |
| **M-C** | **Custos medidos:** 3 dias de coletor para todos os ativos candidatos e `costs measure` | M-A, M-B, T-062 | `preregistro/custos.json` commitado, com BTC |

### Bloco G — Avaliação da Rota A

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-070 | Veredito, relatório de avaliação, seção de vieses, aviso de amostra, arquivo de resultado, comando `evaluate` | T-052, T-053, T-066 | RF-ANA-05 CA-05.1 a CA-05.3, RF-ANA-06 CA-06.1, RF-ANA-07 CA-07.1, RF-ANA-02 CA-02.3, RF-SEL-05 CA-05.2, RF-ING-08 CA-08.1, RF-ING-03 CA-03.3, RF-CLI-01 CA-01.1 |
| T-071 | Gráfico | T-070 | RF-CLI-02 CA-02.1 |
| T-072 | Determinismo e orçamento de performance | T-070 | RNF-01, RNF-04 |
| **M-1A** | **Rota A:** `select`, commit do congelamento, ingestão de setembro, `evaluate`. Relatório de triagem commitado | M-C, T-072 | DoD da Parte 1A dos requisitos, item por item |

### Bloco H — Rota B

| ID | Entrega | Depende | Prova |
|---|---|---|---|
| T-080 | Fonte de preço do livro | T-012, T-043 | RF-SIM-03 CA-03.2 e CA-03.3 |
| T-081 | Conferência do livro contra o proxy | T-080 | RF-COL-05 CA-05.1 |
| T-082 | Publicação e janela efetiva: `window open` e `effective_window` | T-066 | RF-SEL-05 CA-05.3, RF-SEL-08 CA-08.4 |
| T-083 | Comparação de fontes, gate do piloto e relatório do gate | T-080, T-082 | RF-SIM-03 CA-03.4, RF-ANA-08 CA-08.1 a CA-08.4 |
| T-084 | Veredito de 30 dias e rota inconclusiva | T-083 | RF-ANA-05 CA-05.4 |
| **M-1B** | **Rota B:** ingestão do pool novo, `select --route B`, `push`, `window open`, 7 dias de cobertura, `gate` | M-1A, T-084 | DoD da Parte 1B |
| **M-1C** | **Veredito:** 30 dias de cobertura, `evaluate`, README final | M-1B | DoD da Parte 1C |

---

## 5. O que este plano não cobre

- O piloto com dinheiro real. Ele tem spec própria e só começa se o gate do piloto for atingido.
- A causa das quebras de continuidade. T-032 entrega o diagnóstico; interpretar o resultado volta para a conversa de arquitetura.
- Qualquer ajuste de parâmetro. Depois de M-1A, nenhum valor de `preregistro/parametros.toml` muda sem emenda dos requisitos.

## 6. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | 2026-10-07 | Plano inicial, sobre os requisitos 1.3 e o design 1.0 |
