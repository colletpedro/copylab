# ADR-0001 — Usar fills públicos da Hyperliquid como fonte de sinal

**Status:** aceito
**Data:** 2026-10-05
**Contexto de decisão:** Fase 1 — ingestão e coletor

## Contexto

Copiar um trader exige saber, com timestamp confiável, o que ele fez. Executar a cópia é a parte fácil: toda corretora tem API de ordens. A parte difícil é observar o líder, e ela define o projeto inteiro: que traders existem para escolher, que histórico há para simular, que latência é possível e quanto custa obter os dados.

As restrições reais: custo zero de dados, um desenvolvedor, capital pequeno, residência no Brasil, e a exigência de que o histórico seja suficiente para simular antes de arriscar dinheiro.

## Decisão

O sinal vem dos fills de carteiras públicas da Hyperliquid, lidos pela API de informação e pelo WebSocket oficiais. O universo se limita aos perpétuos do primeiro dex. O estudo usa a mesma corretora como referência de preço na Rota B.

## Justificativa

- **É a única fonte oficial e documentada de fills por conta.** Qualquer endereço pode ser consultado, sem autenticação, com instante, preço, tamanho, posição anterior e indicação de taker ou maker.
- **O histórico vem junto.** A API devolve até 10.000 fills por carteira, o que basta para carteiras de frequência baixa, que são justamente as copiáveis com atraso de segundos.
- **O fluxo público de negócios traz os endereços das duas pontas.** Isso permite gravar, daqui para a frente, a atividade de todas as carteiras do universo, inclusive as que quebrarem. É o caminho para eliminar o viés de sobrevivência numa rodada futura.
- **Sinal e execução na mesma corretora.** Um bot futuro executaria onde o líder executa, sem diferença de preço entre corretoras.

**Onde a escolha é pior.** A população é só a de traders da Hyperliquid, e análises informais indicam que apenas cerca de 14% a 17% das carteiras lucram. O histórico gratuito trunca em 10.000 fills, o que exclui carteiras muito ativas. A corretora não tem KYC, e a situação regulatória de um residente no Brasil operando nela não foi verificada. Uma fase com dinheiro real exigiria autocustódia, com o risco operacional correspondente. Nada disso pesa num estudo somente leitura, mas tudo pesa na decisão de construir o bot.

## Alternativas descartadas

**Líderes de copy trading da Binance.** É onde o capital do usuário já está, tem spot e tem copy trading nativo. Descartada porque a API oficial de copy trading serve ao próprio líder e não expõe posições de terceiros. O que existe são endpoints internos do site, não documentados, com relatos de quebra, e o líder pode ocultar as posições. Voltaria a ser a resposta certa se a Binance publicasse fills de líderes por API oficial.

**Líderes de copy trading da OKX.** Tem endpoints públicos e oficiais de ranking, posições atuais e histórico de posições, além de ambiente de demonstração. Descartada como fonte primária porque entrega posições por consulta periódica, não fills com timestamp, e porque a disponibilidade no Brasil e a cobertura de spot não foram confirmadas. É a segunda opção se a Hyperliquid se tornar inviável.

**Polymarket.** Tem API pública de negócios por carteira, e um estudo recente encontrou que operações copiadas lá superam as operações próprias do mesmo seguidor. Descartada porque está bloqueada no Brasil e só permite fechar posições.

**Agregadores (Copin, Nansen).** Entregam dados já limpos e classificados, de dezenas de corretoras. Descartados porque exigem chave ou pagamento e porque o projeto herdaria a curadoria deles, que é exatamente a parte que este estudo quer medir por conta própria.

## Consequências

- O código desta fase não precisa de chave, carteira nem assinatura. Isso vira regra verificável (RNF-09).
- A ingestão precisa respeitar 1.200 de peso por minuto por IP. Uma página de 2.000 fills custa cerca de 120 de peso, o que dá da ordem de 10 páginas por minuto.
- Assinaturas de usuário por WebSocket aceitam no máximo 10 usuários distintos por IP. A coorte fica limitada a K ≤ 10 (RNF-11). Um bot futuro contornaria isso pelo fluxo público de negócios, a confirmar.
- Carteiras com mais de 10.000 fills desde o início da janela são excluídas e contadas.
- Fills de spot e de perpétuos HIP-3 são gravados e marcados, mas não copiados.
- A posição do líder é reconstruída dos fills, e por isso a continuidade de posição passa a ser invariante de dado (RF-ING-03).

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Nenhum módulo importa cliente de ordens, assinatura ou chave | `test_architecture_no_order_or_signing_imports` |
| O peso por minuto nunca excede o limite | `test_rate_budget_never_exceeds_limit` |
| Fills consecutivos de um ativo encadeiam a posição | `test_position_continuity_detects_missing_fill` |
| Fills fora do universo são gravados e marcados, nunca descartados | `test_out_of_universe_fills_are_kept_and_flagged` |

## Revisitar quando

A Hyperliquid restringir a API de informação ou reduzir a retenção; a Binance ou a OKX passarem a publicar fills de líderes por API oficial; ou surgir restrição legal a residentes no Brasil. Qualquer um dos três reabre a decisão antes de uma fase com dinheiro real.
