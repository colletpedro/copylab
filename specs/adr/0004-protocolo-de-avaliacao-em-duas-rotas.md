# ADR-0004 — Avaliar em duas rotas: triagem retrospectiva e veredito prospectivo

**Status:** aceito
**Data:** 2026-10-05
**Contexto de decisão:** Fase 1 — seleção e avaliação

## Contexto

A pergunta do estudo é se uma regra fixa de escolha de carteiras, aplicada num instante, produz uma cópia que rende depois desse instante. Responder com honestidade exige três coisas: escolher sem ver o futuro, medir com preços a que o seguidor realmente executaria, e não escolher entre carteiras que só existem hoje porque sobreviveram.

Os dados gratuitos não entregam as três ao mesmo tempo. O histórico de fills existe, mas a lista de candidatas é a de hoje. O livro de ofertas da Hyperliquid não tem histórico gratuito: o que não for gravado agora não se recupera. O arquivo completo, com todos os fills de todas as carteiras e o livro, existe num bucket pago por quem baixa.

A restrição do projeto é custo zero. A restrição do método é que o critério foi combinado antes de qualquer dado ser lido e precisa continuar assim.

## Decisão

Duas rotas, com o mesmo simulador, a mesma regra de seleção e o mesmo critério.

**Rota A — triagem retrospectiva.** Seleção com dados de 2026-07-01 a 2026-08-31, corte em 2026-09-01, avaliação em setembro de 2026. Preço do seguidor pelo perpétuo equivalente na Binance. O resultado é rotulado "triagem".

**Rota B — avaliação prospectiva.** O coletor grava o livro e o fluxo de negócios a partir do primeiro dia. Quando o simulador existir, a mesma regra de seleção é aplicada aos 62 dias anteriores, e a coorte é congelada e publicada no repositório remoto. A avaliação cobre os 30 dias seguintes, com preço do livro gravado, e tem dois marcos: a semana ao vivo, aos 7 dias, e o veredito do estudo, aos 30.

**Pré-registro.** Coorte, referências de exposição, parâmetros e hashes dos dados vão para um arquivo de congelamento antes de qualquer leitura da janela de avaliação. O comando de avaliação se recusa a rodar sem ele. A Rota A não pode alterar a regra da Rota B depois de vista.

O que cada resultado libera está no ADR-0005.

## Justificativa

- **A Rota A responde em dias e custa nada.** Ela exercita o sistema inteiro com dado real, que é onde aparecem os erros que as fixtures não preveem, e diz cedo se a ideia tem alguma chance.
- **A Rota B não tem como olhar o futuro.** A coorte é publicada antes de os dados da avaliação existirem. Não é disciplina de quem roda, é o calendário.
- **A Rota B mede o preço em vez de supor.** O slippage deixa de ser premissa e passa a ser o livro gravado.
- **O livro só se obtém gravando.** Começar o coletor no primeiro dia é a única decisão desta fase que não pode ser adiada sem perda.
- **Dois resultados independentes com a mesma regra.** Se as duas rotas concordam, a conclusão é mais forte que qualquer uma sozinha. Se discordam, a discordância mostra onde as premissas da Rota A falham.

**Onde a escolha é pior.** A Rota B demora no mínimo 30 dias e exige uma máquina ligada. A seleção das duas rotas parte do leaderboard de hoje, e portanto herda o viés de sobrevivência: a Rota B evita o lookahead, não a sobrevivência. Uma janela de 30 dias com cinco carteiras é amostra pequena, e um resultado positivo nela é indício, não prova. E o critério compara com comprar e manter BTC: num mês de queda forte ele é fácil de bater, num mês de alta forte é difícil.

## Alternativas descartadas

**Baixar o arquivo histórico pago (Rota C).** É a resposta metodologicamente melhor: todas as carteiras, inclusive as que quebraram, e o livro real para qualquer período. O custo estimado é de poucos dólares por mês de fills; o do livro não foi estimado. Descartada nesta fase porque a restrição é custo zero e exige conta em nuvem com cartão. É a primeira coisa a reabrir se a Rota A for promissora.

**Só a Rota A.** Entrega um veredito em dias. Descartada como veredito porque o preço é de outra corretora, o slippage é suposto e a lista de candidatas vem depois do período avaliado. Serve para triar, e por isso nunca libera nada sozinha.

**Só a Rota B.** É a mais limpa das duas. Descartada porque passar 30 dias sem nenhum resultado significa descobrir os erros do simulador só no fim, e porque a seleção da Rota B precisa de um simulador já testado em dado real.

**Validação cruzada em várias janelas (walk-forward).** Daria vários resultados fora da amostra em vez de um. Descartada nesta fase porque o histórico gratuito, limitado a 10.000 fills, não sustenta várias janelas para as mesmas carteiras, e porque adiciona um mecanismo a validar antes de o básico estar provado. É o passo natural depois da Rota C.

**Selecionar pelo leaderboard de PnL ou ROI.** É o que qualquer pessoa faria e é o que as plataformas mostram. Descartada porque as janelas de desempenho do leaderboard cobrem o período de avaliação da Rota A, o que seria olhar o futuro, e porque há evidência publicada de que ranking de plataforma tem correlação fraca com retorno futuro.

## Consequências

- A fase fecha em três partes: triagem, semana ao vivo e veredito de 30 dias. O Definition of Done separa as três.
- O coletor é a primeira coisa a entrar em operação, antes mesmo de o simulador existir. O livro gravado antes do congelamento da Rota B serve para comparar o preço proxy com o livro real.
- Do leaderboard, a seleção lê apenas endereços e patrimônio. Ler qualquer campo de desempenho levanta exceção.
- O patrimônio lido do leaderboard é o de hoje. Isso é o vazamento residual da Rota A e fica declarado em todo relatório.
- Na seleção da Rota B, o ranking usa o preço proxy, porque o livro não cobre os 62 dias anteriores. A avaliação usa o livro.
- Lacunas do coletor estendem a janela da Rota B pela regra dos parâmetros pré-registrados. Além do limite, a rota é declarada inconclusiva, e não aprovada nem reprovada.
- O veredito de 30 dias é o resultado do estudo. Ele segue as regras do congelamento com ou sem piloto em andamento. O que libera o piloto é decidido no ADR-0005.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Alterar qualquer dado a partir do corte não muda coorte, referências de exposição nem congelamento | `test_mutating_evaluation_window_does_not_change_frozen_cohort` |
| A seleção não lê dado com timestamp a partir do corte | `test_selection_reading_at_or_after_cutoff_raises` |
| A seleção não lê campos de desempenho do leaderboard | `test_selection_reading_leaderboard_performance_raises` |
| A avaliação recusa rodar sem congelamento ou com hash divergente | `test_evaluate_refuses_without_matching_freeze` |
| Mesma semente e mesmos dados produzem as mesmas coortes de controle | `test_control_cohorts_are_deterministic_for_seed` |
| Veredito da Rota A sai rotulado como triagem | `test_route_a_verdict_is_labelled_triage` |
| O veredito de 30 dias não depende do gate nem do piloto | `test_thirty_day_verdict_ignores_gate_and_pilot` |
| Critério não atingido quando não há coorte ou uma subconta congelou | `test_verdict_fails_without_cohort_or_with_frozen_subaccount` |

## Revisitar quando

A Rota A atingir o critério, o que justifica gastar com a Rota C para repetir o estudo sem viés de sobrevivência; ou quando o coletor tiver 92 dias de fluxo de negócios gravado, o que permite selecionar entre todas as carteiras que operaram no período, sem depender do leaderboard.
