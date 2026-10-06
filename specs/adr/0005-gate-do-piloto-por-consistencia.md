# ADR-0005 — Liberar um piloto de US$ 50 pela Rota A e por uma semana de consistência

**Status:** aceito
**Data:** 2026-10-05
**Contexto de decisão:** Fase 1 — veredito e passagem para a Fase 2

## Contexto

O plano original só admitia dinheiro real depois do veredito prospectivo de 30 dias. O dono do projeto quer tentar algo de verdade antes disso, com um valor que aceita perder, enquanto o estudo completo continua e produz o resultado robusto.

Duas forças puxam em sentidos opostos. Uma semana copiando uma única carteira tem poucas operações e não distingue acerto de sorte: usá-la como prova de que a cópia rende seria decidir quase ao acaso. Por outro lado, um piloto pequeno entrega o que nenhuma simulação entrega, que é a ordem real, com o preço, a latência e as falhas reais.

A regra precisa ser escrita antes de qualquer dado ser lido, e precisa deixar claro o que cada resultado prova e o que não prova.

## Decisão

O piloto é liberado se, e somente se, valem as quatro condições, no cenário primário:

1. A Rota A atingiu o critério: retorno líquido positivo e acima de comprar e manter BTC.
2. Na semana ao vivo, o retorno líquido da cópia simulada com o livro gravado é ≥ −10%.
3. Na semana ao vivo, a diferença entre o retorno simulado com o livro gravado e o simulado com o preço proxy é, em módulo, ≤ 1 ponto percentual.
4. Há coorte, nenhuma subconta congelou e a cobertura do livro foi suficiente.

O gate é computado uma única vez. Semana com cobertura abaixo de 95% se estende por no máximo 3 dias; além disso, o gate é inconclusivo e conta como não atingido.

**Condições do piloto**, que a spec dele herda:

- Capital real de no máximo US$ 50, sem aportes.
- Mesma coorte, mesma regra de espelhamento e mesmo teto de 1x do congelamento da Rota B.
- Chave que opera e não saca.
- Um período em modo sombra, com ordens simuladas em tempo real, antes da primeira ordem real.
- Encerramento se o veredito de 30 dias não atingir o critério.

O estudo de 30 dias continua pelas regras do congelamento, com ou sem piloto.

## Justificativa

- **O peso estatístico fica na Rota A.** Ela avalia 30 dias, não 7. A semana ao vivo não é chamada a provar que a cópia rende.
- **A semana confere o que só o livro real pode conferir.** A Rota A supõe preço de outra corretora e slippage por premissa. Se a diferença entre as duas fontes ficar dentro de 1 ponto percentual, as premissas se sustentam para aquela carteira e aquele capital. Se não, a Rota A não vale como base.
- **"Semana positiva" seria ruído.** Com uma carteira e poucos episódios, o sinal do retorno semanal reprovaria ou aprovaria quase ao acaso. O limite de −10% só barra o desastre.
- **O piloto compra uma medida, não um retorno.** O que ele produz de valor é a divergência entre cada ordem simulada e a ordem real correspondente. É a validação do simulador, e a simulação não consegue produzi-la sozinha.
- **O risco é limitado por construção.** US$ 50, alavancagem de 1x e chave sem saque.

**Onde a escolha é pior.** O piloto começa com evidência mais fraca que o veredito de 30 dias. A Rota A carrega viés de sobrevivência e preço proxy, e no cenário primário a coorte tem uma carteira só. O lucro ou o prejuízo do piloto não prova nada sobre a estratégia, e existe o risco de ser lido como se provasse. Dinheiro real em jogo também cria a tentação de ajustar as regras do estudo no meio do caminho.

## Alternativas descartadas

**Esperar o veredito de 30 dias.** É a evidência mais forte que esta fase produz e era o plano original. Descartada como condição do piloto porque o risco aceito é pequeno e fixo, e porque o piloto gera um dado que o estudo não gera. Continua sendo a condição para qualquer valor acima de US$ 50.

**Liberar por semana positiva.** É a regra intuitiva e a mais fácil de explicar. Descartada porque, com essa amostra, o sinal do retorno é quase aleatório. Uma regra que aprova ao acaso parece um critério e não é.

**Liberar só pela Rota A, sem a semana.** Chegaria ao piloto uma semana antes. Descartada porque a Rota A nunca viu o livro da Hyperliquid, e a semana é a conferência barata dessa premissa.

**Piloto só em testnet.** Risco zero e exercita o caminho inteiro das ordens. Descartada como substituto porque a liquidez da testnet não é a do mercado real, e o preço de execução é justamente o que se quer medir. Não foi abandonada: é uma etapa natural da spec do piloto, antes do dinheiro real.

**Piloto com as mesmas carteiras da Rota A.** Usaria as carteiras já avaliadas em setembro. Descartada porque essa seleção foi feita com dados até agosto e estaria desatualizada. O estudo avalia a regra de seleção, não uma carteira específica.

## Consequências

- A fase passa a ter três marcos: triagem, gate do piloto e veredito de 30 dias.
- O resultado do piloto nunca entra no veredito do estudo. O veredito de 30 dias entra no piloto de uma única forma: como regra de encerramento.
- O relatório do gate precisa dizer, com essas palavras, que é uma verificação de consistência.
- Aumentar o capital real exige um ADR novo e o veredito de 30 dias atingido.
- Ficam como pendências da spec do piloto, a resolver antes de qualquer depósito: a situação regulatória de um residente no Brasil na Hyperliquid, os custos fixos de entrada e saída, o limite de perda e o mecanismo de desligamento.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| O gate é atingido se, e somente se, as quatro condições valem | `test_pilot_gate_requires_all_four_conditions` |
| Cada condição, isolada, reprova o gate quando falha | `test_pilot_gate_fails_on_each_single_condition` |
| Gate já computado não é recomputado com outra janela, cenário ou limite | `test_pilot_gate_refuses_recomputation` |
| Cobertura insuficiente estende a semana por até 3 dias e depois reprova | `test_live_week_extends_then_fails_on_low_coverage` |
| A comparação entre livro e proxy usa a mesma coorte, o mesmo cenário e o mesmo intervalo | `test_source_comparison_shares_cohort_scenario_and_interval` |
| O relatório do gate declara que é verificação de consistência e repete o teto de capital | `test_gate_report_states_consistency_check_and_capital_cap` |

## Revisitar quando

O piloto tiver medido a divergência entre ordens simuladas e reais, o que diz se os limites de 10% e de 1 ponto percentual estavam folgados ou apertados. A revisão vale para rodadas futuras, nunca para um gate já computado. Também reabre se houver intenção de operar com mais de US$ 50.
