# Fase 1 (estudo de simulação) — Requisitos

**Status:** aprovada — versão 1.3, em 2026-10-07, junto com o gate de design
**Versão:** 1.3
**Data:** 2026-10-07
**Próximo gate:** `specs/00-plataforma/fase-1-tasks.md` (proposto)

> **Nota de organização:** como na Fase 1 do quantlab, esta fase é uma fatia vertical que atravessa vários módulos, e o critério de aceitação é único ("o estudo roda ponta a ponta e não mente"). Este documento é a fonte da verdade da fase. O pacote se chama `copylab` (D16).
>
> **A fase fecha em três partes.** A Rota A (retrospectiva) simula setembro de 2026 e entrega uma triagem em dias. A Rota B (prospectiva) tem dois marcos: aos 7 dias, a semana ao vivo, que junto com a Rota A decide o gate do piloto; aos 30 dias, o veredito do estudo. As duas rotas usam o mesmo simulador e o mesmo critério. Ver ADR-0004 e ADR-0005.

---

## 1. Objetivo

Medir quanto do resultado de um trader da Hyperliquid sobrevive quando ele é copiado por uma conta pequena, com atraso de segundos, taxas, funding, ordem mínima e teto de alavancagem de 1x. A fase entrega um instrumento de medição e um veredito mecânico contra um critério fixado antes de rodar.

O objetivo **não** é encontrar um trader lucrativo, operar dinheiro real nem construir o bot. "Copiar não compensa depois dos custos" é um resultado válido e será reportado como tal.

A fase também decide, por regra escrita antes dos dados, se um piloto com dinheiro real pode começar (RF-ANA-08). O piloto em si tem spec própria.

## 2. Escopo

**Dentro:**

- Verificação dos dados reais antes de congelar parâmetros
- Ingestão: leaderboard, fills por carteira, funding, metadados de ativos e preço proxy da Binance
- Coletor prospectivo: livro de ofertas e fluxo público de negócios do universo
- Seleção pré-registrada de carteiras, com isolamento temporal
- Simulador de cópia em perpétuos, long e short, com teto de 1x, e a variante só compras como coluna de controle
- Métricas, benchmarks, decomposição do custo de copiar e veredito
- Gate do piloto: a regra mecânica que libera, ou não, a fase com dinheiro real
- CLI e relatório

**Fora (e para onde vai):**

- Piloto com dinheiro real (bot, chaves, ordens, testnet) — spec própria (Fase 2), só se o gate do piloto for atingido (RF-ANA-08)
- Arquivo histórico pago da Hyperliquid (S3) — reabre por ADR novo (ver ADR-0004)
- Spot, perpétuos HIP-3 e outras corretoras como fonte de sinal — fora desta fase
- Ordens limite do seguidor — fase do piloto ou posterior
- Otimização de filtros ou parâmetros e walk-forward — fase posterior
- API HTTP e dashboard — fase posterior
- Tributação — fora do projeto

## 3. Glossário

| Termo | Definição operacional |
|---|---|
| **Líder** | Carteira (endereço) da Hyperliquid cujas operações são copiadas. |
| **Seguidor** | A conta simulada que copia. Nesta fase não existe conta real. |
| **Fill** | Uma execução de ordem: instante, ativo, lado, preço, tamanho e posição anterior. |
| **Perpétuo** | Contrato que acompanha o preço de um ativo, sem vencimento, com margem e funding. |
| **Notional** | Valor financeiro de uma posição ou ordem: tamanho × preço. |
| **Exposição bruta** | Soma dos módulos dos notionals de todas as posições abertas. |
| **Patrimônio** | Saldo em USDC mais o PnL não realizado das posições abertas. |
| **Alavancagem** | Exposição bruta dividida pelo patrimônio. |
| **Teto de alavancagem** | Máximo de alavancagem a que uma ordem do seguidor pode levá-lo. Default 1,0. |
| **Funding** | Pagamento horário entre posições long e short de um perpétuo. Taxa positiva: long paga. |
| **Episódio** | Intervalo em que a posição do líder em um ativo sai de zero e volta a zero. Inversão de sinal encerra um episódio e abre outro. |
| **Evento do líder** | O conjunto dos fills de um líder em um ativo no mesmo milissegundo. Uma ordem do líder costuma se dividir em muitos fills com o mesmo instante, e o seguidor decide uma vez só. O instante do evento é o `time` desses fills. |
| **Δ (atraso)** | Segundos entre o evento do líder e a execução do seguidor. |
| **Taker / maker** | Quem cruza o spread (`crossed = true`) e quem tinha ordem em repouso. O seguidor é sempre taker. |
| **bps** | Um centésimo de ponto percentual. 1 bps = 0,01%. |
| **Slippage** | Diferença entre o preço observado e o preço efetivamente executado. |
| **Preço proxy** | Preço do perpétuo equivalente na Binance, usado na Rota A no lugar do livro da Hyperliquid. |
| **Referência de exposição (N\*)** | Notional, em dólares, que representa a exposição típica de pico do líder na janela de seleção. Mapeia a escala do líder para a do seguidor. |
| **Janela de seleção** | Período cujos dados podem ser usados para escolher carteiras. |
| **Corte (T)** | Instante que separa seleção de avaliação. Nada com timestamp ≥ T entra na seleção. |
| **Janela de avaliação** | Período em que a coorte congelada é medida. |
| **Coorte** | As K carteiras escolhidas e congeladas no corte. |
| **Congelamento** | Arquivo versionado com coorte, parâmetros e hashes, gravado antes de qualquer leitura da janela de avaliação. |
| **Lookahead** | Usar, numa decisão, informação que só existiria depois dela. |
| **Viés de sobrevivência** | Escolher o universo de carteiras entre as que existem hoje, excluindo as que quebraram. Infla o resultado. |
| **Semana ao vivo** | Os primeiros 7 dias de cobertura efetiva da janela de avaliação da Rota B. Nela a cópia continua simulada; o que é real é o livro gravado. |
| **Gate do piloto** | Regra mecânica, computada uma única vez, que decide se o piloto com dinheiro real pode começar. |
| **Piloto** | Operação com dinheiro real, limitada a US$ 50, que copia a coorte da Rota B. Fora desta spec. |
| **Tipo de instrumento** | Classe de um fill: perpétuo do primeiro dex, perpétuo HIP-3 (nome com prefixo de dex, como `xyz:`), spot, token de resultado, ou outro. Só a primeira classe é copiada. |
| **Pool de candidatas** | Carteiras do snapshot do leaderboard que passam em F2. Em outubro de 2026 eram cerca de 18 mil. |
| **Universo** | Os ativos que o estudo copia. É formado por regra a cada seleção (RF-SEL-08), não por lista fixa. |

---

## 4. Requisitos funcionais

### 4.1 Verificação de dados (RF-VER)

Esta área roda **antes** do congelamento dos parâmetros de §7.2. Ela não escolhe nada com liberdade: cada medição tem uma regra de consequência escrita abaixo, e a consequência é sempre uma emenda desta spec.

É a única área implementada antes do gate de design, porque o design depende do que ela medir. Roda por scripts exploratórios em `scripts/verify/`, fora de `src/`, sem piso de cobertura. O relatório fica versionado em `docs/` e é entrada do design.

**RF-VER-01 — Esquema e retenção da API**
O que esta spec assume sobre a API foi lido em documentação. Precisa ser confirmado em dado real.

- **CA-01.1** — *Dado* uma amostra semeada de 20 carteiras do leaderboard, *quando* `verify` executa, *então* o relatório lista, para cada campo usado (`time`, `coin`, `px`, `sz`, `side`, `startPosition`, `dir`, `crossed`, `closedPnl`, `fee`, `tid`, `oid`), a fração de fills em que ele está presente e é interpretável. Fração menor que 100% em qualquer campo reprova a verificação.
- **CA-01.2** — *Dado* a mesma amostra, *quando* `verify` executa, *então* o relatório informa, por carteira, a data do fill mais antigo devolvido, se o teto de 10.000 fills foi atingido, e a fração da amostra cujo histórico alcança o início da janela de seleção.
- **CA-01.3** — *Dado* o leaderboard, *quando* `verify` executa, *então* o relatório informa o número de linhas, os campos presentes e o menor patrimônio listado.
- **CA-01.4** — *Dado* os episódios fechados da amostra, *quando* o PnL é reconstruído dos preços e tamanhos, *então* o relatório informa se `closedPnl` é bruto ou líquido de `fee`, testando as duas hipóteses.
- **CA-01.5** — *Dado* 10 minutos de gravação do fluxo público de negócios de um ativo, *quando* `verify` executa, *então* o relatório confirma se cada negócio traz os endereços das duas pontas. Se não trouxer, RF-COL-03 sai do escopo por emenda.

**RF-VER-02 — Cobertura do universo**

- **CA-02.1** — *Dado* uma amostra semeada de 100 carteiras que passam em F1 e F2, *quando* `verify` executa usando apenas fills da janela de seleção, *então* o relatório informa a fração do notional negociado em cada ativo e a fração acumulada no universo proposto.
- **CA-02.2** — *Dado* que a fração acumulada é menor que 50%, *quando* `verify` termina, *então* o relatório lista os ativos a acrescentar segundo a regra D7 e o status é "universo a emendar". O universo só muda por emenda desta spec, anterior ao congelamento.

**RF-VER-03 — Validade do preço proxy**

- **CA-03.1** — *Dado* ao menos 10.000 fills de líderes por ativo do universo na janela de seleção, *quando* cada um é comparado ao preço proxy do mesmo segundo, *então* o relatório informa mediana e p95 da diferença em bps, por ativo e por dia.
- **CA-03.2** — *Dado* um ativo em que o p95 do desvio absoluto em relação à mediana do dia excede 10 bps, *quando* `verify` termina, *então* o ativo é marcado "proxy inválido": sai da Rota A e permanece na Rota B.

**RF-VER-04 — Orçamento de dados**

- **CA-04.1** — *Dado* uma hora de gravação do coletor na configuração default, *quando* `verify` executa, *então* o relatório informa bytes gravados por ativo e a extrapolação para 45 dias.
- **CA-04.2** — *Dado* o download de um dia de preço proxy por ativo, *quando* `verify` executa, *então* o relatório informa o tamanho e a extrapolação para todas as janelas.
- **CA-04.3** — *Dado* que alguma extrapolação excede o orçamento de RNF-10, *quando* `verify` termina, *então* o status é "orçamento a emendar".

**RF-VER-05 — Verificação complementar**
Acrescentada na emenda 1.1, para fechar o que a primeira execução deixou em aberto. Valem as mesmas regras desta área.

- **CA-05.1** — *Dado* as quebras de continuidade encontradas, *quando* a verificação executa, *então* o relatório informa quantas coincidem com uma fronteira de página da coleta e, para uma amostra semeada de 10 quebras, se uma nova consulta de uma hora em torno de cada uma devolve algum fill que faltava. Se alguma quebra for explicada pela paginação, o defeito é nosso: corrige-se a coleta e a taxa de quebra é medida de novo.
- **CA-05.2** — *Dado* os episódios fechados das amostras, *quando* a diferença entre o PnL reconstruído e a soma dos `closedPnl` é dividida pelo notional negociado no episódio, *então* o relatório informa mediana, p95, p99 e máximo dessa razão, por número de fills, e a fração de episódios acima de 1 bp. Se essa fração passar de 5%, RF-ING-04 CA-04.2 volta para emenda.
- **CA-05.3** — *Dado* um ativo do universo e uma semana da janela de seleção, *quando* o histórico de funding é consultado, *então* o relatório informa o formato da resposta e se há uma taxa para cada hora cheia.
- **CA-05.4** — *Dado* as carteiras ativas da amostra de RF-VER-02, *quando* a verificação executa, *então* o relatório lista os 30 perpétuos do primeiro dex de maior notional na amostra, com número de fills e existência de equivalente na Binance, e informa quantas carteiras passariam em F9 com o universo de BTC, ETH e SOL e com o de todos os listados que têm equivalente. A medida é informativa.

**Resultado da verificação.** RF-VER-01 a RF-VER-04 rodaram em 2026-10-06, e o relatório está em `docs/verificacao-de-dados.md`. Dez pontos contradisseram esta spec ou os ADRs. Cada um foi resolvido na emenda 1.1, e o mapa está em §10. RF-VER-03 não pôde ser medida com a amostra disponível; a conferência do proxy passou para RF-ING-06 CA-06.3 e RF-COL-05. RF-VER-05 rodou no mesmo dia, com os quatro critérios satisfeitos: nenhuma quebra de continuidade é explicada pela paginação, e a causa continua sem identificação; 1,7% dos episódios divergem em mais de 1 bp do notional, com máximo de 3,3 bps; o funding tem um registro por hora; e F9 passa em 24 de 54 carteiras com os ativos que têm equivalente na Binance, contra 6 de 54 com BTC, ETH e SOL.

---

### 4.2 Ingestão (RF-ING)

**RF-ING-01 — Snapshot do leaderboard**

- **CA-01.1** — *Dado* que a ingestão do leaderboard executa, *quando* termina, *então* o snapshot é gravado com o instante da coleta e um hash, e snapshots anteriores não são sobrescritos.

**RF-ING-02 — Fills por carteira**

- **CA-02.1** — *Dado* uma carteira e uma janela, *quando* a ingestão executa, *então* a coleta pagina até esgotar a janela, com fills não agregados (`aggregateByTime` falso), início de página inclusivo e deduplicação, de modo que nenhum fill de um mesmo milissegundo se perca na fronteira entre páginas.
- **CA-02.2** — *Dado* que uma janela já foi ingerida, *quando* a ingestão executa de novo, *então* a contagem de fills permanece idêntica.
- **CA-02.3** — *Dado* uma carteira com mais de 20.000 fills na janela pedida, *quando* a coleta ultrapassa esse número, *então* ela para, e a carteira é marcada "frequência incompatível" e fica inelegível. Não existe teto de retenção por contagem: a integridade do histórico é conferida pela continuidade de posição (RF-ING-03).
- **CA-02.4** — *Dado* um fill, *quando* a ingestão o grava, *então* ele é classificado pelo tipo de instrumento (perpétuo do primeiro dex, HIP-3, spot, token de resultado ou outro). Fills fora do universo são gravados e marcados, não descartados. Os filtros F8 e F9 dependem deles.
- **CA-02.5** — *Dado* um fill de perpétuo do primeiro dex, *quando* a validação executa, *então* os 12 campos de RF-VER-01 CA-01.1 estão presentes e são interpretáveis; caso contrário a carteira fica inelegível e a falha é reportada. Nas demais classes exige-se só o necessário para o notional: fill sem preço ou tamanho interpretável conta com notional zero e é reportado.

**RF-ING-03 — Continuidade de posição**
A posição do líder é reconstruída dos fills. Um fill ausente corrompe tudo o que vem depois.

- **CA-03.1** — *Dado* dois fills consecutivos da mesma carteira no mesmo ativo, *quando* a validação executa, *então* o `startPosition` do segundo é igual ao `startPosition` do primeiro mais o `sz` com o sinal do lado, dentro da tolerância de um lote. Caso contrário, a carteira é marcada "quebra de continuidade" naquele ativo, com o instante.
- **CA-03.2** — *Dado* uma carteira com quebra de continuidade em ativo do universo dentro da janela de seleção, *quando* a seleção executa, *então* a carteira é inelegível e aparece no funil.
- **CA-03.3** — *Dado* uma quebra de continuidade de uma carteira da coorte dentro da janela de avaliação, *quando* a avaliação executa, *então* a carteira não é excluída: a quebra é tratada por RF-SIM-02 CA-02.8 e contada no relatório.
- **CA-03.4** — *Dado* as quebras encontradas numa ingestão, *quando* o relatório é emitido, *então* informa a distribuição delas por idade, que é o tempo entre a quebra e a coleta, e por presença de fill de TWAP na vizinhança. A medida é informativa e serve para investigar a causa.

**RF-ING-04 — Episódios e conferência de PnL**

- **CA-04.1** — *Dado* os fills de uma carteira em um ativo, *quando* os episódios são construídos, *então* cada episódio vai da posição zero até a volta a zero, e uma inversão de sinal encerra um episódio e abre outro no mesmo instante.
- **CA-04.2** — *Dado* um episódio aberto e fechado dentro da janela ingerida, *quando* o PnL é reconstruído dos preços e tamanhos por custo médio, *então* a diferença para a soma dos `closedPnl` dos fills do episódio, que é bruta de taxa, é de no máximo 10 bps do notional negociado no episódio. Diferença maior indica posição ou preço reconstruído errado: na janela de seleção ela torna a carteira inelegível, e é sempre reportada. Episódio que já estava aberto no início da janela não tem custo de entrada conhecido e fica fora da conferência.

**RF-ING-05 — Funding e metadados**

- **CA-05.1** — *Dado* um ativo e uma janela, *quando* a ingestão executa, *então* há uma taxa de funding para cada hora cheia da janela, com cada registro associado à hora por arredondamento para baixo do seu instante. Hora faltante é falha explícita.
- **CA-05.2** — *Dado* um ativo, *quando* a ingestão executa, *então* o tamanho de lote é gravado com o instante da coleta.

**RF-ING-06 — Preço proxy**

- **CA-06.1** — *Dado* um ativo e uma janela, *quando* a ingestão executa, *então* é produzida uma série por segundo com preço mínimo, máximo e último. Segundos sem negócio ficam ausentes, não preenchidos.
- **CA-06.2** — *Dado* um arquivo baixado, *quando* a ingestão o lê, *então* ele é conferido contra o checksum publicado. Checksum divergente é falha explícita.
- **CA-06.3** — *Dado* a ingestão concluída para as candidatas, *quando* cada fill dos ativos candidatos ao universo (RF-SEL-08) na janela de seleção é comparado ao preço proxy do mesmo segundo, *então* o relatório informa mediana e p95 da diferença em bps, por ativo e por dia. Ativo em que o p95 do desvio absoluto em relação à mediana do dia excede 10 bps, ou em que o módulo da mediana de algum dia excede 50 bps, é marcado "proxy inválido" e não entra no universo. A conferência roda antes da formação do universo.
- **CA-06.4** — *Dado* a mesma comparação, *quando* o relatório é emitido, *então* informa também a mediana diária da diferença e a variação dela entre dias, que é o deslocamento de nível entre as duas corretoras.

**RF-ING-07 — Limites da API e resiliência**

- **CA-07.1** — *Dado* qualquer sequência de requisições, *quando* a ingestão executa, *então* o peso acumulado por minuto nunca excede o limite configurado (default 1.000, abaixo do teto de 1.200 da corretora). Verificável com provedor falso.
- **CA-07.2** — *Dado* que a coleta de uma carteira falha, *quando* a ingestão de uma lista executa, *então* as demais são processadas e a falha é reportada ao final com código de saída diferente de zero.
- **CA-07.3** — *Dado* uma resposta de limite excedido, *quando* a ingestão a recebe, *então* ela espera e repete com recuo; esgotadas as tentativas, falha explicitamente.

**RF-ING-08 — Reprodutibilidade**

- **CA-08.1** — *Dado* qualquer resultado de seleção ou simulação, *quando* o relatório é gerado, *então* ele registra os instantes de ingestão e um hash determinístico dos dados consumidos.
- **CA-08.2** — *Dado* um fill já gravado e uma nova coleta que devolve valor diferente para ele, *quando* a ingestão executa, *então* a divergência é logada com valor anterior e novo, e o resultado muda de hash. Dentro de uma janela já congelada o dado gravado não é alterado: a divergência é logada, gravada à parte e contada no relatório da avaliação.

---

### 4.3 Coletor prospectivo (RF-COL)

**RF-COL-01 — Livro de ofertas**

- **CA-01.1** — *Dado* um ativo do universo, *quando* o coletor está rodando, *então* são gravados o canal de melhor compra e venda, a cada mudança, e o retrato do livro na assinatura rápida (5 níveis, a cada meio segundo, aproximadamente), os dois com o timestamp da corretora e o de recebimento local, em formato comprimido.

**RF-COL-02 — Lacunas**

- **CA-02.1** — *Dado* uma desconexão, *quando* o coletor a detecta, *então* ele reconecta sozinho e registra a lacuna, com início e fim, por ativo.
- **CA-02.2** — *Dado* mais de 10 segundos sem retrato do livro de um ativo e sem desconexão detectada, *quando* o coletor verifica, *então* o intervalo também é registrado como lacuna. A regra não se aplica ao fluxo de negócios, que fica em silêncio em mercado quieto.
- **CA-02.3** — *Dado* o coletor em execução, *quando* o comando de status é chamado, *então* ele mostra, por ativo, a fração do tempo sem lacuna desde o início.

**RF-COL-03 — Fluxo público de negócios**

- **CA-03.1** — *Dado* um ativo do universo, *quando* o coletor está rodando, *então* todo negócio é gravado com os endereços das duas pontas, lado agressor, preço, tamanho e os dois timestamps.
- **CA-03.2** — *Dado* os negócios gravados, *quando* o relatório é gerado, *então* ele informa mediana, p95 e p99 do atraso entre o timestamp da corretora e o de recebimento, ao lado da grade de Δ. A medida é informativa e não altera o critério.

**RF-COL-04 — Operação**

- **CA-04.1** — *Dado* que o processo é reiniciado, *quando* volta a gravar, *então* nenhum registro é duplicado nem corrompido.
- **CA-04.2** — *Dado* 45 dias de execução, *quando* o uso de disco é medido, *então* ele está dentro do orçamento de RNF-10.

**RF-COL-05 — Conferência do proxy contra o livro**

- **CA-05.1** — *Dado* um dia com livro gravado e preço proxy disponível, *quando* o relatório é gerado, *então* informa, por ativo, mediana e p95 da diferença em bps entre o ponto médio do livro e o preço proxy do mesmo segundo. A medida é informativa e entra na declaração de vieses.
- **CA-05.2** — *Dado* ao menos 3 dias de gravação de um ativo, *quando* o relatório é gerado, *então* informa a mediana, ponderada pelo tempo, do meio-spread em bps daquele ativo, medida nos 3 primeiros dias UTC completos em que a cobertura dele foi de ao menos 95%. Esse valor é gravado uma vez por ativo num arquivo de parâmetros de custo, antes da seleção que o usa, e nunca é alterado depois. Ele alimenta o slippage do cenário primário da Rota A (§7.2).

---

### 4.4 Seleção (RF-SEL)

**RF-SEL-01 — Isolamento temporal** ⭐
A seleção com corte T não pode depender de nada que aconteceu a partir de T.

- **CA-01.1** — *Dado* uma seleção com corte T, *quando* ela executa, *então* lê apenas fills, preços e funding com timestamp menor que T. Tentativa de leitura a partir de T levanta exceção.
- **CA-01.2** — *Dado* uma seleção concluída, *quando* qualquer fill, preço ou funding com timestamp ≥ T é alterado arbitrariamente e a seleção é refeita, *então* a coorte, as referências de exposição e o arquivo de congelamento são idênticos. **Este é um dos dois testes de aceitação da fase.**
- **CA-01.3** — *Dado* o snapshot do leaderboard, que na Rota A é posterior a T, *quando* a seleção o lê, *então* usa apenas a lista de endereços e o patrimônio. Leitura de PnL, ROI ou volume por janela do leaderboard levanta exceção. O vazamento que resta é o viés de sobrevivência, declarado em RF-ANA-06.
- **CA-01.4** — *Dado* os parâmetros de custo por ativo (RF-COL-05 CA-05.2), *quando* a seleção os usa, *então* eles vêm do arquivo de parâmetros gravado antes dela. São parâmetros, não dados da janela: o teste de CA-01.2 os mantém fixos.

**RF-SEL-02 — Filtros de elegibilidade**

- **CA-02.1** — *Dado* as carteiras candidatas, *quando* a seleção executa, *então* os filtros F1 a F10 de §7.3 são aplicados e o relatório mostra o funil na ordem de execução: quantas entraram e quantas cada filtro removeu. A ordem não altera o conjunto final. F1 roda por último, por ser o mais caro de consultar.
- **CA-02.2** — *Dado* a execução da seleção, *quando* um limiar é lido, *então* ele vem do arquivo de parâmetros pré-registrados e de nenhum outro lugar.
- **CA-02.3** — *Dado* uma carteira sintética construída para falhar em exatamente um filtro, *quando* a seleção executa, *então* ela é removida por aquele filtro e por nenhum outro. Um teste por filtro.

**RF-SEL-03 — Referência de exposição**

- **CA-03.1** — *Dado* os fills de um líder na janela de seleção, *quando* N\* é calculado, *então* ele é o percentil 95, ponderado pelo tempo, da exposição bruta em dólares no universo, considerando só o tempo em que o líder tem alguma posição aberta no universo, com cada posição medida ao preço do último fill daquele ativo (ADR-0007).
- **CA-03.2** — *Dado* um líder cujo N\* é zero ou indefinido, *quando* a seleção executa, *então* ele é inelegível.

**RF-SEL-04 — Ranking e coorte**

- **CA-04.1** — *Dado* as carteiras elegíveis, *quando* o ranking executa, *então* elas são ordenadas pelo Sharpe diário da própria cópia simulada na janela de seleção, no cenário primário.
- **CA-04.2** — *Dado* o ranking, *quando* a coorte é formada, *então* entram as K primeiras cujo retorno líquido simulado na janela de seleção é positivo. Empate é desfeito por endereço em ordem crescente.
- **CA-04.3** — *Dado* menos de K carteiras nessa condição, *quando* a coorte é formada, *então* ela fica menor. Com zero, o resultado é "sem coorte" e conta como critério não atingido.
- **CA-04.4** — *Dado* a grade de capital, em que K depende do capital (§7.2), *quando* as coortes são formadas, *então* a coorte de cada capital é o prefixo de tamanho K do mesmo ranking. Há um ranking só.

**RF-SEL-05 — Congelamento**

- **CA-05.1** — *Dado* uma seleção concluída, *quando* ela termina, *então* grava um arquivo de congelamento com rota, T, universo, coorte, N\* por líder, parâmetros, incluídos os de custo por ativo, hashes dos dados e versão do código.
- **CA-05.2** — *Dado* a simulação da janela de avaliação, *quando* não há arquivo de congelamento, ou os hashes ou parâmetros divergem dele, *então* ela se recusa a rodar.
- **CA-05.3** — *Dado* a Rota B, *quando* o congelamento é publicado no repositório remoto, *então* a janela de avaliação começa na primeira meia-noite UTC posterior à publicação. O instante de publicação é o do commit do congelamento, e a presença dele no remoto é conferida antes dessa meia-noite.
- **CA-05.4** — *Dado* uma rota sem arquivo de congelamento, *quando* se pede a ingestão de qualquer dado da janela de avaliação dela, fills ou dados de mercado, *então* o comando se recusa. O mesmo vale para a janela de seleção da Rota B enquanto a Rota A não estiver congelada, porque ela contém a avaliação da Rota A.

**RF-SEL-06 — Coortes de controle**

- **CA-06.1** — *Dado* as carteiras elegíveis, *quando* a seleção termina, *então* são sorteadas 1.000 coortes de K carteiras para cada K distinto da grade de capital, sem reposição dentro de cada coorte, com semente registrada no congelamento.
- **CA-06.2** — *Dado* a mesma semente e os mesmos dados, *quando* o sorteio é refeito, *então* as coortes são idênticas.
- **CA-06.3** — *Dado* que o número de coortes distintas possíveis é menor que 1.000, *quando* o sorteio executa, *então* todas as coortes possíveis são usadas, uma vez cada. Com K = 1, a distribuição de controle é a lista inteira de elegíveis.

**RF-SEL-07 — Pool de candidatas**

- **CA-07.1** — *Dado* o snapshot do leaderboard, *quando* a seleção começa, *então* as candidatas são uma amostra aleatória de 3.000 endereços entre os que passam em F2, sorteada com semente registrada, com os endereços ordenados antes do sorteio.
- **CA-07.2** — *Dado* menos de 20 carteiras elegíveis ao fim dos filtros, *quando* a seleção verifica, *então* a amostra cresce em blocos de 3.000, na mesma sequência do sorteio, até haver 20 elegíveis ou o pool acabar. Cada ampliação fica registrada no congelamento.
- **CA-07.3** — *Dado* a decisão de ampliar, *quando* ela é tomada, *então* depende só da contagem de elegíveis, que não usa desempenho.

**RF-SEL-08 — Universo por regra**
O universo não é uma lista fixa. É formado a cada seleção, por critérios de liquidez e de qualidade de preço. Nenhum critério usa desempenho.

- **CA-08.1** — *Dado* os fills das candidatas na janela de seleção, *quando* o universo é formado, *então* entram os perpétuos do primeiro dex que cumprem as cinco condições: (i) têm perpétuo equivalente na Binance com dados em todos os dias da janela; (ii) estão, entre os que cumprem (i), nos 20 de maior notional negociado pelas candidatas; (iii) têm pelo menos 2.000 fills de candidatas na janela; (iv) passam na conferência do proxy de RF-ING-06 CA-06.3; (v) têm meio-spread medido pelo coletor (RF-COL-05 CA-05.2). Nas contas de (ii) e (iii) entram só as candidatas cuja coleta foi completa: as marcadas "frequência incompatível" têm histórico truncado e ficam fora.
- **CA-08.2** — *Dado* a seleção, *quando* ela executa, *então* o universo é formado antes dos filtros que dependem dele e fica gravado no congelamento.
- **CA-08.3** — *Dado* o universo formado, *quando* o relatório é emitido, *então* informa, para cada ativo considerado, qual condição o deixou fora, e a cobertura do universo sobre o notional das candidatas, em todos os fills e só em perpétuos do primeiro dex.
- **CA-08.4** — *Dado* a Rota B, *quando* o congelamento é publicado, *então* a janela de avaliação só começa numa meia-noite UTC em que o coletor já esteja gravando todos os ativos do universo.
- **CA-08.5** — *Dado* qualquer rota, *quando* os dados de mercado são coletados, *então* BTC está sempre incluído, no coletor, no preço proxy e na medida de custo, mesmo que fique fora do universo. O benchmark depende dele.

---

### 4.5 Simulador (RF-SIM)

**RF-SIM-01 — Invariante anti-lookahead** ⭐
Uma ordem do seguidor executada no instante τ só pode depender de eventos do líder com instante ≤ τ − Δ. Ver ADR-0003 e ADR-0008.

- **CA-01.1** — *Dado* um evento do líder no instante t, *quando* a ordem correspondente do seguidor é executada, *então* o instante de execução é t + Δ, ou a primeira observação de preço existente a partir dele.
- **CA-01.2** — *Dado* uma simulação concluída e um corte c, *quando* (i) todo evento do líder com instante > c, (ii) todo preço posterior a c + Δ e à última observação consumida pelas execuções até c + Δ e (iii) todo funding posterior a esse mesmo instante são alterados arbitrariamente e a simulação é refeita, *então* o conjunto de ordens executadas até c + Δ é idêntico. **Este é um dos dois testes de aceitação da fase.**
- **CA-01.3** — *Dado* que o simulador está processando o instante τ, *quando* qualquer componente pede um evento do líder posterior a τ − Δ ou um preço posterior ao permitido para τ, *então* a leitura levanta exceção. O laço pode conhecer de antemão os instantes em que haverá evento ou observação, para saber quando acordar, mas nunca o conteúdo deles.
- **CA-01.4** — *Dado* um evento do líder cujo t + Δ cai depois do fim da janela, *quando* a simulação termina, *então* a ordem não é executada e é reportada como pendente, sem afetar a contabilidade.
- **CA-01.5** — *Dado* que não existe observação de preço em t + Δ, *quando* a ordem é executada, *então* usa a próxima observação existente, qualquer que seja a distância, e o atraso efetivo fica registrado na ordem. A ordem é processada nesse instante, com o patrimônio e os preços dele, e o que o seguidor sabe do líder são os eventos cujas ordens já foram processadas (ADR-0008). Nenhum preço é inventado.

**RF-SIM-02 — Espelhamento por exposição relativa**
Ver ADR-0002.

- **CA-02.1** — *Dado* que, após um evento, a posição do líder no ativo c tem notional n, *quando* o alvo é calculado, *então* o alvo do seguidor em c é `pico × (n / N*) × patrimônio do seguidor`, com o sinal da posição do líder.
- **CA-02.2** — *Dado* que a soma dos módulos dos alvos excede `teto × patrimônio`, *quando* o alvo é calculado, *então* todos os alvos são multiplicados pelo mesmo fator para caber no teto, e as reduções são executadas antes dos aumentos. Num evento em um ativo, os demais ativos daquele líder só recebem ordem se for uma redução exigida pelo teto, no mínimo necessário para voltar a ele, repartido em proporção ao que cada um excede do seu alvo.
- **CA-02.3** — *Dado* uma posição do líder que já estava aberta no início da janela, *quando* a simulação executa, *então* o alvo do seguidor naquele ativo é zero até a posição do líder voltar a zero. Só episódios abertos a partir de zero dentro da janela são copiados.
- **CA-02.4** — *Dado* a diferença entre alvo e posição atual, *quando* a ordem é formada, *então* o tamanho é arredondado para baixo ao lote. Ordem com notional abaixo do mínimo não é enviada, é contada como "abaixo do mínimo", e a diferença é reavaliada no próximo evento daquele líder naquele ativo.
- **CA-02.5** — *Dado* que o líder zera a posição em um ativo, *quando* o evento é processado, *então* o seguidor zera a sua integralmente, mesmo abaixo do mínimo.
- **CA-02.6** — *Dado* a variante só compras, *quando* um alvo é negativo, *então* ele é substituído por zero e todo o resto do cálculo é idêntico.
- **CA-02.7** — *Dado* que as ordens de um evento foram executadas, *quando* o estado é inspecionado, *então*: (i) nenhuma ordem que aumenta a exposição deixou a exposição bruta, aos preços de execução, acima de `teto × patrimônio`, já descontada a taxa da ordem; (ii) se a exposição estava acima do teto porque o preço andou entre eventos, as reduções exigidas pelo teto foram enviadas antes de qualquer aumento. Duas reduções ficam sem enviar: a que cai abaixo da ordem mínima (CA-02.4) e a de um ativo sem observação de preço naquele instante. O excesso que elas deixam é contado e, enquanto ele durar, (i) impede qualquer aumento. Deriva acima do teto entre eventos é permitida e reportada como alavancagem máxima observada.
- **CA-02.8** — *Dado* qualquer fill do líder, *quando* a posição dele é atualizada, *então* ela é a posição anterior declarada no fill mais o tamanho com sinal. Se essa posição anterior não for a que o simulador tinha, houve mudança não observada: ela é incorporada naquele instante, contada no relatório, e nunca retroage nem é interpolada.

**RF-SIM-03 — Preço de execução**
Ver ADR-0003.

- **CA-03.1** — *Dado* a Rota A, *quando* uma ordem é executada, *então* a compra sai ao preço máximo e a venda ao preço mínimo do segundo do proxy que contém o instante de execução, mais o slippage configurado, contra o seguidor.
- **CA-03.2** — *Dado* a Rota B, *quando* uma ordem é executada, *então* o melhor preço vem do canal de melhor compra e venda, usando, entre a última observação até o instante de execução e a primeira depois dele, a pior para o seguidor. A profundidade além do melhor nível vem do retrato rápido do livro mais recente.
- **CA-03.3** — *Dado* a Rota B e uma ordem maior que a profundidade gravada, *quando* ela é executada, *então* só a parte disponível é executada; o resto é contado como "profundidade excedida" e reavaliado no próximo evento daquele líder naquele ativo.
- **CA-03.4** — *Dado* a Rota B, *quando* a comparação de fontes de preço é pedida, *então* a mesma coorte e o mesmo cenário são simulados sobre o mesmo intervalo, uma vez com o livro gravado e uma vez com o preço proxy, e a diferença de retorno é reportada em pontos percentuais.

**RF-SIM-04 — Custos**

- **CA-04.1** — *Dado* uma taxa taker configurada em bps, *quando* uma ordem executa, *então* a taxa sobre o notional é debitada e registrada na ordem.
- **CA-04.2** — *Dado* taxa zero, ou slippage zero na Rota A, *quando* o relatório é emitido, *então* ele sinaliza que o cenário é irrealista.

**RF-SIM-05 — Funding**

- **CA-05.1** — *Dado* uma posição aberta em uma hora cheia, *quando* o funding é aplicado, *então* o pagamento é `tamanho com sinal × preço de marcação × taxa da hora`, debitado do seguidor quando positivo.
- **CA-05.2** — *Dado* nenhuma posição aberta na hora cheia, *quando* o funding é aplicado, *então* o pagamento é zero.
- **CA-05.3** — *Dado* uma posição constante por 10 horas com taxa e preço constantes, *quando* a simulação executa, *então* o funding total é igual à forma fechada, conferível no papel.

**RF-SIM-06 — Contabilidade**

- **CA-06.1** — *Dado* qualquer instante, *quando* o estado é inspecionado, *então* `patrimônio = saldo + PnL não realizado ao preço de marcação`.
- **CA-06.2** — *Dado* o fim da simulação, *quando* se soma PnL realizado, PnL não realizado, funding líquido e taxas, *então* o total concilia com `patrimônio final − patrimônio inicial` com tolerância relativa de 1e-9. **Teste de conciliação obrigatório.**
- **CA-06.3** — *Dado* uma posição aberta no fim da janela, *quando* a simulação termina, *então* ela é marcada pelo último preço e reportada separadamente do PnL realizado, sem liquidação forçada.
- **CA-06.4** — *Dado* que o patrimônio de uma subconta chega a zero ou menos em um instante de marcação, *quando* a simulação o detecta, *então* a subconta congela, o patrimônio é reportado no valor real, e as métricas que pressupõem patrimônio positivo saem como ausentes explícitas, nunca como `NaN`.

**RF-SIM-07 — Subcontas e carteira**

- **CA-07.1** — *Dado* uma coorte de K líderes e capital C, *quando* a simulação executa, *então* cada líder é copiado em uma subconta independente com capital C/K, sem compensação de posições entre subcontas. Se a coorte tem menos de K carteiras, cada subconta continua com C/K e o restante fica parado em caixa, dentro do patrimônio da carteira.
- **CA-07.2** — *Dado* as subcontas, *quando* o resultado da carteira é computado, *então* o patrimônio da carteira é a soma dos patrimônios das subcontas em cada instante.

**RF-SIM-08 — Grade de cenários**

- **CA-08.1** — *Dado* a grade de §7.2, *quando* a simulação executa, *então* todos os cenários são rodados e o relatório mostra a grade inteira, com o cenário primário identificado. Só o primário entra no veredito.

---

### 4.6 Analytics (RF-ANA)

**RF-ANA-01 — Métricas**
Por subconta e para a carteira: retorno líquido, Sharpe diário anualizado, drawdown máximo, número de episódios copiados, taxa de acerto por episódio, taxas pagas, funding líquido, giro e alavancagem máxima observada.

- **CA-01.1** — *Dado* a série de retornos diários (dia UTC), *quando* o Sharpe é computado, *então* usa `média / desvio-padrão amostral × √365`, com taxa livre de risco zero, declarada no relatório.
- **CA-01.2** — *Dado* desvio-padrão zero, *quando* o Sharpe é computado, *então* o resultado é indefinido e reportado como tal.
- **CA-01.3** — *Dado* a curva de patrimônio, *quando* o drawdown máximo é computado, *então* é a maior queda percentual em relação ao máximo corrente, com datas de pico, de fundo e de recuperação, ou indicação de não recuperado.
- **CA-01.4** — *Dado* uma avaliação concluída, *quando* o relatório é emitido, *então* o resultado líquido aparece também por ativo e em dois grupos: BTC, ETH e SOL de um lado, os demais ativos do universo do outro. A quebra é informativa e não entra no veredito.

**RF-ANA-02 — Benchmarks**

- **CA-02.1** — *Dado* uma avaliação concluída, *quando* o relatório é emitido, *então* mostra em paralelo o resultado de comprar e manter BTC perpétuo a 1x com o capital inteiro, no mesmo período, com o mesmo modelo de execução, taxa e funding.
- **CA-02.2** — *Dado* a mesma avaliação, *quando* o relatório é emitido, *então* mostra o resultado da mesma coorte com Δ = 0 na mesma fonte de preço, como referência do custo do atraso.
- **CA-02.3** — *Dado* as coortes de controle, *quando* o relatório é emitido, *então* informa em que percentil da distribuição das 1.000 coortes aleatórias o resultado da coorte selecionada cai.

**RF-ANA-03 — Decomposição do custo de copiar**

- **CA-03.1** — *Dado* uma avaliação concluída, *quando* o relatório é emitido, *então* mostra o retorno em seis degraus, cada um uma simulação completa que liga um fator a mais, nesta ordem: (1) cópia ideal, com Δ = 0 e sem custo nem restrição de tamanho; (2) mais atraso Δ; (3) mais slippage; (4) mais taxas; (5) mais funding; (6) mais lote, ordem mínima e teto, que é o cenário completo.
- **CA-03.2** — *Dado* os seis degraus, *quando* as diferenças entre degraus consecutivos são somadas, *então* o total é igual à diferença entre o primeiro e o último.

**RF-ANA-04 — Contadores de não cópia**

- **CA-04.1** — *Dado* uma avaliação, *quando* o relatório é emitido, *então* informa quantos eventos e quanto notional do líder deixaram de ser copiados, por motivo: abaixo do mínimo, teto atingido, profundidade excedida, fora do universo, posição anterior à janela e pendente no fim.

**RF-ANA-05 — Veredito**

- **CA-05.1** — *Dado* o cenário primário na janela de avaliação, *quando* o veredito é computado, *então* o critério é atingido se, e somente se, o retorno líquido da carteira é positivo **e** maior que o do benchmark de CA-02.1.
- **CA-05.2** — *Dado* um veredito da Rota A, *quando* o relatório é emitido, *então* ele é rotulado "triagem" e declara que, sozinho, não libera o piloto.
- **CA-05.3** — *Dado* que alguma subconta congelou (RF-SIM-06 CA-06.4) ou que não há coorte, *quando* o veredito é computado, *então* o critério não é atingido.
- **CA-05.4** — *Dado* a Rota B, *quando* o veredito de 30 dias é computado, *então* usa a coorte e os parâmetros do congelamento, qualquer que tenha sido o resultado do gate do piloto e exista ou não um piloto em andamento.

**RF-ANA-06 — Declaração de vieses**

- **CA-06.1** — *Dado* qualquer relatório, *quando* é emitido, *então* contém uma seção fixa declarando: viés de sobrevivência na lista de candidatos; preço proxy e slippage por premissa na Rota A; janela única de 30 dias e dependência do regime de mercado; ausência de correção para múltiplas hipóteses; ausência de impacto de mercado e do efeito de outros copiadores; exclusão de carteiras com histórico truncado; posições anteriores à janela não copiadas; referência de exposição congelada; atraso modelado como constante; funding aproximado pelo preço de marcação da fonte usada; taxa base sem descontos; custos fixos de entrada e saída de capital não modelados; coorte de uma única carteira no cenário primário; universo restrito a perpétuos do primeiro dex, com a cobertura medida; pool de candidatas amostrado.

**RF-ANA-07 — Tamanho de amostra**

- **CA-07.1** — *Dado* menos de 30 dias de retornos ou menos de 30 episódios copiados na carteira, *quando* o relatório é emitido, *então* ele avisa que a amostra é insuficiente para inferência. O aviso não altera o veredito.

**RF-ANA-08 — Gate do piloto**
Ver ADR-0005. O gate confere se a semana ao vivo é consistente com o que a Rota A supôs. Ele não é evidência de que a cópia rende.

- **CA-08.1** — *Dado* a Rota A concluída e a semana ao vivo completa, *quando* o gate é computado no cenário primário, *então* ele é atingido se, e somente se, valem as quatro condições: (i) a Rota A atingiu o critério de RF-ANA-05 CA-05.1; (ii) o retorno líquido da cópia simulada com o livro gravado, na semana ao vivo, é ≥ −10%; (iii) o módulo da diferença de RF-SIM-03 CA-03.4, na semana ao vivo, é ≤ 1 ponto percentual; (iv) há coorte e nenhuma subconta congelou.
- **CA-08.2** — *Dado* que a cobertura do livro de algum ativo na semana é menor que 95%, *quando* o gate é computado, *então* a semana se estende até completar 7 dias de cobertura, por no máximo 3 dias. Além disso, o gate é inconclusivo e conta como não atingido.
- **CA-08.3** — *Dado* um gate já computado, *quando* se tenta computá-lo de novo com outra janela, outro cenário ou outros limites, *então* o comando se recusa. O resultado fica gravado em arquivo versionado, com os hashes dos dados.
- **CA-08.4** — *Dado* o relatório do gate, *quando* é emitido, *então* declara que se trata de uma verificação de consistência, informa quantos episódios a semana teve, e repete o teto de capital real de §7.2.

---

### 4.7 CLI (RF-CLI)

**RF-CLI-01 — Comandos**

```
python scripts/verify/run.py        # verificação de dados (§4.1), fora do pacote
python -m copylab ingest leaderboard
python -m copylab ingest fills --route A --window selection
python -m copylab ingest market --route A --window selection
python -m copylab collect
python -m copylab collect status
python -m copylab collect compact
python -m copylab costs measure
python -m copylab select --route A
python -m copylab select --route B --cutoff 2026-10-20
python -m copylab window open --freeze preregistro/rota-b.json
python -m copylab evaluate --freeze preregistro/rota-a.json
python -m copylab gate --freeze preregistro/rota-b.json
```

A ingestão, de fills e de dados de mercado, é pedida por rota e por janela, e não por datas, para que o comando possa recusar a janela de avaliação antes do congelamento (RF-SEL-05 CA-05.4). O corte da Rota A vem do arquivo de parâmetros; o da Rota B é argumento, e a data acima é só exemplo.

- **CA-01.1** — *Quando* `evaluate` executa com sucesso, *então* o relatório é impresso e gravado em arquivo, com o veredito na primeira seção.
- **CA-01.2** — *Dado* que faltam dados para a janela pedida, *quando* qualquer comando executa, *então* falha com mensagem acionável e código de saída diferente de zero.

**RF-CLI-02 — Gráfico**

- **CA-02.1** — *Quando* o gráfico é gerado, *então* mostra a curva de patrimônio da carteira, do benchmark e da coorte com Δ = 0 no painel superior, e o drawdown no inferior.

---

## 5. Requisitos não funcionais

- **RNF-01 — Determinismo.** Mesmos dados e mesmos parâmetros produzem resultado idêntico. Toda aleatoriedade usa semente registrada.
- **RNF-02 — Cobertura de testes.** Mínimo de 85%, com cobertura de ramos, em seleção, simulador, analytics e no livro-razão do líder (posições e episódios).
- **RNF-03 — Fixtures de papel.** Testes de seleção, simulador e analytics rodam sobre séries construídas à mão, com o resultado esperado derivado no próprio teste. Dado real de mercado não entra nesses testes.
- **RNF-04 — Performance.** Uma carteira, um cenário, 92 dias: menos de 5 segundos. Filtros sobre 3.000 carteiras: menos de 10 minutos. Ranking de até 200 elegíveis no cenário primário: menos de 30 minutos. A ingestão é limitada pela API, não pelo código: cerca de 15 horas por bloco de 3.000 carteiras.
- **RNF-05 — Tipagem.** `mypy --strict` no CI.
- **RNF-06 — Ambiente.** Python 3.12+, `uv`. Nenhum serviço externo: os dados ficam em arquivos locais (ADR-0006). `make test` roda offline, sem rede.
- **RNF-07 — Tempo.** Todo timestamp é um inteiro de milissegundos UTC, do provedor ao relatório. A conversão para dia-calendário UTC acontece em um único módulo. Nenhum fuso local, nenhum `datetime` sem fuso.
- **RNF-08 — Dinheiro.** Ponto flutuante, com comparações de teste por tolerância explícita.
- **RNF-09 — Somente leitura.** Nenhuma chave privada, nenhuma assinatura e nenhum endpoint de ordem existem no código desta fase. Verificável por teste de arquitetura sobre os imports.
- **RNF-10 — Custo e disco.** Nenhum dado ou serviço pago. Disco local total da fase ≤ 30 GB, com a gravação do coletor comprimida e os arquivos brutos do proxy descartados depois de gerada a série por segundo.
- **RNF-11 — Limites da API.** Respeitar 1.200 de peso por minuto por IP e 10 usuários distintos em assinaturas de usuário por WebSocket. Consequência: K ≤ 10.

## 6. Premissas

1. O seguidor é sempre taker, paga a taxa base de perpétuos (4,5 bps) e não tem desconto de volume, staking ou indicação.
2. A ordem mínima é de US$ 10 de notional, exceto ao zerar integralmente uma posição.
3. Toda ordem do seguidor é a mercado, sem impacto de mercado além da profundidade gravada.
4. O atraso Δ é constante dentro de um cenário.
5. O seguidor não replica a alavancagem do líder. Replica o perfil relativo de exposição, mapeado para o teto de 1x (ADR-0002).
6. Cada subconta opera com margem própria. Não há transferência entre subcontas durante a janela.
7. A liquidação do seguidor é simplificada: a subconta congela quando o patrimônio chega a zero. Numa corretora real ela seria liquidada antes.
8. Na Rota A, o preço do perpétuo na Binance é aceito como aproximação do preço na Hyperliquid, dentro do limite medido em RF-VER-03.
9. Moeda única (USDC tratado como dólar). Sem imposto.
10. Capital do seguidor não recebe aportes nem saques durante a janela.
11. Todo capital desta fase é simulado. Nenhum dinheiro real é movimentado.
12. Custos fixos de pôr e tirar dinheiro da corretora (depósito mínimo, taxa de saque, conversão de reais) não entram no retorno simulado. Com capital pequeno eles pesam, e o relatório declara isso.
13. O coletor roda em uma máquina doméstica ligada sem interrupção. Quedas de energia e de internet viram lacunas, tratadas por RF-COL-02 e pela regra de cobertura de §7.2.
14. A API devolve histórico além dos 10.000 fills que a documentação cita, mas a profundidade real não foi medida. A integridade do histórico é conferida pela continuidade de posição.

## 7. Decisões e parâmetros

### 7.1 Decisões fechadas

| # | Questão | Decisão | Razão |
|---|---|---|---|
| D1 | Fonte do sinal | Fills de carteiras públicas da Hyperliquid | ADR-0001 |
| D2 | Instrumento e risco | Perpétuos, long e short, teto de 1x; variante só compras como controle | ADR-0002, com a referência de exposição do ADR-0007 |
| D3 | Execução do seguidor | Em t + Δ, ao pior preço observado | ADR-0003, com o caso sem preço do ADR-0008 |
| D4 | Protocolo de avaliação | Rota A como triagem; Rota B com a semana ao vivo aos 7 dias e o veredito do estudo aos 30 | ADR-0004 |
| D5 | Critério | Retorno líquido positivo e acima de comprar e manter BTC, no cenário primário | Combinado antes de qualquer dado ser lido |
| D6 | Repositório | Projeto novo, com as convenções do quantlab e sem reaproveitar código dele | Mercado e escala de tempo diferentes |
| D7 | Universo | Formado por regra a cada seleção (RF-SEL-08): até 20 perpétuos do primeiro dex, com equivalente na Binance, volume mínimo e proxy aprovado. Substitui a lista BTC, ETH e SOL | A verificação mostrou que os três cobrem 41,3% do notional de perpétuos e 16,6% do total, e que poucas carteiras se concentram neles. Uma lista fixa, de 3 ou de 8, seria escolha de autor; a regra deixa os dados decidirem quais ativos têm preço confiável. Perpétuos HIP-3, 54,7% do notional da amostra, continuam fora por não terem preço equivalente |
| D8 | Posições anteriores à janela | Não são copiadas | Evita entrar em posição antiga a preço que o líder não pagou; dá episódios limpos como unidade de análise |
| D9 | Um resultado por rota | A Rota A não pode alterar a regra da Rota B depois de vista | Sem isso, a Rota B deixaria de ser pré-registrada |
| D10 | Onde o coletor roda | Na máquina secundária do Pedro, ligada sem interrupção | Os servidores gratuitos avaliados exigem cartão de crédito no cadastro. O da Oracle, o mais generoso, recolhe instâncias ociosas e reduziu o plano em 2026 sem aviso; o do Google só existe em regiões dos EUA, país restrito pela Hyperliquid. A máquina própria não depende de terceiros, e a latência medida nela é a do lugar onde um bot rodaria |
| D11 | Capital do cenário primário | US$ 50, o capital real pretendido para o piloto | O mínimo de US$ 10 por ordem torna o resultado muito dependente do capital. Simular com um valor que não será usado mediria outra coisa |
| D12 | O que libera o piloto | Rota A atinge o critério e a semana ao vivo não a contradiz (RF-ANA-08) | ADR-0005 |
| D13 | Capital real máximo | US$ 50, sem aportes. Qualquer valor acima exige ADR novo e o veredito de 30 dias | Limite fixado por quem arrisca o dinheiro, antes de qualquer resultado |
| D14 | Número de carteiras na coorte | `min(5, ⌊capital / 50⌋)`, mínimo 1 | Cada subconta precisa valer várias vezes a ordem mínima, ou quase nada é copiado |
| D15 | Limiares dos filtros F1 a F10 | Os da tabela de §7.3 | Valores de simulação delegados na aprovação. Ficam congelados antes de qualquer dado ser lido |
| D16 | Nome do projeto e do pacote | `copylab` | Segue o padrão do quantlab |
| D17 | Pool de candidatas | Amostra semeada de 3.000 carteiras do pool F2, ampliável em blocos de 3.000 (RF-SEL-07) | O pool tem cerca de 18 mil carteiras, e ingerir todas levaria dias no limite da API. Uma amostra aleatória não introduz viés. Custa cerca de 15 horas de coleta por rota |
| D18 | Granularidade dos fills | Não agregados (`aggregateByTime` falso) | Continuidade, episódios e a marcação de taker por fill foram medidos assim. A agregação muda a contagem em 35% |
| D19 | Canais do coletor | Melhor compra e venda a cada mudança, mais o livro na assinatura rápida | O livro default chega a cada 5,4 s, não a cada 0,5 s. Para ordens de dezenas de dólares, o melhor nível basta |
| D20 | Tolerância de conciliação de PnL | 10 bps do notional do episódio | A divergência medida tem mediana de 0,002 bps e máximo de 3,3 bps, o que é arredondamento. Um erro real de posição ou de preço produz diferença muito maior. O limite de 1 bp da emenda 1.1 tornaria inelegíveis 7 de 39 carteiras por arredondamento. O valor foi fixado depois de ver essa distribuição, que não contém dado de desempenho |
| D21 | Slippage da Rota A por ativo | O maior entre 2 bps e a mediana do meio-spread medido pelo coletor | Com ativos menos líquidos no universo, um valor único favoreceria justamente os mais caros de copiar |

### 7.2 Parâmetros pré-registrados

Valores aprovados com esta spec, exceto onde a coluna indica outra coisa. Depois de congelados, só mudam por emenda com versão nova, e nunca depois de uma janela de avaliação ter sido lida.

| Parâmetro | Valor | Congela em |
|---|---|---|
| Universo | Por regra, a cada seleção (RF-SEL-08): no máximo 20 ativos, mínimo de 2.000 fills de candidatas por ativo, desvio do proxy de até 10 bps e nível de até 50 bps | Aprovação da emenda 1.1 |
| Rota A — janela de seleção | 2026-07-01 a 2026-08-31 (UTC), 62 dias | Aprovação |
| Rota A — corte T | 2026-09-01 00:00 UTC | Aprovação |
| Rota A — janela de avaliação | 2026-09-01 a 2026-09-30 (UTC), 30 dias | Aprovação |
| Rota B — janela de seleção | Os 62 dias que terminam no corte da Rota B, uma meia-noite UTC anterior ao congelamento | Aprovação |
| Rota B — janela de avaliação | 30 dias a partir da primeira meia-noite UTC após a publicação do congelamento | Aprovação |
| Rota B — cobertura mínima do livro | 95% do tempo por ativo. Abaixo disso, a janela se estende até completar 30 dias de cobertura, no máximo por 15 dias; além disso, a rota é inconclusiva | Aprovação |
| Semana ao vivo | Os primeiros 7 dias de cobertura efetiva da janela de avaliação da Rota B, com extensão máxima de 3 dias | Aprovação |
| Gate do piloto — perda máxima na semana | 10% (retorno simulado com o livro ≥ −10%) | Aprovação |
| Gate do piloto — diferença entre fontes de preço | 1 ponto percentual, em módulo | Aprovação |
| Capital real máximo do piloto | US$ 50 | Aprovação |
| Pool de candidatas | 3.000 carteiras do pool F2, sorteadas com a semente 20261005, em blocos adicionais de 3.000 enquanto houver menos de 20 elegíveis | Aprovação da emenda 1.1 |
| Teto de fills por carteira na janela | 20.000 | Aprovação da emenda 1.1 |
| Tolerância de conciliação de PnL | 10 bps do notional do episódio | Aprovação da versão 1.2 |
| K (carteiras na coorte) | `min(5, ⌊capital / 50⌋)`, com mínimo de 1. Cada subconta tem pelo menos US$ 50, cinco vezes a ordem mínima | Aprovação |
| Capital (simulado) | Primário US$ 50, com K = 1. Grade: 50 / 100 / 500, com K = 1 / 2 / 5 | Aprovação |
| Δ | Primário 5 s; grade 1 / 5 / 30 s | Aprovação |
| Grade de cenários | Os nove pares de capital e Δ, com o slippage primário. A sensibilidade de slippage roda só no capital e no Δ primários. A variante só compras roda em todos | Aprovação da versão 1.3 |
| Slippage (Rota A) | Primário, por ativo: o maior entre 2 bps e a mediana do meio-spread medido pelo coletor em ao menos 3 dias, medido uma vez por ativo e congelado antes da seleção que o usa. Sensibilidade: zero e o dobro do primário | Aprovação da emenda 1.1 |
| Taxa taker | 4,5 bps | Aprovação |
| Teto de alavancagem | 1,0 | Aprovação |
| Exposição no pico | 1,0 | Aprovação |
| Ordem mínima | US$ 10 | Aprovação |
| Ranking | Sharpe diário da cópia simulada na janela de seleção | Aprovação |
| Coortes de controle | 1.000, semente 20261005 | Aprovação |
| Anualização | √365, dia UTC | Aprovação |

### 7.3 Filtros de elegibilidade

Todos calculados só com dados da janela de seleção, exceto F1 e F2, que vêm do snapshot do leaderboard. Limiares aprovados por delegação (D15).

| # | Filtro | Limiar | Por quê |
|---|---|---|---|
| F1 | Tipo de conta | Usuário comum (exclui vault e subconta). Aplicado por último | Vault tem regras próprias de saque e comissão |
| F2 | Patrimônio no snapshot | ≥ US$ 30.000 | Conta pequena some ou saca tudo; é o piso que a documentação da HyperDash recomenda |
| F3 | Histórico íntegro | Dentro da janela de seleção: sem quebra de continuidade no universo, sem falha de campo em fill de perpétuo, PnL conciliado e no máximo 20.000 fills | Sem isso a posição reconstruída está errada |
| F4 | Episódios fechados no universo | ≥ 20 | Amostra mínima por carteira |
| F5 | Regularidade | Abre episódio em ≥ 6 dos 8 blocos completos de 7 dias | Exclui quem acertou uma semana |
| F6 | Duração mediana do episódio | Entre 1 hora e 7 dias | Abaixo de 1 hora, o atraso de segundos pesa demais; acima de 7 dias, sobram poucos episódios em 30 dias |
| F7 | Entradas a mercado | ≥ 50% do notional de abertura com `crossed = true` | Quem entra em repouso recebe o spread que o seguidor paga |
| F8 | Concentração | Mediana de até 3 perpétuos abertos ao mesmo tempo, medida sobre o tempo em posição, contando também os HIP-3 e os de fora do universo | Muitas posições simultâneas indicam market maker ou arbitragem de funding |
| F9 | Cobertura do universo | ≥ 50% do notional da carteira em ativos do universo | Abaixo disso copia-se a menor parte da estratégia |
| F10 | Liquidações | Nenhum fill em que a carteira é a liquidada. Auto-deleveraging não conta | Sinal de risco que o teto de 1x não elimina por completo |

## 8. Questões em aberto

Nenhuma. Q1 a Q5 foram fechadas como D10 a D16. Q6 (universo) e Q7 (pool de candidatas), abertas na emenda 1.1, foram fechadas como D7 e D17.

## 9. Definition of Done

**Parte 1A — triagem (Rota A):**

- [ ] Verificação de dados executada, relatório versionado em `docs/`, e toda emenda que ela exigir aplicada antes do congelamento
- [ ] O teste de RF-SIM-01 CA-01.2 (mutação do futuro no simulador) passa
- [ ] O teste de RF-SEL-01 CA-01.2 (mutação da janela de avaliação na seleção) passa
- [ ] O teste de conciliação de RF-SIM-06 CA-06.2 passa
- [ ] O teste de arquitetura de RNF-09 (somente leitura) passa
- [ ] Cobertura ≥ 85% em seleção, simulador, analytics e livro-razão do líder
- [ ] CI verde: testes, `mypy --strict`, lint
- [ ] ADRs 0001 a 0008 aceitos
- [ ] Verificação complementar (RF-VER-05) executada, com o relatório atualizado
- [ ] Congelamento da Rota A commitado antes de qualquer leitura da janela de avaliação
- [ ] Relatório da Rota A com veredito, grade inteira, decomposição, controle só compras e seção de vieses
- [ ] O coletor está rodando e o comando de status mostra cobertura

**Parte 1B — semana ao vivo e gate do piloto:**

- [ ] Congelamento da Rota B publicado no remoto antes do início da janela
- [ ] 7 dias de cobertura efetiva do livro, pela regra de RF-ANA-08 CA-08.2
- [ ] Gate do piloto computado uma única vez, com resultado e hashes versionados
- [ ] Relatório do gate com as quatro condições, uma a uma

**Parte 1C — veredito do estudo (Rota B, 30 dias):**

- [ ] 30 dias de cobertura efetiva do livro, pela regra de §7.2
- [ ] Relatório da Rota B com veredito, computado pelas regras do congelamento
- [ ] README com arquitetura, instruções de execução e limitações conhecidas
- [ ] O resultado reportado como saiu, inclusive se a cópia perder para comprar e manter

## 10. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 1.3 | 2026-10-07 | **Aprovada em 2026-10-07.** Resposta à leitura cruzada do design. Guarda de ingestão vira critério e passa a valer também para dados de mercado (RF-SEL-05 CA-05.4, RF-CLI-01). Segunda exceção do teto: ativo sem preço no instante (RF-SIM-02 CA-02.7). Redução pelo teto mínima e proporcional (RF-SIM-02 CA-02.2). Instantes futuros permitidos ao laço, conteúdos não (RF-SIM-01 CA-01.3). Custo medido uma vez por ativo, e BTC sempre medido (RF-COL-05 CA-05.2, RF-SEL-08 CA-08.5, §7.2). Publicação da Rota B pelo instante do commit (RF-SEL-05 CA-05.3). Janela de seleção da Rota B termina no corte (§7.2). Composição da grade (§7.2). Default do limite de peso em 1.000 (RF-ING-07 CA-07.1). Acertos de redação no glossário e em RF-SIM-03 CA-03.3 |
| 1.2 | 2026-10-06 | **Proposta, substituída pela 1.3.** Fecha a emenda 1.1 com o resultado de RF-VER-05 e com o que o design encontrou. Tolerância de PnL de 1 para 10 bps (RF-ING-04 CA-04.2, D20). Condição de nível no proxy (RF-ING-06 CA-06.3). Funding associado à hora por arredondamento (RF-ING-05 CA-05.1). N\* só sobre o tempo em posição, porque sobre o tempo total um líder que fica pouco tempo posicionado teria referência zero (RF-SEL-03 CA-03.1, ADR-0007). Parâmetros de custo congelados antes da seleção (RF-SEL-01 CA-01.4, RF-SEL-05 CA-05.1, RF-SEL-08 CA-08.1 e CA-08.5, RF-COL-05 CA-05.2). Ordens em outros ativos só para reduzir (RF-SIM-02 CA-02.2 e CA-02.4). Diagnóstico das quebras (RF-ING-03 CA-03.4). Livro-razão do líder na cobertura (RNF-02). Sem serviço de banco (RNF-06, ADR-0006). Precisões que o design exigiu: evento do líder como o conjunto de fills do mesmo milissegundo (glossário); teto conferido nas ordens que aumentam exposição, com a exceção da ordem mínima (RF-SIM-02 CA-02.7); execução atrasada processada no instante efetivo e teste de mutação enunciado pelo relógio da execução (RF-SIM-01 CA-01.2 e CA-01.5, ADR-0008); universo contado sobre candidatas com coleta completa (RF-SEL-08 CA-08.1); dado congelado não reescrito (RF-ING-08 CA-08.2); conferência de PnL só em episódios abertos e fechados na janela (RF-ING-04 CA-04.2); meio-spread ponderado pelo tempo (RF-COL-05 CA-05.2); F8 sobre perpétuos; desvio-padrão amostral (RF-ANA-01 CA-01.1); capital parado quando a coorte é menor que K (RF-SIM-07 CA-07.1); semente do pool (§7.2); comandos da CLI (RF-CLI-01) |
| 1.1 | 2026-10-06 | **Emenda proposta**, resultado da verificação de dados. (1) Sem teto de 10.000 fills: RF-ING-02 CA-02.1 e CA-02.3, F3, premissa 14. (2) Tolerância de PnL: RF-ING-04 CA-04.2, D20. (3) Quebras de continuidade: RF-ING-03 CA-03.2 e CA-03.3, RF-SIM-02 CA-02.8, RF-VER-05 CA-05.1. (4) Universo por regra, no lugar da lista fixa: RF-SEL-08, D7, D21, RF-COL-05 CA-05.2, RF-ANA-01 CA-01.4. (5) Pool de candidatas: RF-SEL-07, D17, RF-SEL-02 CA-02.1. (6) Cadência do livro: RF-COL-01 CA-01.1, RF-SIM-03 CA-03.2, D19. (7) Regra de lacuna: RF-COL-02 CA-02.2. (8) Classes de fill: RF-ING-02 CA-02.4 e CA-02.5, F10. (9) Agregação: D18. (10) Proxy: RF-ING-06 CA-06.3 e CA-06.4, RF-COL-05. Acrescentada RF-VER-05. Q6 e Q7 abertas e fechadas na mesma emenda |
| 1.0 | 2026-10-05 | **Aprovada.** Estrutura em três marcos: Rota A, semana ao vivo com gate do piloto (RF-ANA-08, ADR-0005) e veredito de 30 dias. Capital primário de US$ 50 (D11), teto real de US$ 50 (D13). Q1 a Q4 fechadas como D11 a D16. Verificação de dados declarada como única área anterior ao design (§4.1). Acrescentados RF-SEL-06 CA-06.3, RF-SIM-03 CA-03.4 e RF-ANA-05 CA-05.4 |
| 0.2 | 2026-10-05 | Esclarecido que todo capital é simulado e que o primário espelha o capital real pretendido (D11, premissas 11 e 12). K passa a depender do capital (§7.2, RF-SEL-04 CA-04.4, RF-SEL-06). Q5 fechada como D10: coletor na máquina secundária (premissa 13). Custos fixos de entrada e saída entram na declaração de vieses |
| 0.1 | 2026-10-05 | Rascunho inicial, com Q1 a Q5 em aberto |
