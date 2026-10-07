# Changelog das specs

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento por spec, não global.

## 2026-10-06

### fase-1-requirements 1.2 — proposta, aguardando o gate de design

Fecha a emenda 1.1 com o resultado de RF-VER-05 e com o que o design encontrou. A versão 1.0 segue aprovada; a 1.2 está **proposta** e é aprovada junto com o design. O que muda:

1. **Tolerância de PnL de 1 para 10 bps** — RF-ING-04 CA-04.2, D20, §7.2.
2. **Condição de nível no proxy** (mediana diária de até 50 bps) — RF-ING-06 CA-06.3, §7.2.
3. **Funding associado à hora por arredondamento para baixo** — RF-ING-05 CA-05.1.
4. **`N*` só sobre o tempo em posição** — RF-SEL-03 CA-03.1, ADR-0007.
5. **Parâmetros de custo congelados antes da seleção** — RF-SEL-01 CA-01.4, RF-SEL-05 CA-05.1, RF-SEL-08 CA-08.1 e CA-08.5, RF-COL-05 CA-05.2.
6. **Ordens em outros ativos só para reduzir** — RF-SIM-02 CA-02.2 e CA-02.4.
7. **Diagnóstico das quebras de continuidade** — RF-ING-03 CA-03.4.
8. **Livro-razão do líder no piso de cobertura** — RNF-02.
9. **Sem serviço de banco** — RNF-06, ADR-0006.

**Precisões que o design exigiu** — evento do líder como o conjunto de fills do mesmo milissegundo (glossário); teto conferido nas ordens que aumentam exposição, com a exceção da ordem mínima (RF-SIM-02 CA-02.7); execução atrasada processada no instante efetivo e teste de mutação enunciado pelo relógio da execução (RF-SIM-01 CA-01.2 e CA-01.5, ADR-0008); universo contado sobre candidatas com coleta completa (RF-SEL-08 CA-08.1); dado congelado não reescrito (RF-ING-08 CA-08.2); conferência de PnL só em episódios abertos e fechados na janela (RF-ING-04 CA-04.2); meio-spread ponderado pelo tempo (RF-COL-05 CA-05.2); F8 sobre perpétuos; desvio-padrão amostral (RF-ANA-01 CA-01.1); capital parado quando a coorte é menor que K (RF-SIM-07 CA-07.1); semente do pool (§7.2); comandos da CLI (RF-CLI-01).

### fase-1-design 0.1 — em revisão

Rascunho inicial do design técnico, sobre os requisitos 1.2. Aguarda o gate 2, o mesmo dos requisitos 1.2 e dos ADRs 0006 a 0008. Já incorpora uma revisão independente, que encontrou dois defeitos (execução atrasada contabilizada no instante nominal, e teto que não disparava redução quando o preço andava).

### ADR-0002, ADR-0003 — errata

Uma errata de 2026-10-06 acrescentada ao fim de cada um. **O corpo de um ADR aceito não mudou.** 0002: o teto tem uma exceção quando a redução exigida cai abaixo da ordem mínima, e a definição de `N*` é refinada pelo ADR-0007. 0003 (segunda errata, do design): o caso sem preço em t + Δ é decidido pelo ADR-0008, que reenuncia o teste de mutação pelo relógio da execução.

### ADR-0006, ADR-0007, ADR-0008 — propostos

Passam a aceitos com a aprovação do design da Fase 1. 0006: dados em arquivos Parquet locais, sem servidor de banco, com hash pelo conteúdo. 0007: `N*` medido só sobre o tempo em posição, refinando o ADR-0002. 0008: a ordem atrasada executa na primeira observação de preço, uma por evento, com a visão do líder formada pelas execuções já processadas, refinando o ADR-0003.

### CLAUDE.md

Regra de errata em §2; invariantes do ADR-0006; refinamentos dos ADRs 0002 e 0003 pelos ADRs 0007 e 0008; `LookaheadError` na hierarquia de exceções; relógio lido num único módulo; livro-razão do líder no piso de cobertura.

### fase-1-requirements 1.1 — emenda proposta, aguardando aprovação

Resultado da verificação de dados (`docs/verificacao-de-dados.md`): dez pontos contradisseram os requisitos ou os ADRs. A versão 1.0 segue aprovada; a 1.1 está **proposta** e só vale depois de aprovada. O que muda:

1. **Sem teto de 10.000 fills** — RF-ING-02 CA-02.1 e CA-02.3, F3, premissa 14.
2. **Tolerância de PnL** — RF-ING-04 CA-04.2, D20 (1 bp do notional do episódio, sujeita a RF-VER-05 CA-05.2).
3. **Quebras de continuidade** — RF-ING-03 CA-03.2 e CA-03.3, RF-SIM-02 CA-02.8.
4. **Universo por regra, no lugar da lista fixa** — RF-SEL-08, D7, D21, RF-COL-05 CA-05.2, RF-ANA-01 CA-01.4.
5. **Pool de candidatas amostrado** — RF-SEL-07, D17, RF-SEL-02 CA-02.1.
6. **Cadência do livro** — RF-COL-01 CA-01.1, RF-SIM-03 CA-03.2, D19.
7. **Regra de lacuna** — RF-COL-02 CA-02.2.
8. **Classes de fill** — RF-ING-02 CA-02.4 e CA-02.5, F10.
9. **Agregação** — D18.
10. **Proxy** — RF-ING-06 CA-06.3 e CA-06.4, RF-COL-05.

**Critérios adicionados** — RF-VER-05 (verificação complementar, CA-05.1 a CA-05.4). **Questões** — Q6 e Q7 abertas e fechadas na mesma emenda, como D7 e D17.

### ADR-0001, ADR-0003, ADR-0004 — errata

Uma errata de 2026-10-06 acrescentada ao fim de cada um. **O corpo de um ADR aceito não mudou.** 0001: não há teto de 10.000 fills, há mais classes de fill, a continuidade quebra em dado real. 0003: o livro default chega a cada 5,4 s, e só a assinatura rápida chega perto de 0,5 s. 0004: o limite de histórico que justificava descartar o walk-forward não existe, e o pool de candidatas passa a ser amostrado.

### CLAUDE.md

A regra de ADR-0001 sobre continuidade de posição distingue seleção (inelegível) de avaliação (mudança não observada incorporada no fill seguinte e contada) e fixa que os fills são sempre não agregados.

## 2026-10-05

### fase-1-requirements 1.0 — aprovada

Gate 1 concluído. A fase fecha em três partes: Rota A (triagem retrospectiva), semana ao vivo com gate do piloto (RF-ANA-08, ADR-0005) e veredito de 30 dias da Rota B.

**Decisões fechadas** — Q1 a Q4 fechadas como D11 a D16: capital primário de US$ 50 (D11), teto de capital real de US$ 50 (D13), K = `min(5, ⌊capital / 50⌋)` (D14), limiares dos filtros F1 a F10 (D15) e nome do pacote `copylab` (D16). Q5 fechada como D10 (coletor na máquina secundária), na versão 0.2.

**Critérios adicionados** — RF-SEL-06 CA-06.3, RF-SIM-03 CA-03.4 e RF-ANA-05 CA-05.4.

**Escopo declarado** — verificação de dados (§4.1) como única área implementada antes do design.

### ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005 — aceitos

Fonte de sinal (fills públicos da Hyperliquid, somente leitura), espelhamento por exposição relativa com teto de 1x, execução do seguidor em t + Δ ao pior preço, protocolo de avaliação em duas rotas com pré-registro, e gate do piloto por consistência.
