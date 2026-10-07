# ADR-0008 — Executar a ordem atrasada quando há preço, uma por evento, com o que o seguidor já viu

**Status:** aceito (2026-10-07, com o gate de design da Fase 1)
**Data:** 2026-10-06
**Contexto de decisão:** Fase 1 — simulador (execução sem preço em t + Δ)
**Refina:** o ADR-0003, no caso que ele não cobria. Todo o resto do ADR-0003 continua valendo.

## Contexto

O ADR-0003 diz que, sem observação de preço em t + Δ, a ordem usa a próxima existente e registra o atraso. Na Rota A isso acontece quando o segundo de execução não tem negócio na Binance, e a espera é de segundos. Na Rota B acontece quando o coletor esteve fora do ar, e a espera pode ser de horas.

O ADR não diz duas coisas que mudam o resultado:

1. **Onde a ordem entra na contabilidade:** no instante nominal, com um preço que só existiu depois, ou no instante em que o preço existe.
2. **O que o seguidor sabe do líder nessa hora.** A frase "a decisão usa apenas eventos com instante ≤ t" foi escrita pensando no caso sem atraso. Com atraso, enquanto a ordem espera, ordens de eventos mais novos em outros ativos podem já ter executado.

O primeiro rascunho do design contabilizava no instante nominal. Uma revisão independente mostrou o defeito: entre o instante nominal e o da observação, o patrimônio, o funding e o tamanho de outras ordens passavam a depender de um preço futuro.

## Decisão

1. **Cada evento do líder continua gerando a sua ordem.**
2. **A execução acontece no primeiro instante, a partir de t + Δ, em que há observação de preço do ativo**, com o patrimônio e os preços desse instante. Nada é contabilizado antes.
3. **O que o seguidor sabe do líder, numa execução, são os eventos cujas execuções já foram processadas**, mais o evento da própria execução. Em cada ativo vale a posição do último evento processado. Sem atraso, isso é idêntico a "eventos com instante ≤ t".
4. Execuções no mesmo instante seguem a ordem do instante do evento e, no empate, a alfabética do ativo. No mesmo ativo, consomem a mesma escada de preços em sequência.
5. Evento cuja execução não acontece antes do fim da janela fica pendente e não entra no que o seguidor sabe.

**O teste de mutação passa a ser enunciado pelo relógio da execução.** Para um corte c: alterar arbitrariamente os eventos do líder com instante > c, e os preços e o funding posteriores a c + Δ e à última observação consumida pelas execuções até c + Δ, não muda nenhuma ordem executada até c + Δ (RF-SIM-01 CA-01.2).

A invariante de RF-SIM-01 não muda: uma ordem executada em τ só depende de eventos do líder com instante ≤ τ − Δ.

## Justificativa

- **Nenhum intervalo depende de preço futuro.** Tudo o que acontece antes da observação é calculado sem ela.
- **A carteira é coerente.** O teto é calculado com o que o seguidor de fato tem naquele instante, e não com uma fotografia antiga do líder.
- **Erra para o lado pessimista.** Se o líder abre e fecha uma posição dentro de uma lacuna, o seguidor executa as duas ordens ao mesmo preço: paga spread e duas taxas e não captura movimento nenhum.
- **É fiel ao que já estava decidido.** Um evento, uma ordem, executada na próxima observação (ADR-0003, RF-SIM-01 CA-01.1 e CA-01.5).

**Onde a escolha é pior.** Um bot real teria negociado durante a lacuna, a preços que o estudo não conhece. Repetir as ordens depois, todas ao mesmo preço, subestima um líder cujo ganho está em operações curtas e pode produzir uma rajada de ordens pequenas que a ordem mínima descarta. E o enunciado do teste de mutação fica mais difícil de ler do que "o que vem depois do corte não muda o que veio antes".

## Alternativas descartadas

**Contabilizar no instante nominal, com o preço da próxima observação.** É a leitura mais direta de "usa a próxima observação" e mantém o instante da ordem em t + Δ. Descartada porque faz um trecho da simulação depender de um preço que ainda não existia, que é lookahead por outro caminho.

**Alinhar de uma vez ao estado mais recente do líder, com uma execução só por ativo.** É o que um bot faria ao voltar de uma queda: olha onde o líder está e ajusta. Descartada porque tudo o que o líder fez durante a lacuna some sem custo, o que favorece a cópia, e porque quebra a regra de que cada evento gera uma ordem.

**Usar só os eventos até t, como a frase do ADR-0003 diz.** Mantém o enunciado original do teste de mutação. Descartada porque a ordem atrasada calcularia o teto com uma carteira que não existe mais e poderia mandar fechar uma posição aberta legitimamente depois.

**Não copiar o evento sem preço.** É simples e não inventa nada. Descartada porque deixa o seguidor com posição que o líder já fechou, ou sem a que ele abriu, até o próximo evento naquele ativo.

## Consequências

- RF-SIM-01 CA-01.2 e CA-01.5 já estão escritos assim nos requisitos 1.2.
- O ADR-0003 recebe uma errata que aponta para este.
- O relatório conta as execuções atrasadas e mostra o atraso efetivo, por ativo.
- Na Rota B, a regra de cobertura mínima de 95% é o que limita o peso deste caso no resultado.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Sem preço em t + Δ, a execução acontece na primeira observação, com o patrimônio e os preços dela | `test_delayed_execution_is_processed_at_effective_instant` |
| A ordem atrasada usa a visão do líder formada pelas execuções já processadas | `test_delayed_order_uses_view_of_processed_events` |
| Abrir e fechar dentro de uma lacuna gera duas ordens ao mesmo preço, com custo e sem ganho | `test_round_trip_inside_gap_pays_costs_and_captures_nothing` |
| Mutação depois do corte, pelo relógio da execução, não muda as ordens executadas até c + Δ | `test_mutating_future_does_not_change_orders_decided_before_cutoff` |
| Uma ordem executada em τ só depende de eventos com instante ≤ τ − Δ | `test_reading_beyond_information_set_raises` |

## Revisitar quando

Mais de 5% dos eventos de uma coorte executarem com atraso, em qualquer rota. Nesse ponto o caso deixa de ser exceção e passa a pesar no resultado.
