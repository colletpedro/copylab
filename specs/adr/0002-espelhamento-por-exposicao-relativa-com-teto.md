# ADR-0002 — Espelhar a exposição relativa do líder, com teto de alavancagem de 1x

**Status:** aceito
**Data:** 2026-10-05
**Contexto de decisão:** Fase 1 — simulador (dimensionamento e risco)

## Contexto

O líder opera perpétuos, long e short, muitas vezes alavancado, com um patrimônio que pode ser milhares de vezes o do seguidor. O seguidor tem capital pequeno, não aceita risco de liquidação e precisa de uma regra que diga, para cada movimento do líder, quanto comprar ou vender.

A regra precisa de três propriedades. Tem de limitar o risco do seguidor independentemente do que o líder faça. Tem de preservar a informação que está no tamanho das posições do líder, não só na direção. E tem de ser calculável com os dados que a API gratuita entrega com segurança.

## Decisão

O seguidor mantém, em cada ativo, uma posição-alvo proporcional à do líder:

```
alvo(c) = pico × ( notional do líder em c / N* ) × patrimônio do seguidor
```

- `N*` é a referência de exposição do líder: o percentil 95, ponderado pelo tempo, da exposição bruta em dólares dele no universo durante a janela de seleção. É calculada só com dados anteriores ao corte e congelada com a coorte.
- `pico` (default 1,0) é a alavancagem do seguidor quando o líder está na exposição de referência.
- **Teto:** se a soma dos módulos dos alvos exceder `teto × patrimônio` (default 1,0), todos os alvos são multiplicados pelo mesmo fator. Reduções são executadas antes de aumentos.
- A cada evento do líder, a ordem do seguidor é `alvo − posição atual`, arredondada para baixo ao lote. Ordem abaixo de US$ 10 não é enviada; a diferença é reavaliada no próximo evento. Zerar uma posição é sempre executável.
- Só episódios abertos a partir de zero dentro da janela são copiados.
- A variante **só compras** substitui alvo negativo por zero e mantém todo o resto. Ela roda sempre, como coluna de controle.

## Justificativa

- **O risco do seguidor não depende do líder.** Um líder a 20x e um a 0,5x resultam em exposição do seguidor entre 0 e 1x. A liquidação exigiria um movimento de preço da ordem de dobrar contra um short, ou de ir a quase zero contra um long.
- **A informação de tamanho é preservada.** Como a escala é a exposição típica de pico do próprio líder, reduzir a posição pela metade leva o seguidor a reduzir pela metade. Um simples corte em 1x apagaria isso: um líder que varia entre 2x e 6x pareceria estar sempre em 1x.
- **Depende só de fills.** `N*` e as posições saem dos fills, que são o dado mais confiável da API. Não é preciso histórico de patrimônio do líder, cuja resolução na API gratuita é desconhecida e que aportes e saques contaminam.
- **Seguir alvo é mais robusto que seguir fills.** Uma ordem que não coube no mínimo não é perdida: a diferença continua existindo e é corrigida no próximo evento.

**Onde a escolha é pior.** O seguidor não replica a alavancagem do líder em relação ao patrimônio dele, e por isso o retorno do seguidor não é comparável ao retorno percentual que o líder exibe. Se o líder aportar ou sacar muito depois do corte, `N*` fica desatualizado: o teto protege para cima, mas para baixo o seguidor fica subexposto. E mapear o pico do líder para 1x usa mais do capital do seguidor do que um líder conservador usa do dele.

## Alternativas descartadas

**Só spot (ou só compras).** Nenhum risco de liquidação e o capital pode ficar numa corretora centralizada. Descartada como cenário principal porque ignora todos os shorts, inclusive os usados como proteção, e portanto copia metade da estratégia. Não foi abandonada: é a variante de controle, e a diferença entre as duas colunas mede quanto os shorts valem.

**Replicar a alavancagem do líder.** É a cópia mais fiel e a única em que o retorno do seguidor acompanha o do líder em percentual. Descartada porque transfere ao seguidor um risco de liquidação que ele não aceita e que o atraso piora: o seguidor entra depois e pode ser liquidado numa oscilação a que o líder sobrevive pondo mais margem.

**Proporção de patrimônio (exposição do líder dividida pelo patrimônio dele), com corte em 1x.** É o modelo das plataformas comerciais e é intuitivo. Descartada porque exige o patrimônio do líder em cada instante, e porque o corte em 1x apaga a variação de tamanho de qualquer líder que opere acima de 1x. Volta a ser candidata se houver uma série confiável de patrimônio e o teto for maior.

**Valor fixo por operação.** Trivial de implementar e de explicar. Descartada porque ignora o tamanho relativo das posições, que é parte do sinal, e porque não define o que fazer em reduções parciais.

**Uma ordem do seguidor para cada fill do líder.** É o que os bots abertos fazem. Descartada porque uma ordem do líder dividida em trinta fills viraria trinta ordens abaixo do mínimo, todas perdidas, e a posição do seguidor se afastaria da do líder sem mecanismo de correção.

## Consequências

- O que o estudo mede é "copiar o perfil de exposição a 1x", e o relatório precisa dizer isso com essas palavras.
- O mínimo de US$ 10 por ordem passa a ser uma restrição central. Com capital de US$ 100 em duas subcontas, cada uma tem US$ 50, e posições do líder abaixo de 20% da referência não são copiadas. Por isso o número de subcontas depende do capital: cada uma precisa valer várias vezes a ordem mínima. O relatório conta e mostra isso (RF-ANA-04).
- O teto vale no momento da ordem. Entre eventos, a variação de preço pode levar a alavancagem acima de 1x, o que é permitido e reportado, sem redução forçada.
- Posições do líder anteriores à janela são ignoradas até fecharem.
- `N*` entra no arquivo de congelamento e não é recalculado durante a avaliação.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Após as ordens de um evento, exposição bruta ≤ teto × patrimônio, com tolerância de um lote | `test_gross_exposure_never_exceeds_cap_after_event` |
| Líder na exposição de referência em um ativo ⇒ seguidor em `pico × patrimônio` | `test_target_at_reference_exposure_equals_peak_times_equity` |
| Alvos acima do teto são reduzidos pelo mesmo fator, com reduções antes de aumentos | `test_cap_scales_all_targets_proportionally_reductions_first` |
| Ordem abaixo do mínimo não é enviada e a diferença persiste | `test_below_minimum_order_is_skipped_and_delta_persists` |
| Zerar é sempre executável, mesmo abaixo do mínimo | `test_full_close_executes_below_minimum` |
| Posição anterior à janela não é copiada até voltar a zero | `test_preexisting_leader_position_is_ignored_until_flat` |
| Variante só compras é a mesma simulação com alvos negativos zerados | `test_long_only_variant_equals_engine_with_shorts_dropped` |
| `N*` usa apenas dados anteriores ao corte | `test_reference_exposure_ignores_data_at_or_after_cutoff` |

## Revisitar quando

A Rota B mostrar que mais da metade do notional do líder deixa de ser copiada por causa do mínimo ou do teto, o que indicaria que a regra, e não o mercado, determina o resultado. Também quando existir uma série confiável de patrimônio do líder, ou se o teto de alavancagem deixar de ser 1x.

## Errata — 2026-10-06

O corpo acima fica como foi escrito. O design da Fase 1 encontrou dois pontos.

1. **O teto tem uma exceção que a tabela de invariantes não previu.** A decisão traz duas regras que se chocam num caso: a exposição depois de um evento respeita o teto, e ordem abaixo do mínimo não é enviada. Quando o preço anda contra o seguidor entre eventos, a exposição passa do teto sem ordem nenhuma. No evento seguinte, a redução que traria a carteira de volta pode ficar abaixo do mínimo, e então não pode ser enviada. Nesse caso o excesso permanece e é contado, e nenhum aumento é executado enquanto ele durar. A invariante da tabela, "exposição bruta ≤ teto × patrimônio após as ordens de um evento", passa a valer assim: nenhuma ordem que aumenta a exposição leva a carteira acima do teto, e toda redução que o teto exige é enviada, salvo a que cai abaixo do mínimo (RF-SIM-02 CA-02.7). A decisão não muda.
2. **A definição de `N*` foi refinada pelo ADR-0007.** O percentil passa a ser medido só sobre o tempo em posição. Isso altera um item da seção Decisão, e por isso está em ADR próprio, e não nesta errata.

## Errata — 2026-10-07

O item 1 da errata anterior diz que a única redução exigida pelo teto que fica sem enviar é a que cai abaixo do mínimo. Há um segundo caso, encontrado na leitura cruzada do design: o ativo a reduzir pode não ter observação de preço naquele instante. Nenhum preço é inventado, então essa redução também não é enviada. O tratamento é o mesmo: o excesso é contado, e nenhum aumento é executado enquanto ele durar (RF-SIM-02 CA-02.7).

Fica também explícito quanto se reduz: o mínimo que devolve a carteira ao teto, repartido entre os ativos em proporção ao que cada um excede do seu alvo (RF-SIM-02 CA-02.2). A decisão não muda.
