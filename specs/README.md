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
| `00-plataforma/fase-1` | 1.0 | ✅ aprovada | ⬜ aguarda a verificação de dados | ⬜ | ⬜ |

## ADRs

Numerados e imutáveis. Quando uma decisão muda, cria-se um ADR novo que declara supersedência do anterior. O antigo não é editado nem removido.

| # | Título | Status |
|---|---|---|
| 0001 | Usar fills públicos da Hyperliquid como fonte de sinal | aceito |
| 0002 | Espelhar a exposição relativa do líder, com teto de alavancagem de 1x | aceito |
| 0003 | Executar o seguidor em t + Δ, ao pior preço observado | aceito |
| 0004 | Avaliar em duas rotas: triagem retrospectiva e veredito prospectivo | aceito |
| 0005 | Liberar um piloto de US$ 50 pela Rota A e por uma semana de consistência | aceito |

## Roadmap

| Fase | Escopo | Estado |
|---|---|---|
| 0 | Fundação: repositório, CI e convenções herdadas do quantlab | não iniciada |
| 1 — verificação | Confirmar em dado real o que a spec assume sobre a API (§4.1) | não iniciada |
| 1A | Rota A: ingestão, seleção, simulador e relatório de triagem sobre setembro de 2026. O coletor entra em operação nesta parte | requisitos aprovados |
| 1B | Semana ao vivo: 7 dias de livro gravado e o gate do piloto | depende de 1A |
| 1C | Veredito do estudo: 30 dias de avaliação prospectiva | depende de 1B |
| 2 | Piloto com dinheiro real, limitado a US$ 50, com spec própria | bloqueada até o gate do piloto ser atingido |
