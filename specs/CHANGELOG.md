# Changelog das specs

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento por spec, não global.

## 2026-10-05

### fase-1-requirements 1.0 — aprovada

Gate 1 concluído. A fase fecha em três partes: Rota A (triagem retrospectiva), semana ao vivo com gate do piloto (RF-ANA-08, ADR-0005) e veredito de 30 dias da Rota B.

**Decisões fechadas** — Q1 a Q4 fechadas como D11 a D16: capital primário de US$ 50 (D11), teto de capital real de US$ 50 (D13), K = `min(5, ⌊capital / 50⌋)` (D14), limiares dos filtros F1 a F10 (D15) e nome do pacote `copylab` (D16). Q5 fechada como D10 (coletor na máquina secundária), na versão 0.2.

**Critérios adicionados** — RF-SEL-06 CA-06.3, RF-SIM-03 CA-03.4 e RF-ANA-05 CA-05.4.

**Escopo declarado** — verificação de dados (§4.1) como única área implementada antes do design.

### ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005 — aceitos

Fonte de sinal (fills públicos da Hyperliquid, somente leitura), espelhamento por exposição relativa com teto de 1x, execução do seguidor em t + Δ ao pior preço, protocolo de avaliação em duas rotas com pré-registro, e gate do piloto por consistência.
