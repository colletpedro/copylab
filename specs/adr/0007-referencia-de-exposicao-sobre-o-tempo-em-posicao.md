# ADR-0007 — Medir a referência de exposição só sobre o tempo em posição

**Status:** aceito (2026-10-07, com o gate de design da Fase 1)
**Data:** 2026-10-06
**Contexto de decisão:** Fase 1 — seleção (referência de exposição)
**Refina:** a definição de `N*` na seção Decisão do ADR-0002. Todo o resto do ADR-0002 continua valendo.

## Contexto

O ADR-0002 define `N*` como "o percentil 95, ponderado pelo tempo, da exposição bruta em dólares [do líder] no universo durante a janela de seleção". Lida como está escrita, a conta inclui o tempo em que o líder não tem posição nenhuma.

Ao escrever o design, a consequência apareceu. Se o líder passa uma fração `p` da janela posicionado, o percentil 95 sobre o tempo total corresponde ao percentil `1 − 0,05 / p` da exposição dele quando está posicionado:

| Tempo em posição | O que `N*` vira |
|---|---|
| 100% | percentil 95 da exposição em posição |
| 20% | percentil 75 |
| 10% | mediana |
| 5% ou menos | zero, e o líder fica inelegível |

Os filtros aprovados admitem líderes assim. Vinte episódios com duração mediana de uma ou duas horas somam de 20 a 40 horas em 1.488, ou seja, entre 1% e 3% da janela. Esse líder passa em F4 e F6 e seria eliminado por uma regra que ninguém decidiu.

Para quem fica acima de 5%, o efeito é outro: `N*` sai pequeno, o alvo do seguidor bate no teto sempre que o líder entra, e a informação de tamanho se perde. É exatamente o que o ADR-0002 dizia querer evitar.

Nenhum dado foi lido com a definição antiga. A mudança é anterior a qualquer seleção.

## Decisão

`N*` é o percentil 95, ponderado pelo tempo, da exposição bruta em dólares do líder no universo, medido **só sobre o tempo em que ele tem alguma posição aberta no universo**, dentro da janela de seleção.

- O percentil é o menor valor de exposição tal que o tempo passado nele ou abaixo dele é pelo menos 95% do tempo em posição. Não há interpolação.
- Cada posição é medida ao preço do último fill do líder naquele ativo.
- Líder sem posição no universo na janela tem `N*` indefinido e é inelegível.

## Justificativa

- **Mede o que o nome diz.** A referência é a exposição típica de pico do líder quando ele está no mercado. Quanto tempo ele passa fora não muda o tamanho das posições que ele abre.
- **Não esconde um filtro.** O que decide se um líder opera o bastante são F4, F5 e F6, que estão escritos, têm limiar e aparecem no funil.
- **Preserva a informação de tamanho.** Um líder esporádico que varia a posição entre a metade e o dobro continua levando o seguidor a variar na mesma proporção.
- **Continua dependendo só de fills anteriores ao corte.**

**Onde a escolha é pior.** Para um líder com poucas horas em posição, `N*` sai de pouca amostra e é mais ruidoso. Dois líderes com o mesmo perfil de tamanho, um posicionado 2% do tempo e outro 100%, recebem a mesma referência, e o capital do seguidor fica parado 98% do tempo com o primeiro. Isso não é corrigido aqui: quem mede se vale a pena é o ranking.

## Alternativas descartadas

**Tempo total da janela, como no ADR-0002.** É a leitura literal e a mais simples de explicar. Descartada pelos dois efeitos descritos no contexto: elimina líderes que os filtros aceitam e achata o sinal de tamanho dos demais.

**Exposição máxima na janela.** Garante que o seguidor nunca passe do teto por causa da escala. Descartada porque um único pico atípico define a referência, e o seguidor fica subexposto em todo o resto do tempo.

**Média da exposição em posição.** É estável e usa toda a amostra. Descartada porque o líder passa boa parte do tempo acima da própria média, e nesses momentos o teto cortaria o alvo e apagaria a variação de tamanho.

**Percentil 95 dos picos por episódio.** Trata cada operação como uma observação. Descartada porque ignora a duração e introduz um segundo conceito de exposição, diferente do que o simulador usa.

## Consequências

- RF-SEL-03 CA-03.1 já está escrito assim nos requisitos 1.2.
- O ADR-0002 recebe uma errata que aponta para este.
- O relatório de seleção mostra, para cada líder da coorte, quantas horas em posição sustentam o `N*` dele.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| `N*` é o percentil 95 ponderado pelo tempo, medido só sobre o tempo em posição | `test_reference_exposure_is_time_weighted_p95_over_time_in_position` |
| Acrescentar tempo sem posição não altera `N*` | `test_reference_exposure_ignores_flat_time` |
| Líder sem posição no universo é inelegível | `test_wallet_without_reference_exposure_is_ineligible` |
| `N*` usa apenas dados anteriores ao corte | `test_reference_exposure_ignores_data_at_or_after_cutoff` |

## Revisitar quando

A Rota B mostrar que as subcontas passam a maior parte do tempo em posição coladas no teto, o que indicaria referência baixa demais, ou quase sempre muito abaixo dele, o que indicaria o contrário.
