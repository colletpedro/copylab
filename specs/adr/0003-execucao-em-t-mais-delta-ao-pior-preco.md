# ADR-0003 — Executar o seguidor em t + Δ, ao pior preço observado

**Status:** aceito
**Data:** 2026-10-05
**Contexto de decisão:** Fase 1 — simulador (execução)

## Contexto

O seguidor só pode agir depois de ver o que o líder fez. Entre o fill do líder e a ordem do seguidor chegar ao livro passam a propagação do dado, o processamento e o envio. Um simulador que execute o seguidor no instante e ao preço do líder não mede cópia nenhuma: mede o próprio líder.

O erro é fácil de cometer sem perceber. Basta usar o preço do fill do líder como preço do seguidor, ou deixar o simulador consultar a lista completa de fills para decidir uma ordem. O resultado parece ótimo e não se reproduz ao vivo.

Há uma segunda dificuldade: o preço em t + Δ não é observado exatamente nesse instante. Na Rota A há uma série por segundo de outra corretora. Na Rota B há retratos do livro a cada meio segundo, aproximadamente.

## Decisão

Um evento do líder no instante t gera uma ordem do seguidor executada em t + Δ. A decisão usa apenas eventos com instante ≤ t. O preço é sempre o pior, para o seguidor, entre os compatíveis com o que foi observado:

- **Rota A:** compra ao máximo e venda ao mínimo do segundo do preço proxy que contém t + Δ, mais um slippage em bps contra o seguidor.
- **Rota B:** a ordem percorre os níveis gravados do livro, usando a pior entre as duas observações adjacentes a t + Δ.
- **Sem observação em t + Δ:** usa-se a próxima existente, e o atraso efetivo é registrado. Nenhum preço é interpolado ou inventado.

A invariante é imposta por construção: o simulador expõe a cada componente apenas eventos do líder até τ − Δ e preços até o permitido para τ. Leitura além disso levanta exceção.

## Justificativa

- **Corresponde a um fluxo executável.** Um bot real vê o fill, calcula e envia. Δ é o parâmetro que resume esse caminho, e a grade (1, 5 e 30 segundos) cobre de um bot bem hospedado até uma cópia manual rápida.
- **É falseável.** Alterar arbitrariamente tudo o que vem depois de um corte não pode mudar nenhuma ordem decidida antes dele. Se qualquer lookahead entrar no código, esse teste quebra.
- **Erra para o lado pessimista.** Dentro de um segundo, ou entre dois retratos do livro, não se sabe a que preço a ordem sairia. Escolher o pior faz o estudo subestimar a cópia em vez de superestimá-la. Um resultado positivo sob essa regra vale mais do que sob uma regra neutra.
- **A mesma regra com Δ = 0 dá a referência.** A coorte simulada com Δ = 0 na mesma fonte de preço isola o custo do atraso, sem misturar a diferença de preço entre corretoras.

**Onde a escolha é pior.** O pessimismo tem custo: com Δ de 1 segundo, o pior preço do segundo pode exagerar o custo real em ativos voláteis. E Δ constante não representa a cauda da latência real, que é quando mais importa. A Rota B mede a latência de recebimento de verdade e a reporta ao lado da grade.

## Alternativas descartadas

**Executar ao preço do fill do líder.** Dá um resultado limpo e comparável ao do líder. Descartada: é lookahead direto, e é a premissa escondida em toda tela que promete "copie este trader e ganhe o que ele ganhou".

**Executar ao último preço negociado em t + Δ.** É neutro e simples. Descartada porque o último negócio pode ter sido do outro lado do spread, e porque na Rota A a série tem resolução de um segundo: usar o fechamento do segundo que contém t + Δ é usar um preço até um segundo no futuro.

**Executar ao preço médio do intervalo.** Reduz o ruído. Descartada porque ninguém consegue negociar uma média, e porque a média suaviza justamente os momentos de movimento rápido, que é quando os líderes costumam operar.

**Latência aleatória, sorteada de uma distribuição.** É mais realista que um valor constante. Descartada nesta fase porque não há distribuição medida para sortear, e uma inventada seria um parâmetro livre a mais. Volta à mesa quando a Rota B tiver medido a latência real.

**Ordem limite ao preço do líder, esperando execução.** É o que um copiador paciente faria, e economiza spread e taxa. Descartada porque exige modelar fila e probabilidade de execução, e porque uma ordem que não executa quando o preço foge é exatamente a operação que mais importava copiar.

## Consequências

- O preço do fill do líder nunca entra no cálculo do preço do seguidor. Ele serve só para reconstruir a posição e o PnL do próprio líder.
- Evento cujo t + Δ cai depois do fim da janela não é executado e é reportado como pendente.
- A fronteira do teste de mutação precisa ser escrita com cuidado: a decisão em t executa legitimamente com o preço observado em t + Δ, então esse preço não é livre para alterar. O livre começa depois da última observação consumida. Um teste que altere cedo demais acusa lookahead onde há execução correta.
- Na Rota A, o slippage é premissa, não medida. O relatório declara isso e mostra a grade.
- Em lacunas do livro, a ordem executa na próxima observação, com atraso efetivo maior que Δ, registrado na ordem.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Alterar eventos, preços e funding posteriores ao corte não muda as ordens decididas até o corte | `test_mutating_future_does_not_change_orders_decided_before_cutoff` |
| Leitura de evento posterior a τ − Δ, ou de preço além do permitido para τ, levanta exceção | `test_reading_beyond_information_set_raises` |
| O preço do fill do líder nunca é usado como preço do seguidor | `test_follower_price_is_independent_of_leader_fill_price` |
| Rota A: compra ao máximo e venda ao mínimo do segundo que contém t + Δ | `test_route_a_uses_worst_price_of_execution_second` |
| Rota B: usa a pior das duas observações adjacentes | `test_route_b_uses_worst_of_adjacent_book_snapshots` |
| Sem observação, usa a próxima existente e registra o atraso efetivo | `test_missing_price_uses_next_observation_and_records_delay` |
| Evento com t + Δ após o fim da janela fica pendente | `test_event_past_window_end_is_reported_pending` |
| Com Δ = 0, sem custo e sem restrição, numa série em que o preço observado é o do líder, o PnL do seguidor é o do líder na escala dele | `test_ideal_copy_reproduces_leader_pnl_at_follower_scale` |

## Nota para defesa em entrevista

Δ é o *decision lag* do sistema, e a curva do resultado em função de Δ é uma medida de *alpha decay*: quanto do ganho do líder desaparece por segundo de atraso. Um líder cujo resultado some em 5 segundos estava ganhando com velocidade, e isso não se copia. Um líder cujo resultado mal muda entre 1 e 30 segundos estava ganhando com direção, e isso se copia. A grade de Δ existe para distinguir os dois.

## Revisitar quando

A Rota B tiver medido a distribuição real do atraso de recebimento, o que permite trocar Δ constante por latência sorteada; ou quando uma fase futura considerar ordens limite para o seguidor.
