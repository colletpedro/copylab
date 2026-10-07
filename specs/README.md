# Specs — copylab

Este diretório é a fonte da verdade do projeto. Nenhuma linha de implementação é escrita antes de a spec correspondente estar escrita, revisada e aprovada. O fluxo, os gates e as convenções são os do quantlab.

## Fluxo por módulo

1. **Requisitos** — o que o módulo faz, com critérios de aceitação testáveis (Dado/Quando/Então).
2. **Design técnico** — arquitetura, interfaces públicas, schemas, decisões com alternativas descartadas.
3. **Plano de tarefas** — tarefas pequenas, ordenadas por dependência, com critério de verificação.
4. **Implementação** — só depois dos três gates acima.

Cada transição é um gate explícito. Um gate reprovado volta para a etapa anterior.

**Exceção declarada:** a verificação de dados (§4.1 dos requisitos da Fase 1) roda antes do design, por scripts exploratórios em `scripts/verify/`, porque o design depende do que ela medir.

## Estado

| Spec | Versão | Requisitos | Design | Tarefas | Implementada |
|---|---|---|---|---|---|
| `00-plataforma/fase-1` | 1.3 | ✅ 1.3 aprovada em 2026-10-07 (gate de design) | ✅ 1.0 aprovado em 2026-10-07 (gate 2, `fase-1-design.md`) | ✅ 0.1 aprovado em 2026-10-07 (gate 3, `fase-1-tasks.md`) | 🟡 em andamento: Bloco 0 |

## ADRs

Numerados e imutáveis. Quando uma decisão muda, cria-se um ADR novo que declara supersedência do anterior. O antigo não é editado nem removido.

Uma **errata** datada, acrescentada ao fim do ADR, corrige um fato e as consequências que dependiam dele, ou aponta para o ADR que o refina. O corpo do ADR não é tocado. Uma errata não pode alterar o que a seção Decisão determina nem inverter a escolha: isso exige ADR novo.

| # | Título | Status |
|---|---|---|
| 0001 | Usar fills públicos da Hyperliquid como fonte de sinal | aceito, com errata de 2026-10-06 |
| 0002 | Espelhar a exposição relativa do líder, com teto de alavancagem de 1x | aceito, com erratas de 2026-10-06 e 2026-10-07; a definição de `N*` é refinada pelo ADR-0007 |
| 0003 | Executar o seguidor em t + Δ, ao pior preço observado | aceito, com duas erratas de 2026-10-06; o caso sem preço em t + Δ é refinado pelo ADR-0008 |
| 0004 | Avaliar em duas rotas: triagem retrospectiva e veredito prospectivo | aceito, com errata de 2026-10-06 |
| 0005 | Liberar um piloto de US$ 50 pela Rota A e por uma semana de consistência | aceito |
| 0006 | Guardar os dados em arquivos Parquet locais, sem servidor de banco | aceito em 2026-10-07, com o gate de design |
| 0007 | Medir a referência de exposição só sobre o tempo em posição | aceito em 2026-10-07, com o gate de design |
| 0008 | Executar a ordem atrasada quando há preço, uma por evento, com o que o seguidor já viu | aceito em 2026-10-07, com o gate de design |

## Roadmap

| Fase | Escopo | Estado |
|---|---|---|
| 0 | Fundação: repositório, CI e convenções herdadas do quantlab | concluída |
| 1 — verificação | Confirmar em dado real o que a spec assume sobre a API (§4.1) | concluída: RF-VER-01 a RF-VER-05 executadas em 2026-10-06 (`docs/verificacao-de-dados.md`) |
| 1A | Rota A: ingestão, seleção, simulador e relatório de triagem sobre setembro de 2026. O coletor entra em operação nesta parte | em implementação, pelo plano de tarefas (`fase-1-tasks.md`): Bloco 0 iniciado em 2026-10-07 |
| 1B | Semana ao vivo: 7 dias de livro gravado e o gate do piloto | depende de 1A |
| 1C | Veredito do estudo: 30 dias de avaliação prospectiva | depende de 1B |
| 2 | Piloto com dinheiro real, limitado a US$ 50, com spec própria | bloqueada até o gate do piloto ser atingido |
