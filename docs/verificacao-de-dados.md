# Verificação de dados (§4.1)

> Gerado por `scripts/verify/report.py` a partir de `data/verify/results/`. Mede e reporta; não decide nada e não altera nenhuma spec.

## Execução

| Item | Valor |
|---|---|
| Início da primeira execução | 2026-10-06T04:30:50Z |
| Fim da última execução | 2026-10-06T05:35:52Z |
| Relatório gerado em | 2026-10-06T05:35:52Z |
| Semente de toda amostragem | `20261005` |
| Versão do código | `b5bb55b` |
| Modo | completo |
| Janela de seleção (conteúdo dos fills) | 2026-07-01T00:00:00Z a 2026-09-01T00:00:00Z (exclusivo) |
| Snapshot do leaderboard | 2026-10-06T04:30:56Z; 47,430 linhas; 37.6 MB; sha256 `0914dc83ef331fff…` |

**Uso da API de informação** (orçamento de peso da verificação: 1000/min; teto documentado: 1200/min)

| Etapa | Requisições | Peso gasto | HTTP 429 | Retentativas | Pico em 60 s | Espera por orçamento |
|---|---|---|---|---|---|---|
| v01 | 168 | 9383 | 0 | 0 | 999 | 7.5 min |
| v02 | 885 | 52415 | 0 | 0 | 1000 | 42.1 min |

O pico é o maior peso acumulado numa janela deslizante de 60 s, contado com a reserva pessimista (120 por página de fills) antes de a resposta chegar. Valores da execução de coleta de 2026-10-06 (04:30 a 05:30 UTC), lidos do primeiro relatório gerado; a reanálise offline posterior não faz requisições.

## Resumo dos 12 critérios

| Critério | Status | Medido |
|---|---|---|
| `RF-VER-01 CA-01.1` | **reprova** | 13,907 fills; pior campo 99.97% presente e interpretável |
| `RF-VER-01 CA-01.2` | **ok** | 20 carteiras; mais de 10.000 fills devolvidos em 7; exatamente 10.000 em 0; histórico começa antes da janela em 85.0% |
| `RF-VER-01 CA-01.3` | **ok** | 47,430 linhas; menor patrimônio US$ 0.00 |
| `RF-VER-01 CA-01.4` | **ok** | closedPnl concilia com a hipótese gross; gross 93.2%, net_all 0.0%, net_close 0.0% (tolerância 0.001; 118 episódios em que a taxa importa); na tolerância da spec (1e-6), gross concilia 40.7% |
| `RF-VER-01 CA-01.5` | **ok** | 799 de 799 negócios com as duas pontas |
| `RF-VER-02 CA-02.1` | **ok** | universo = 16.6% (todos os fills) / 41.3% (só perpétuos) |
| `RF-VER-02 CA-02.2` | **a emendar** | acumulado 16.6% (todos) / 41.3% (perpétuos) |
| `RF-VER-03 CA-03.1` | **reprova** | fills por ativo: BTC 86, ETH 75, SOL 20 |
| `RF-VER-03 CA-03.2` | **não medido** | BTC: ok (n=86), ETH: ok (n=75), SOL: ok (n=20) |
| `RF-VER-04 CA-04.1` | **ok** | 60 min; 45 dias = 13.11 GB bruto / 1.70 GB gzip |
| `RF-VER-04 CA-04.2` | **ok** | proxy, 154 dias: 2.82 GB em zips |
| `RF-VER-04 CA-04.3` | **ok** | orçamento 30 GB; maior extrapolação individual 19.43 GB |

## RF-VER-01 — esquema e retenção da API

| Critério | Regra da spec | Medido | Status |
|---|---|---|---|
| `CA-01.1` | cada campo presente e interpretável em 100% dos fills | 13,907 fills; pior campo 99.97% presente e interpretável | **reprova** |
| `CA-01.2` | informar, por carteira, o fill mais antigo, se o teto de 10.000 foi atingido e a fração que alcança o início da janela | 20 carteiras; mais de 10.000 fills devolvidos em 7; exatamente 10.000 em 0; histórico começa antes da janela em 85.0% | **ok** |
| `CA-01.3` | informar linhas, campos presentes e o menor patrimônio listado | 47,430 linhas; menor patrimônio US$ 0.00 | **ok** |
| `CA-01.4` | informar se closedPnl é bruto ou líquido de fee, testando as duas hipóteses | closedPnl concilia com a hipótese gross; gross 93.2%, net_all 0.0%, net_close 0.0% (tolerância 0.001; 118 episódios em que a taxa importa); na tolerância da spec (1e-6), gross concilia 40.7% | **ok** |
| `CA-01.5` | cada negócio traz os endereços das duas pontas; se não trouxer, RF-COL-03 sai do escopo por emenda | 799 de 799 negócios com as duas pontas | **ok** |

Amostra: 20 carteiras sorteadas do leaderboard inteiro (endereços ordenados antes do sorteio, semente `20261005`); falhas de coleta: 0.

### CA-01.1 — campos por fill

| Campo | Presente | Presente e interpretável |
|---|---|---|
| `time` | 100.00% | 100.00% |
| `coin` | 100.00% | 100.00% |
| `px` | 100.00% | 99.99% |
| `sz` | 100.00% | 100.00% |
| `side` | 100.00% | 100.00% |
| `startPosition` | 100.00% | 100.00% |
| `dir` | 100.00% | 100.00% |
| `crossed` | 100.00% | 100.00% |
| `closedPnl` | 100.00% | 100.00% |
| `fee` | 100.00% | 100.00% |
| `tid` | 100.00% | 99.97% |
| `oid` | 100.00% | 100.00% |

Fills analisados: 13,907. Campos que reprovam: ['px', 'tid'].

Pior campo por tipo de ativo:

| Tipo | Fills | Pior campo (interpretável) |
|---|---|---|
| perp | 2,096 | 100.00% |
| hip3 | 11,554 | 100.00% |
| spot | 254 | 98.43% |
| outcome | 3 | 66.67% |

Campos presentes nos fills além dos 12 da spec: {'hash': 13907, 'feeToken': 13907, 'twapId': 13907, 'liquidation': 66, 'builderFee': 3, 'cloid': 3}.

Valores de `dir` observados: {'Open Long': 5404, 'Close Long': 5228, 'Open Short': 1303, 'Close Short': 1518, 'Long > Short': 107, 'Sell': 143, 'Short > Long': 90, 'Buy': 109, 'Spot Dust Conversion': 4, 'Settlement': 1}.

### CA-01.2 — retenção por carteira

| Carteira | Fills na janela | Antes da janela (contagem) | Depois do corte (só contagem) | Total devolvido | Mais antigo | O histórico começa | Passou de 10.000 |
|---|---|---|---|---|---|---|---|
| `0x6118bc9c2fe6c10261d199c52a5d9b657a7e84ca` | 4 | 1455 | 0 | 1,459 | 2025-03-19T15:00:22Z | antes da janela | não |
| `0xbfba167ecc3d9e13a8401d8a7ca288240a952f33` | 10841 | 0 | 2000 | >12,841 | 2026-07-14T03:55:22Z | dentro da janela | sim |
| `0x67f4259074b626749691c0f31e3a78a9ceab405b` | 765 | 7994 | 2225 | >10,984 | 2025-06-07T15:30:49Z | antes da janela | sim |
| `0x8c294aeb643f8099f3d15fb47e437edd72df4022` | 313 | 9985 | 579 | >10,877 | 2025-11-23T05:56:06Z | antes da janela | sim |
| `0x3609a72d39d526f7885f2a8ec5728be923032b3a` | 2 | 461 | 0 | 463 | 2025-01-06T15:25:02Z | antes da janela | não |
| `0x20b5e2391abe9ef5ff75d160109da395f443e953` | 0 | 2149 | 0 | 2,149 | 2024-11-29T13:17:55Z | antes da janela | não |
| `0xc27df0a5459a75ab4fe623b0c2a2021791266f55` | 136 | 1048 | 356 | 1,540 | 2024-12-12T21:35:50Z | antes da janela | não |
| `0xb75055233b067dd97bae6babd28e6a095c3d97ae` | 0 | 0 | 0 | 0 | — | sem fills | não |
| `0x07313ac0106cce8ace35caba54e4b11dab2ae42d` | 0 | 24 | 13 | 37 | 2025-06-11T15:32:29Z | antes da janela | não |
| `0x1f75442e5d0856193986560934e1e6eb5faaf3c5` | 58 | 1901 | 41 | 2,000 | 2024-04-17T11:19:52Z | antes da janela | não |
| `0x26d957cf59e34a37080691c5024e307393eb69b3` | 2 | 7635 | 29 | 7,666 | 2025-01-14T22:21:35Z | antes da janela | não |
| `0xfd993896bb8bf7d01eb3b00b57210ae584c85750` | 0 | 5075 | 0 | 5,075 | 2023-12-23T01:32:35Z | antes da janela | não |
| `0x64d8fdf7346337953c434824a84072dc53fcccd8` | 18 | 1816 | 43 | 1,877 | 2023-11-30T06:14:17Z | antes da janela | não |
| `0xbc476160765ff70cbd78d5a63aaa885555d575f1` | 0 | 11806 | 0 | >11,806 | 2025-06-05T10:49:05Z | antes da janela | sim |
| `0x63d6cbd12a2984c211ff623074e9362e4520e902` | 965 | 7917 | 1511 | >10,393 | 2025-07-22T02:22:53Z | antes da janela | sim |
| `0x9af02b863f5d404841a1166ca4dd9b810512e40f` | 0 | 11989 | 0 | >11,989 | 2025-05-20T20:53:58Z | antes da janela | sim |
| `0xe1dc587acfc93f1ef87d3b17e33af9aebfc6b972` | 36 | 4189 | 0 | 4,225 | 2025-10-13T12:28:57Z | antes da janela | não |
| `0x90d97d27cf9437694cb554fe69468a0f3e20459f` | 0 | 2976 | 0 | 2,976 | 2024-11-19T05:08:28Z | antes da janela | não |
| `0xce700c52f85779c8f2e6b8908dca62963889da0b` | 0 | 0 | 92 | 92 | — | depois da janela | não |
| `0xf9d5aa669b007610c14b58073e54f1aa93adea26` | 767 | 5977 | 4389 | >11,133 | 2026-01-26T21:51:43Z | antes da janela | sim |

Histórico por categoria: {'antes da janela': 17, 'dentro da janela': 1, 'sem fills': 1, 'depois da janela': 1}. Maior total contado: 12,841. Contagens com `>` pararam cedo, ao provar que a carteira passa de 10.000 fills (a paginação não prosseguiu). Nenhum fill de antes da janela ou do corte teve o conteúdo guardado: só contagem e o instante do mais antigo.

Fills que compartilham `tid` com outro fill da mesma carteira: 1.

### CA-01.3 — leaderboard

| Medida | Valor |
|---|---|
| Linhas | 47,430 |
| Campos por linha (contagem de linhas que o trazem) | {'ethAddress': 47430, 'accountValue': 47430, 'windowPerformances': 47430, 'prize': 47430, 'displayName': 47430} |
| Menor patrimônio listado (US$) | 0.00 |
| Linhas com patrimônio ≥ US$ 30.000 (F2) | 18,369 |
| `windowPerformances` presente em | 47,430 linhas |
| Janelas em `windowPerformances` (só nomes) | {'day': 47430, 'week': 47430, 'month': 47430, 'allTime': 47430} |
| Campos por janela (só nomes; valores não foram guardados) | {'pnl': 189720, 'roi': 189720, 'vlm': 189720} |
| Endereços inválidos / duplicados | 0 / 0 |

### CA-01.4 — `closedPnl` bruto ou líquido

Só contagens de episódios; nenhum valor de PnL é impresso ou gravado. Tolerância relativa 1e-6 (com piso absoluto de 1e-6 USD, escolha deste script). Hipóteses sobre a soma de `closedPnl` do episódio: `gross` = igual ao PnL reconstruído de preços e tamanhos por custo médio; `net_all` = reconstruído menos todas as taxas do episódio; `net_close` = menos só as taxas dos fills que reduzem posição (a terceira é um acréscimo deste script à comparação binária da spec).

| Contagem | Valor |
|---|---|
| episodes | 145 |
| excluded_broken | 1 |
| excluded_inversion | 19 |
| excluded_open_at_end | 7 |
| fee_matters | 118 |
| gross | 48 |
| gross_when_fee_matters | 48 |
| net_all | 0 |
| net_all_when_fee_matters | 0 |
| net_close | 0 |
| net_close_when_fee_matters | 0 |
| tested | 118 |

Leitura: **closedPnl concilia com a hipótese gross** — gross 93.2%, net_all 0.0%, net_close 0.0% (tolerância 0.001; 118 episódios em que a taxa importa); na tolerância da spec (1e-6), gross concilia 40.7%.

Episódios que conciliam, por tolerância (relativa e absoluta iguais):

| Tolerância | Episódios testados | gross | net_all | net_close |
|---|---|---|---|---|
| 1e-06 | 118 | 48 (40.7%) | 0 (0.0%) | 0 (0.0%) |
| 0.0001 | 118 | 88 (74.6%) | 0 (0.0%) | 0 (0.0%) |
| 0.001 | 118 | 110 (93.2%) | 0 (0.0%) | 0 (0.0%) |
| 0.01 | 118 | 116 (98.3%) | 4 (3.4%) | 17 (14.4%) |

Conferência fill a fill (aberturas devem ter `closedPnl` 0 se for bruto, ou menos a taxa se for líquido; fechamentos devem ter o realizado, com ou sem a própria taxa):

| Tolerância | abertura = 0 | abertura = -taxa | fechamento = realizado | fechamento = realizado - taxa |
|---|---|---|---|---|
| 1e-06 | 722 / 722 | 0 / 722 | 183 / 646 | 0 / 646 |
| 0.001 | 722 / 722 | 1 / 722 | 623 / 646 | 1 / 646 |

Hipótese bruta por número de fills do episódio:

| Episódio | Testados | Concilia em 1e-6 | Concilia em 1e-3 |
|---|---|---|---|
| 2 fills | 15 | 15 (100.0%) | 15 (100.0%) |
| 3-4 fills | 15 | 10 (66.7%) | 14 (93.3%) |
| 5+ fills | 88 | 23 (26.1%) | 81 (92.0%) |

Diagnóstico das 17 quebras de continuidade: `dir` do fill anterior {'Close Long': 6, 'Close Short': 2, 'Open Long': 7, 'Long > Short': 2}; tamanho do salto {'salto >= tamanho do fill anterior': 9, 'salto menor': 8}; com campo `liquidation` em um dos dois fills: 0; intervalo entre os dois fills: mediana 7,492 s, máximo 935,965 s, 0 com menos de 1 s.


### `aggregateByTime` falso e verdadeiro (janela de seleção)

| Carteira | Falso | Verdadeiro |
|---|---|---|
| `0x6118bc9c2fe6c10261d199c52a5d9b657a7e84ca` | 4 | 4 |
| `0xbfba167ecc3d9e13a8401d8a7ca288240a952f33` | 10841 | 7749 |
| `0x67f4259074b626749691c0f31e3a78a9ceab405b` | 765 | 126 |
| `0x8c294aeb643f8099f3d15fb47e437edd72df4022` | 313 | 93 |
| `0x3609a72d39d526f7885f2a8ec5728be923032b3a` | 2 | 1 |
| `0x20b5e2391abe9ef5ff75d160109da395f443e953` | 0 | 0 |
| `0xc27df0a5459a75ab4fe623b0c2a2021791266f55` | 136 | 96 |
| `0xb75055233b067dd97bae6babd28e6a095c3d97ae` | 0 | 0 |
| `0x07313ac0106cce8ace35caba54e4b11dab2ae42d` | 0 | 0 |
| `0x1f75442e5d0856193986560934e1e6eb5faaf3c5` | 58 | 17 |
| `0x26d957cf59e34a37080691c5024e307393eb69b3` | 2 | 2 |
| `0xfd993896bb8bf7d01eb3b00b57210ae584c85750` | 0 | 0 |
| `0x64d8fdf7346337953c434824a84072dc53fcccd8` | 18 | 5 |
| `0xbc476160765ff70cbd78d5a63aaa885555d575f1` | 0 | 0 |
| `0x63d6cbd12a2984c211ff623074e9362e4520e902` | 965 | 599 |
| `0x9af02b863f5d404841a1166ca4dd9b810512e40f` | 0 | 0 |
| `0xe1dc587acfc93f1ef87d3b17e33af9aebfc6b972` | 36 | 14 |
| `0x90d97d27cf9437694cb554fe69468a0f3e20459f` | 0 | 0 |
| `0xce700c52f85779c8f2e6b8908dca62963889da0b` | 0 | 0 |
| `0xf9d5aa669b007610c14b58073e54f1aa93adea26` | 767 | 323 |
| **Total** | **13907** | **9029** |

### Quebra de continuidade de posição (RF-ING-03 CA-03.1), amostra de RF-VER-01

| Medida | Valor |
|---|---|
| Carteiras com fills de perpétuo do `meta` | 7 |
| Séries (carteira, ativo) | 28 |
| Pares consecutivos conferidos | 2,068 |
| Pares com quebra | 17 (0.822%) |
| … dos quais entre fills do mesmo milissegundo | 0 |
| Séries com ao menos uma quebra | 10 |
| Carteiras com ao menos uma quebra | 3 |

### Complemento: mesma medição na amostra maior de RF-VER-02 (não é da spec)

| Medida | Valor |
|---|---|
| Carteiras com fills de perpétuo do `meta` | 36 |
| Séries (carteira, ativo) | 385 |
| Pares consecutivos conferidos | 53,666 |
| Pares com quebra | 83 (0.155%) |
| … dos quais entre fills do mesmo milissegundo | 0 |
| Séries com ao menos uma quebra | 30 |
| Carteiras com ao menos uma quebra | 4 |

`closedPnl` na amostra maior: **ok:gross** — gross 80.3%, net_all 0.0%, net_close 1.2% (tolerância 0.001; 860 episódios em que a taxa importa); na tolerância da spec (1e-6), gross concilia 25.6%.

| Contagem | Valor |
|---|---|
| episodes | 984 |
| excluded_broken | 11 |
| excluded_inversion | 37 |
| excluded_open_at_end | 76 |
| fee_matters | 860 |
| gross | 220 |
| gross_when_fee_matters | 220 |
| net_all | 0 |
| net_all_when_fee_matters | 0 |
| net_close | 0 |
| net_close_when_fee_matters | 0 |
| tested | 860 |

Episódios que conciliam, por tolerância (relativa e absoluta iguais):

| Tolerância | Episódios testados | gross | net_all | net_close |
|---|---|---|---|---|
| 1e-06 | 860 | 220 (25.6%) | 0 (0.0%) | 0 (0.0%) |
| 0.0001 | 860 | 523 (60.8%) | 0 (0.0%) | 0 (0.0%) |
| 0.001 | 860 | 691 (80.3%) | 0 (0.0%) | 10 (1.2%) |
| 0.01 | 860 | 804 (93.5%) | 69 (8.0%) | 155 (18.0%) |

Conferência fill a fill (aberturas devem ter `closedPnl` 0 se for bruto, ou menos a taxa se for líquido; fechamentos devem ter o realizado, com ou sem a própria taxa):

| Tolerância | abertura = 0 | abertura = -taxa | fechamento = realizado | fechamento = realizado - taxa |
|---|---|---|---|---|
| 1e-06 | 19347 / 19347 | 0 / 19347 | 2172 / 16060 | 0 / 16060 |
| 0.001 | 19347 / 19347 | 28 / 19347 | 13790 / 16060 | 504 / 16060 |

Hipótese bruta por número de fills do episódio:

| Episódio | Testados | Concilia em 1e-6 | Concilia em 1e-3 |
|---|---|---|---|
| 2 fills | 36 | 36 (100.0%) | 36 (100.0%) |
| 3-4 fills | 83 | 56 (67.5%) | 76 (91.6%) |
| 5+ fills | 741 | 128 (17.3%) | 579 (78.1%) |

Diagnóstico das 83 quebras de continuidade: `dir` do fill anterior {'Open Long': 33, 'Close Long': 23, 'Close Short': 17, 'Open Short': 9, 'Auto-Deleveraging': 1}; tamanho do salto {'salto >= tamanho do fill anterior': 70, 'salto menor': 13}; com campo `liquidation` em um dos dois fills: 3; intervalo entre os dois fills: mediana 81,472 s, máximo 2,264,573 s, 0 com menos de 1 s.


### CA-01.5 — fluxo público de negócios

| Medida | Valor |
|---|---|
| Ativo e janela de gravação conferida | BTC, 10.0 min |
| Negócios | 799 |
| Com os endereços das duas pontas | 799 (100.000%) |
| Endereços distintos | 249 |
| Comprador e vendedor com o mesmo endereço | 0 |
| Campos de cada negócio | {'coin': 799, 'side': 799, 'px': 799, 'sz': 799, 'time': 799, 'hash': 799, 'tid': 799, 'users': 799} |

## RF-VER-02 — cobertura do universo

| Critério | Regra da spec | Medido | Status |
|---|---|---|---|
| `CA-02.1` | informar a fração do notional em cada ativo e a fração acumulada no universo | universo = 16.6% (todos os fills) / 41.3% (só perpétuos) | **ok** |
| `CA-02.2` | se a fração acumulada < 50%: listar os ativos a acrescentar pela regra D7; status 'universo a emendar' | acumulado 16.6% (todos) / 41.3% (perpétuos) | **a emendar** |

Amostra: 100 carteiras que passam em F1 (`userRole == "user"`) e F2 (patrimônio ≥ US$ 30.000), de um pool F2 de 18,369. Foram consultadas 100 para achar 100: papéis encontrados {'user': 100}. Só fills da janela de seleção. Falhas de coleta: 0.

### CA-02.1 — notional negociado por ativo

Volume `px x sz` somado nos fills da janela. "Todos": denominador com spot e HIP-3 inclusos. "Perpétuos": só perpétuos do primeiro dex.

| Ativo | Tipo | Fração (todos) | Fração (perpétuos) | No universo |
|---|---|---|---|---|
| `xyz:SKHX` | hip3 | 26.66% | — |  |
| `HYPE` | perp | 11.04% | 27.38% |  |
| `BTC` | perp | 9.34% | 23.17% | sim |
| `ETH` | perp | 5.41% | 13.43% | sim |
| `xyz:MU` | hip3 | 4.07% | — |  |
| `ZEC` | perp | 3.19% | 7.92% |  |
| `@107` | spot | 2.94% | — |  |
| `PUMP` | perp | 2.82% | 6.98% |  |
| `xyz:CXMT` | hip3 | 2.50% | — |  |
| `xyz:SNDK` | hip3 | 2.41% | — |  |
| `xyz:SKHY` | hip3 | 2.36% | — |  |
| `xyz:SPCX` | hip3 | 2.18% | — |  |
| `xyz:SMSN` | hip3 | 1.92% | — |  |
| `SOL` | perp | 1.88% | 4.67% | sim |
| `xyz:XYZ100` | hip3 | 1.39% | — |  |

**Acumulado no universo (BTC, ETH, SOL): 16.64% (todos os fills) e 41.27% (só perpétuos).**

Notional por tipo de ativo: outcome 0.2%, perp 40.3%, spot 4.7%, hip3 54.7%.

Fração do notional de cada carteira que cai no universo (o que F9 mede): n = 54, p25 0.0%, mediana 0.0%, p75 21.4%; 6 carteiras com ≥ 50%.

### CA-02.2 — regra D7

Existência do perpétuo na Binance conferida no arquivo público do dia 2026-07-18 para os 40 maiores perpétuos fora do universo. Nada foi acrescentado: só a lista que a regra D7 produziria.

- Base **todos os fills**, em ordem: 1. `HYPE` (11.04%; acumulado 27.7%), 2. `ZEC` (3.19%; acumulado 30.9%), 3. `PUMP` (2.82%; acumulado 33.7%), 4. `LIT` (1.04%; acumulado 34.7%), 5. `ENA` (0.98%; acumulado 35.7%)
- Base **só perpétuos**, em ordem: 1. `HYPE` (27.38%; acumulado 68.7%)

Sem equivalente verificado na Binance (pulados pela regra): ['CASHCAT', 'PURR'].

### Retenção nesta amostra (informativo)

Fills na janela: 124,971. O histórico começa antes da janela em 69.0% das carteiras ({'antes da janela': 69, 'sem fills': 21, 'dentro da janela': 5, 'depois da janela': 5}); mais de 10.000 fills devolvidos em 29 de 100; exatamente 10.000 em 0; maior total contado 17,216; sem fill na janela: 46.

## RF-VER-03 — validade do preço proxy

| Critério | Regra da spec | Medido | Status |
|---|---|---|---|
| `CA-03.1` | ao menos 10.000 fills de líderes por ativo; mediana e p95 em bps por ativo e por dia | fills por ativo: BTC 86, ETH 75, SOL 20 | **reprova** |
| `CA-03.2` | p95 do desvio absoluto em relação à mediana do dia > 10 bps: 'proxy inválido' (sai da Rota A) | BTC: ok (n=86), ETH: ok (n=75), SOL: ok (n=20) | **não medido** |

Dias sorteados da janela (semente `20261005`): 2026-07-10, 2026-07-18, 2026-07-19, 2026-07-26, 2026-08-04. Fills de líderes: os da amostra de RF-VER-02, nesses dias. Proxy do segundo = último negócio do segundo (`last`); `mid` é sensibilidade.

| Arquivo | Zip | CSV | Negócios | Segundos com negócio | Checksum |
|---|---|---|---|---|---|
| `BTCUSDT` 2026-07-10 | 13.1 MB | 70.6 MB | 1,114,857 | 83,730 | confere |
| `BTCUSDT` 2026-07-18 | 4.8 MB | 25.1 MB | 396,032 | 76,028 | confere |
| `BTCUSDT` 2026-07-19 | 6.4 MB | 33.7 MB | 532,421 | 78,645 | confere |
| `BTCUSDT` 2026-07-26 | 5.6 MB | 29.4 MB | 463,639 | 77,792 | confere |
| `BTCUSDT` 2026-08-04 | 11.0 MB | 58.8 MB | 927,811 | 82,193 | confere |
| `ETHUSDT` 2026-07-10 | 12.1 MB | 57.0 MB | 901,649 | 82,366 | confere |
| `ETHUSDT` 2026-07-18 | 4.7 MB | 21.7 MB | 342,897 | 74,459 | confere |
| `ETHUSDT` 2026-07-19 | 7.0 MB | 33.1 MB | 522,921 | 77,620 | confere |
| `ETHUSDT` 2026-07-26 | 7.5 MB | 35.4 MB | 560,008 | 77,519 | confere |
| `ETHUSDT` 2026-08-04 | 10.3 MB | 48.8 MB | 772,121 | 81,178 | confere |
| `SOLUSDT` 2026-07-10 | 3.0 MB | 13.3 MB | 219,635 | 75,032 | confere |
| `SOLUSDT` 2026-07-18 | 1.8 MB | 8.0 MB | 131,799 | 65,453 | confere |
| `SOLUSDT` 2026-07-19 | 2.2 MB | 10.1 MB | 166,295 | 70,398 | confere |
| `SOLUSDT` 2026-07-26 | 2.2 MB | 9.9 MB | 162,782 | 68,545 | confere |
| `SOLUSDT` 2026-08-04 | 2.2 MB | 9.5 MB | 156,982 | 67,939 | confere |

### BTC

| Dia | Fills | Sem proxy no segundo | Mediana (bps) | p95 abs(dif) (bps) | p95 abs(dif - mediana do dia) (bps) | idem, base `mid` |
|---|---|---|---|---|---|---|
| 2026-07-10 | 3 | 0 | 4.02 | 4.04 | 0.01 | 0.01 |
| 2026-07-18 | 0 | 0 | — | — | — | — |
| 2026-07-19 | 0 | 0 | — | — | — | — |
| 2026-07-26 | 13 | 0 | 0.73 | 0.73 | 0.01 | 0.02 |
| 2026-08-04 | 70 | 3 | 0.00 | 1.18 | 1.18 | 0.78 |

Total BTC: 86 fills (83 com proxy no segundo). p95 do desvio em relação à mediana do dia, agregando os dias: 1.06 bps (`last`), 0.78 bps (`mid`). Dias acima de 10 bps: nenhum.

### ETH

| Dia | Fills | Sem proxy no segundo | Mediana (bps) | p95 abs(dif) (bps) | p95 abs(dif - mediana do dia) (bps) | idem, base `mid` |
|---|---|---|---|---|---|---|
| 2026-07-10 | 1 | 0 | 3.36 | 3.36 | 0.00 | 0.00 |
| 2026-07-18 | 1 | 0 | 5.43 | 5.43 | 0.00 | 0.00 |
| 2026-07-19 | 5 | 0 | 8.06 | 8.06 | 3.07 | 3.41 |
| 2026-07-26 | 41 | 0 | 1.38 | 1.38 | 0.49 | 0.52 |
| 2026-08-04 | 27 | 0 | 1.01 | 1.97 | 1.87 | 1.87 |

Total ETH: 75 fills (75 com proxy no segundo). p95 do desvio em relação à mediana do dia, agregando os dias: 1.87 bps (`last`), 1.87 bps (`mid`). Dias acima de 10 bps: nenhum.

### SOL

| Dia | Fills | Sem proxy no segundo | Mediana (bps) | p95 abs(dif) (bps) | p95 abs(dif - mediana do dia) (bps) | idem, base `mid` |
|---|---|---|---|---|---|---|
| 2026-07-10 | 3 | 0 | 2.44 | 3.36 | 0.95 | 0.85 |
| 2026-07-18 | 0 | 0 | — | — | — | — |
| 2026-07-19 | 17 | 0 | 1.71 | 2.90 | 1.71 | 1.58 |
| 2026-07-26 | 0 | 0 | — | — | — | — |
| 2026-08-04 | 0 | 0 | — | — | — | — |

Total SOL: 20 fills (20 com proxy no segundo). p95 do desvio em relação à mediana do dia, agregando os dias: 1.71 bps (`last`), 1.58 bps (`mid`). Dias acima de 10 bps: nenhum.

Para dimensionar o déficit de CA-03.1: nos 62 dias da janela inteira, a mesma amostra de carteiras tem BTC 2,739, ETH 2,189, SOL 1,089 fills (contra os 10.000 por ativo que o critério pede).

## RF-VER-04 — orçamento de dados

| Critério | Regra da spec | Medido | Status |
|---|---|---|---|
| `CA-04.1` | bytes gravados por ativo em uma hora e a extrapolação para 45 dias | 60 min; 45 dias = 13.11 GB bruto / 1.70 GB gzip | **ok** |
| `CA-04.2` | tamanho de um dia de proxy por ativo e extrapolação para todas as janelas | proxy, 154 dias: 2.82 GB em zips | **ok** |
| `CA-04.3` | alguma extrapolação excede o orçamento de RNF-10 (30 GB): 'orçamento a emendar' | orçamento 30 GB; maior extrapolação individual 19.43 GB | **ok** |

Gravação: início 2026-10-06T04:30:51Z, duração 60.0 min, eventos {'connect': 2, 'end': 1, 'start': 1}. Formato: mensagem JSON bruta + instante de recebimento, um arquivo por (ativo, canal).

| Ativo | Canal | Mensagens | Itens | Bytes | gzip | Msg/s | Intervalo entre atualizações da corretora p50 (s) | p95 (s) | recebimento - corretora p50 / p95 / p99 (ms) |
|---|---|---|---|---|---|---|---|---|---|
| BTC | l2Book | 671 | 670 | 1.0 MB | 156.2 kB | 0.19 | 5.395 | 5.524 | 366 / 617 / 831 |
| BTC | l2BookFast | 6,609 | 6,608 | 3.1 MB | 244.5 kB | 1.84 | 0.539 | 0.606 | 322 / 580 / 868 |
| BTC | bbo | 17,130 | 17,129 | 2.6 MB | 280.5 kB | 4.76 | 0.134 | 0.623 | 282 / 554 / 878 |
| BTC | trades | 2,582 | 6,124 | 1.7 MB | 274.7 kB | 0.72 | 1.005 | 4.053 | 303 / 726 / 1027 |
| ETH | l2Book | 671 | 670 | 1.0 MB | 179.8 kB | 0.19 | 5.395 | 5.524 | 367 / 623 / 839 |
| ETH | l2BookFast | 6,608 | 6,607 | 3.0 MB | 300.2 kB | 1.84 | 0.539 | 0.606 | 322 / 580 / 869 |
| ETH | bbo | 12,963 | 12,962 | 2.0 MB | 219.7 kB | 3.60 | 0.137 | 0.942 | 283 / 551 / 879 |
| ETH | trades | 1,519 | 2,620 | 771.4 kB | 125.0 kB | 0.42 | 1.829 | 8.519 | 315 / 645 / 909 |
| SOL | l2Book | 671 | 670 | 1.0 MB | 150.4 kB | 0.19 | 5.395 | 5.524 | 368 / 623 / 839 |
| SOL | l2BookFast | 6,608 | 6,607 | 3.0 MB | 258.0 kB | 1.84 | 0.539 | 0.606 | 322 / 580 / 869 |
| SOL | bbo | 13,046 | 13,045 | 1.9 MB | 198.2 kB | 3.62 | 0.180 | 0.805 | 281 / 549 / 857 |
| SOL | trades | 669 | 1,135 | 337.1 kB | 60.9 kB | 0.19 | 4.354 | 14.993 | 305 / 493 / 759 |

A primeira mensagem de cada assinatura é um snapshot e fica fora das colunas de intervalo e de atraso (os bytes contam tudo). Snapshot de `trades`: BTC/trades: 30 itens, até 8 s de idade; ETH/trades: 30 itens, até 11 s de idade; SOL/trades: 30 itens, até 45 s de idade.

A diferença recebimento - corretora mistura latência de rede com diferença entre os relógios das duas máquinas; fração negativa por canal: BTC/l2Book 0.0%, BTC/l2BookFast 0.0%, BTC/bbo 0.0%, BTC/trades 0.0%, ETH/l2Book 0.0%, ETH/l2BookFast 0.0%, ETH/bbo 0.0%, ETH/trades 0.0%, SOL/l2Book 0.0%, SOL/l2BookFast 0.0%, SOL/bbo 0.0%, SOL/trades 0.0%.

### CA-04.1 — extrapolação para 45 dias

| Ativo | Variante | Medido em 1.00 h | 45 dias (bruto) | 45 dias (gzip) |
|---|---|---|---|---|
| BTC | default | 5.4 MB | 5.67 GB | 750.4 MB |
| BTC | fast | 7.4 MB | 7.81 GB | 843.6 MB |
| BTC | no_book_depth | 4.3 MB | 4.58 GB | 585.7 MB |
| ETH | default | 3.8 MB | 3.97 GB | 553.4 MB |
| ETH | fast | 5.8 MB | 6.08 GB | 680.4 MB |
| ETH | no_book_depth | 2.7 MB | 2.87 GB | 363.7 MB |
| SOL | default | 3.3 MB | 3.46 GB | 432.1 MB |
| SOL | fast | 5.3 MB | 5.54 GB | 545.6 MB |
| SOL | no_book_depth | 2.3 MB | 2.39 GB | 273.4 MB |
| **Total** | default | 12.4 MB | 13.11 GB | 1.70 GB |
| **Total** | fast | 18.4 MB | 19.43 GB | 2.02 GB |
| **Total** | no_book_depth | 9.3 MB | 9.84 GB | 1.19 GB |

Extrapolação linear a partir de uma única janela de gravação: não captura variação ao longo do dia nem de regime de mercado.

### CA-04.2 — preço proxy

| Ativo | Dias medidos | Zip médio/dia | CSV médio/dia | Série por segundo média/dia | Zips, 92 dias (Rota A) | Zips, 154 dias (todas as janelas) |
|---|---|---|---|---|---|---|
| BTC | 5 | 8.2 MB | 43.5 MB | 377.1 kB | 751.3 MB | 1.23 GB |
| ETH | 5 | 8.3 MB | 39.2 MB | 364.0 kB | 764.9 MB | 1.25 GB |
| SOL | 5 | 2.3 MB | 10.2 MB | 211.5 kB | 209.3 MB | 350.3 MB |
| **Total** |  |  |  |  | 1.69 GB | 2.82 GB |

### CA-04.3 — contra o orçamento de RNF-10

| Extrapolação | GB | Excede 30 GB |
|---|---|---|
| coletor, 45 dias, l2Book default (20 níveis, ~5 s) + bbo + trades (bruto) | 13.11 | não |
| coletor, 45 dias, l2Book default (20 níveis, ~5 s) + bbo + trades (gzip) | 1.70 | não |
| coletor, 45 dias, l2Book rápido (5 níveis, ~0,5 s) + bbo + trades (bruto) | 19.43 | não |
| coletor, 45 dias, l2Book rápido (5 níveis, ~0,5 s) + bbo + trades (gzip) | 2.02 | não |
| coletor, 45 dias, bbo + trades, sem l2Book (bruto) | 9.84 | não |
| coletor, 45 dias, bbo + trades, sem l2Book (gzip) | 1.19 | não |
| proxy, 154 dias, zips mantidos | 2.82 | não |
| proxy, 154 dias, só a série por segundo | 0.14 | não |
| soma pior caso: maior variante do coletor (bruto) + zips do proxy | 22.25 | não |
| soma melhor caso: menor variante do coletor (gzip) + série por segundo | 1.33 | não |

Orçamento de disco da fase inteira: 30 GB. A regra da spec é por extrapolação individual; as somas são informativas.

## O que contradiz a spec

Cada item cita a regra da spec ou do ADR, o que os dados mostraram e o que isso toca. Nada abaixo foi corrigido na spec.

**1. O teto de 10.000 fills por carteira não se aplica à paginação por tempo.**
ADR-0001 diz que "a API devolve até 10.000 fills por carteira" e que carteiras com mais de 10.000 fills desde o início da janela "são excluídas e contadas"; F3, RF-ING-02 CA-02.3 e RF-VER-01 CA-01.2 também supõem um teto. A documentação lida diz o mesmo ("only the 10,000 most recent fills are available"). Paginando `userFillsByTime` por intervalo de tempo, a API devolveu **mais de 10.000 fills em 7 das 20 carteiras da amostra de RF-VER-01 e em 29 das 100 da amostra de RF-VER-02**, e em nenhuma o total parou em exatamente 10.000. Uma carteira devolveu 31.331 fills (contagem validada na exploração, somando três partições de tempo independentes, que bateram), remontando a janeiro de 2024; o fill mais antigo visto na amostra de 20 é de 2023-11-30. A contagem desta execução para cedo ao passar de 10.000 (o maior total contado é 17.216), então **a profundidade real de retenção não foi medida**. Toca: a regra de exclusão do ADR-0001 e o filtro F3 excluiriam carteiras ativas sem necessidade; a regra de retenção precisa ser reescrita em termos do que a API de fato devolve.

**2. `closedPnl` é bruto de taxa, mas não concilia na tolerância de 1e-6 de RF-ING-04 CA-04.2.**
A resposta a RF-VER-01 CA-01.4 é inequívoca: as hipóteses líquidas concordam com 0% dos episódios (até 1,2% em uma delas na amostra de 100, em tolerância 1e-3), e os fills que abrem ou aumentam posição têm `closedPnl` igual a zero em 19.347 de 19.347 casos (amostra de 100). Mas a reconstrução por custo médio de preços e tamanhos só fecha na tolerância da spec nos episódios de **2 fills** (36 de 36 e 15 de 15, 100%). Nos episódios com 5 ou mais fills, concilia em **17% (amostra de 100) e 26% (amostra de 20) na tolerância de 1e-6**; em 1e-3 sobe para 78% e 92%, e em 1e-2 para 93,5% (amostra de 100). Fill a fill, os fechamentos batem com o realizado em 85,9% dos casos em 1e-3 (13.790 de 16.060). A contabilidade de preço de entrada da corretora não é a média ponderada simples, e a causa **não foi identificada**. Toca: RF-ING-04 CA-04.2 torna "inelegível" a carteira com divergência acima de 1e-6; com essa tolerância e esse método de reconstrução, a maioria das carteiras com episódios de vários fills seria eliminada. A definição de "divergência" e a origem do PnL do líder (reconstruído ou o `closedPnl` por fill) são decisões de design.

**3. A continuidade de posição quebra em fills reais, sem relação com a ordem de mesmo milissegundo.**
RF-ING-03 supõe que fills consecutivos encadeiam a posição e trata a quebra como exceção. Medido nos perpétuos do `meta`: **0,82% dos pares quebram na amostra de 20 (17 de 2.068; 3 de 7 carteiras com fills de perpétuo) e 0,16% na de 100 (83 de 53.666; 4 de 36 carteiras)**. Zero quebras ocorrem entre fills do mesmo milissegundo, então não é ambiguidade de ordenação. O intervalo mediano entre os dois fills quebrados é de 7.492 s (amostra de 20) e 81.472 s (amostra de 100), com máximo de 26 dias; em 9 de 17 e 70 de 83 quebras o salto é pelo menos do tamanho do fill anterior. É compatível com fill ausente na resposta ou com mudança de posição sem fill (há 1 `Auto-Deleveraging` e 3 pares com o campo `liquidation`), e os dados **não distinguem** as duas. Toca: F3 e a regra "quebra de continuidade torna a carteira inelegível" têm efeito real, da ordem de 11% das carteiras com perpétuos na amostra de 100.

**4. O universo BTC, ETH e SOL cobre menos de 50% do volume, e a regra D7 não chega a 50% em uma das duas bases.**
Na amostra de 100 carteiras F1+F2 (124.971 fills na janela), o universo tem **16,6% do notional de todos os fills** e **41,3% do notional de perpétuos do primeiro dex**: abaixo de 50% nas duas leituras, o que dá o status "universo a emendar". Pela regra D7, a lista (em ordem) é `HYPE`, `ZEC`, `PUMP`, `LIT`, `ENA` na base de todos os fills, que para no limite de 8 ativos com **35,7% acumulado, ainda abaixo de 50%**; na base de só perpétuos, `HYPE` sozinho leva a 68,7%. `CASHCAT` e `PURR` foram pulados por não terem equivalente verificado na Binance. A spec não diz qual é o denominador de "notional negociado", e o status de CA-02.2 é o mesmo nas duas, mas o caminho de ampliação não é. O que pesa: **54,7% do notional é HIP-3** (`xyz:*`, `io:*`), fora do escopo, 4,7% é spot e 0,2% é de tokens de resultado.

**5. Metade da amostra F1+F2 não opera na janela, e quase ninguém concentra em BTC, ETH e SOL.**
Das 100 carteiras que passam em F1 e F2, 46 não têm um único fill na janela (21 não têm fill nenhum no histórico devolvido). F1 não eliminou nenhuma (100 de 100 com `userRole = "user"`). Das 54 carteiras com fills, só **6 têm 50% ou mais do notional no universo** (F9), a mediana é 0,0% e o p75 é 21,4%. Toca: o funil de §7.3 e o tamanho do pool de candidatas para a Rota A e a coorte de K carteiras.

**6. O `l2Book` default chega a cada ~5,4 s, não a cada ~0,5 s como o ADR-0003 e RF-SIM-03 supõem.**
ADR-0003: "na Rota B há retratos do livro a cada meio segundo, aproximadamente". Gravado por uma hora, o `l2Book` na assinatura default (20 níveis) tem intervalo mediano de **5,395 s** (0,19 mensagens/s). Com `fast: true` (5 níveis) o intervalo mediano é **0,539 s**, e o canal `bbo` (melhor compra e venda, só em mudança) tem mediana de 0,13 a 0,18 s. Ou seja, a premissa só vale na assinatura rápida, com 5 níveis de profundidade. Toca: o "pior preço entre as duas observações adjacentes" de RF-SIM-03 CA-03.2 e a profundidade de CA-03.3 ("percorre os níveis gravados") dependem de qual assinatura o coletor usa.

**7. A regra de lacuna de 10 s de RF-COL-02 CA-02.2 dispara em silêncio normal do fluxo de negócios.**
Em uma hora sem nenhuma desconexão, o fluxo de `trades` teve **5 intervalos acima de 10 s em BTC, 37 em ETH e 104 em SOL** (máximo 30 s), enquanto `bbo` e `l2Book` não passaram de 7,3 s. Aplicada ao `trades`, a regra marcaria como lacuna mercado quieto.

**8. A spec não prevê classes de fill que aparecem na resposta.**
Além de perpétuos, HIP-3 e spot, há fills de **tokens de resultado** (moedas `#NNNN`; `dir` `Buy`, `Sell`, `Merge Outcome`, `Negate Outcome`, `Settlement`), e os `Settlement` trazem `px = 0`. Há também `Spot Dust Conversion` com `tid = 0` e `hash` zerado. Por isso **RF-VER-01 CA-01.1 reprova** na leitura literal (qualquer campo abaixo de 100%): `px` em 99,99% e `tid` em 99,97% nos 13.907 fills da amostra de 20. Todos os fills de perpétuo do primeiro dex e de HIP-3 passam em 100% dos 12 campos; as falhas vêm de spot (`tid`) e de tokens de resultado (`px`). Os fills trazem ainda campos que a spec não lista: `hash`, `feeToken`, `twapId` (sempre), `liquidation` (66 fills) e `builderFee` e `cloid` (3).

**9. `aggregateByTime` muda a contagem em 35%.**
Na amostra de 20, a janela tem 13.907 fills com `aggregateByTime` falso e 9.029 com verdadeiro. A spec não fixa qual usar, e RF-ING-03 (continuidade) e RF-ING-04 (episódios) foram medidos com o falso.

**10. O preço proxy não foi invalidado, mas a medida é fraca e o proxy tem viés de nível.**
Nos 5 dias sorteados, o p95 do desvio em relação à mediana do dia ficou entre 0,8 e 1,9 bps (muito abaixo de 10 bps), **com 86 fills de BTC, 75 de ETH e 20 de SOL**, e por isso CA-03.1 reprova e CA-03.2 fica "não medido". As medianas diárias do desvio não são negativas em nenhum dia com fills (de 0,0 a 8,1 bps, com 1 a 70 fills por dia; preço da Hyperliquid igual ou acima da Binance), um deslocamento que a regra de CA-03.2 (desvio em relação à mediana do dia) não enxerga.

**Sem contradição, confirmado em dado real:** o leaderboard tem `ethAddress`, `accountValue` e `windowPerformances` em todas as 47.430 linhas (janelas `day`, `week`, `month` e `allTime`, com `pnl`, `roi` e `vlm`); o fluxo público de `trades` traz os endereços das duas pontas em 799 de 799 negócios (RF-COL-03 permanece no escopo); o peso de uma página cheia de fills é de cerca de 120 e o orçamento de 1.200 por minuto foi respeitado sem nenhum HTTP 429 (pico de 1.000 contra um orçamento de 1.000); os arquivos da Binance conferem com o `.CHECKSUM` publicado (15 de 15); o orçamento de disco de RNF-10 não é excedido por nenhuma extrapolação individual (a maior é 19,43 GB, e a soma pessimista é 22,25 GB).

## O que não foi possível medir

Cada item diz o que faltou e por quê.

1. **RF-VER-03 CA-03.1 e CA-03.2 (validade do proxy).** Os 10.000 fills por ativo não foram atingidos nos 5 dias sorteados (BTC 86, ETH 75, SOL 20), e a conta fica aquém também na janela inteira: a mesma amostra de 100 carteiras tem 2.739 fills de BTC, 2.189 de ETH e 1.089 de SOL nos 62 dias. Para chegar a 10.000 por ativo com esta fonte, a amostra de líderes teria de crescer cerca de 3,7 vezes para BTC, 4,6 para ETH e 9,2 para SOL (aritmética sobre os números medidos, não uma recomendação). Os desvios reportados são indicativos, e CA-03.2 fica "não medido".
2. **A profundidade real de retenção de `userFillsByTime`.** A contagem parou ao passar de 10.000 fills (maior total contado: 17.216). Não se sabe até onde a API devolve histórico, nem se o histórico devolvido é completo (ver quebras de continuidade).
3. **A causa das quebras de continuidade.** Os dados não distinguem fill ausente na resposta de mudança de posição sem fill (ADL, liquidação, outro mecanismo).
4. **A causa do desvio de `closedPnl` em episódios de vários fills.** Só se testou a média ponderada simples. Não há, nos endpoints usados, o preço de entrada que a corretora aplica, então a hipótese de arredondamento ou de outra regra de custo médio não foi verificada. Episódios terminados por inversão (19 de 145 na amostra de 20; 37 de 984 na de 100), com posição aberta no fim (7 e 76) ou com quebra de continuidade (1 e 11) ficaram fora do teste.
5. **O denominador de "notional negociado" (CA-02.1).** A spec não o define. As duas bases foram reportadas, e nenhuma foi escolhida. O resultado também depende de a amostra incluir 46 carteiras sem fills na janela, que não pesam no notional agregado.
6. **RF-VER-04 CA-04.1 além de uma hora.** Uma única janela de gravação (terça-feira, 04:30 a 05:30 UTC) extrapolada linearmente para 45 dias: não captura variação de volume ao longo do dia, da semana nem de regime de mercado. O formato gravado é a mensagem JSON bruta com o instante de recebimento, não o do coletor, e só se mediram as profundidades das assinaturas default (20 níveis) e rápida (5 níveis); "profundidade adicional configurável" (RF-COL-01) não foi explorada.
7. **O tratamento de lacunas (RF-COL-02).** Em uma hora houve 2 conexões e nenhuma reconexão, então reconexão e registro de lacuna não foram exercitados. A latência recebimento menos corretora (mediana de 280 a 370 ms) mistura rede e diferença de relógio entre as duas máquinas, e os dois efeitos não foram separados.
8. **`fundingHistory` e `szDecimals` além do `meta`.** O prompt pedia para confirmar o formato de `fundingHistory` antes de usá-lo; ele não faz parte de RF-VER-01 a RF-VER-04 e não foi usado nem confirmado.
9. **A janela de avaliação.** Por regra (3 do prompt), o conteúdo de fills a partir de 2026-09-01 não foi lido, só contado, e essas contagens entram apenas no total usado para a retenção. Qualquer pergunta que exija olhar esse período fica sem resposta.
10. **Desempenho.** Nenhum PnL, retorno ou ranking de carteira foi calculado, impresso ou gravado, exceto as contagens de concordância de CA-01.4. Dos valores de `windowPerformances` do leaderboard só se confirmou a estrutura.
11. **Existência do equivalente na Binance (regra D7).** Conferida só pelo arquivo público de um dia (2026-07-18) e pelo mapeamento `k` -> `1000` para símbolos; um ativo listado depois dessa data apareceria como "sem equivalente".
12. **CA-01.5 sem gravação própria de 10 minutos.** Os 10 minutos de `trades` de BTC vêm dos primeiros 10 minutos da gravação de uma hora (sem a mensagem de snapshot da assinatura, que traz 30 negócios com até 45 s de idade).

## Notas de método

- **O que é decisão do script, não da spec.** Tolerância absoluta de 1e-6 USD junto da relativa; a terceira hipótese `net_close` e a escada de tolerâncias de CA-01.4; a margem de 50 pontos percentuais para dizer qual hipótese descreve `closedPnl`; `last` como preço do segundo do proxy (com `mid` como sensibilidade); e a leitura de CA-03.2 por ativo agregando os dias (a leitura por ativo-dia está nas tabelas). O proxy de um segundo sem negócio na Binance não é preenchido: o fill fica fora (3 de 86 em BTC).
- **Dados brutos e a regra 2.** `data/verify/` (fora do git) guarda os fills da janela de seleção como a API os devolveu, o que inclui o campo `closedPnl` de cada fill; nenhum PnL derivado foi gravado. O leaderboard foi guardado só com `ethAddress` e `accountValue` (e o hash do corpo bruto), sem `windowPerformances`. De fills anteriores à janela e posteriores ao corte guardam-se só contagem e, para os anteriores, o instante do mais antigo.
- **Reprodutibilidade.** A amostra depende do snapshot do leaderboard (que muda de hora em hora: entre a exploração e a execução a lista passou de 47.453 para 47.430 linhas); o `sha256` do snapshot está na tabela de execução. A coleta (rede) rodou das 04:30 às 05:30 UTC de 2026-10-06 com o código `cc93868`; depois dela, a análise foi refeita offline três vezes sobre os mesmos dados, sem nova requisição à API de informação, com correções de classificação e de relatório (commits `ab19d51` e `b5bb55b`). O relatório registra o hash da última geração.
- **Custo de coletar.** Com orçamento de 1.000 de peso por minuto, a amostra de 20 custou 9.383 de peso e a de 100 custou 52.415 (inclui 100 consultas de `userRole`, 6.000 de peso); a média é de cerca de 534 de peso de fills por carteira ativa na janela (máximo 1.064). Para 500 carteiras, se todas fossem ativas, seriam da ordem de 300.000 de peso (cerca de 5 horas no mesmo orçamento); como quase metade das candidatas não opera na janela, o custo real ficaria entre 2,5 e 5 horas (conta sobre os números medidos, não uma medida).

---

## Verificação complementar (RF-VER-05)

Código `db946ac+dirty`. Mesmas regras de RF-VER-01 a RF-VER-04: somente leitura, nada de desempenho, nada de conteúdo da janela de avaliação (toda consulta é cortada em 2026-09-01), semente `20261005`. Uso da API de informação: 227 requisições, peso 7877, pico de 1000 em 60 s (orçamento 1000), 0 respostas 429.

| Critério | Regra da spec | Medido | Status |
|---|---|---|---|
| `CA-05.1` | quantas quebras coincidem com fronteira de página; em 10 quebras sorteadas, uma nova consulta de 1 hora devolve fill que faltava? Se sim, o defeito é da coleta | 100 quebras; 16 atravessam uma fronteira de página; 0 de 10 consultas devolveram fill que faltava | **ok** |
| `CA-05.2` | mediana, p95, p99 e máximo da razão módulo(reconstruído - closedPnl) / notional, em bps, por faixa de fills, e a fração acima de 1 bp; acima de 5% RF-ING-04 CA-04.2 volta para emenda | 978 episódios; mediana 0.0021, p95 0.400, p99 1.407, máximo 3.263 bps; 1.7% acima de 1 bp | **ok** |
| `CA-05.3` | formato da resposta de fundingHistory e se há uma taxa para cada hora cheia | 168 registros em 168 horas; intervalo mediano 3600.000 s; horas com registro: 168/168 | **ok** |
| `CA-05.4` | 30 perpétuos de maior notional, fills e equivalente na Binance; carteiras com 50% ou mais do notional no universo, para dois universos (informativo) | F9 com BTC, ETH e SOL: 6 de 54; com os 27 listados com equivalente: 24 de 54 | **ok** |

### CA-05.1 — quebras de continuidade e paginação

**Como a coleta paginou:** inclusivo (startTime = instante do último fill da página anterior); fills não agregados; até 2000 por página; a repetição do milissegundo da fronteira é descartada por multiconjunto de chaves dos fills do milissegundo da fronteira. **A coleta original não guardou as fronteiras de página** e elas não foram reconstruídas por suposição: para medi-las, as carteiras com quebra foram **recoletadas** com a paginação instrumentada (segunda coleta, rotulada), e a recoleta foi comparada fill a fill com a primeira.

| Carteira recoletada | Páginas | Fills na janela | Fronteiras de página | Idêntica à primeira coleta (fills e ordem) |
|---|---|---|---|---|
| `0x3a90705c017255731c3ecac6f5bc3cd9ac3fae8b` | 5 | 6,109 | 3 | sim |
| `0x3af22be0e13429239a2bb6c60f70ecff6ebd5af3` | 5 | 6,039 | 3 | sim |
| `0x3e02519a47cef3d4464944c4815fad9e5837e767` | 3 | 2,522 | 1 | sim |
| `0x53f81d22b16ff1718ab8ee52bff0592685325f92` | 7 | 10,694 | 5 | sim |
| `0x63d6cbd12a2984c211ff623074e9362e4520e902` | 2 | 965 | 0 | sim |
| `0x64d8fdf7346337953c434824a84072dc53fcccd8` | 2 | 18 | 0 | sim |
| `0x8c294aeb643f8099f3d15fb47e437edd72df4022` | 2 | 313 | 0 | sim |

**100 quebras em 7 carteiras** (as duas amostras juntas, como em RF-VER-01 e RF-VER-02). **16 atravessam uma fronteira de página** (há uma fronteira entre os dois fills quebrados na lista da carteira) e **0 caem exatamente numa fronteira** (os dois fills são vizinhos na lista e a fronteira os separa).

Pares que atravessam uma fronteira, por vão (posições entre os dois fills na lista da carteira):

| Vão | Quebras que atravessam | Pares íntegros que atravessam |
|---|---|---|
| 1 | 1 de 891 | 10 de 20258 (0.05%) |
| 2 a 10 | 0 de 8 | 0 de 247 (0.00%) |
| 11 a 100 | 0 de 18 | 5 de 300 (1.67%) |
| 101 a 1000 | 9 de 32 | 5 de 100 (5.00%) |
| mais de 1000 | 7 de 8 | 11 de 15 (73.33%) |

Consulta nova de cada quebra sorteada (intervalo entre os dois fills quebrados, 1 minuto de folga de cada lado, no máximo 2 páginas):

| Quebra | Vão no tempo | Fills devolvidos | Fills já gravados no intervalo | Faltavam na coleta | Gravados e não devolvidos | Cobre o intervalo todo |
|---|---|---|---|---|---|---|
| `0x3e02519a…` ZEC | 27.8 h | 20 | 20 | 0 | 0 | sim |
| `0x53f81d22…` PUMP | 76.3 h | 286 | 286 | 0 | 0 | sim |
| `0x53f81d22…` ASTER | 64.3 h | 198 | 198 | 0 | 0 | sim |
| `0x53f81d22…` DOGE | 10.8 h | 113 | 113 | 0 | 0 | sim |
| `0x3e02519a…` CASHCAT | 134.2 h | 122 | 122 | 0 | 0 | sim |
| `0x3af22be0…` HYPE | 46.4 h | 548 | 548 | 0 | 0 | sim |
| `0x53f81d22…` PUMP | 126.2 h | 1059 | 1059 | 0 | 0 | sim |
| `0x53f81d22…` PUMP | 63.1 h | 412 | 412 | 0 | 0 | sim |
| `0x3a90705c…` HYPE | 28.2 h | 48 | 48 | 0 | 0 | sim |
| `0x3a90705c…` SOL | 13.6 h | 15 | 15 | 0 | 0 | sim |

**Complemento, fora da spec:** as outras 90 quebras foram reconsultadas do mesmo jeito (32,437 fills devolvidos): 88 consultas cobriram o intervalo todo; **0 devolveram fill que faltava**; 0 deixaram de devolver fill já gravado.

### CA-05.2 — divergência de PnL sobre o notional

Razão `|PnL reconstruído - soma dos closedPnl| / notional negociado no episódio`, em bps, nos episódios fechados e íntegros (zero a zero, sem inversão, sem quebra) das duas amostras. **Só razões e contagens: nenhum valor de PnL é impresso ou gravado.**

| Faixa | Episódios | Mediana (bps) | p95 (bps) | p99 (bps) | Máximo (bps) | Acima de 1 bp |
|---|---|---|---|---|---|---|
| 2 fills | 51 | 0.0000 | 0.000 | 0.000 | 0.000 | 0 (0.0%) |
| 3-4 fills | 98 | 0.0000 | 0.059 | 1.547 | 1.597 | 2 (2.0%) |
| 5+ fills | 829 | 0.0036 | 0.476 | 1.362 | 3.263 | 15 (1.8%) |
| **todos** | 978 | 0.0021 | 0.400 | 1.407 | 3.263 | 17 (1.7%) |
| amostra de RF-VER-01 (20) | 118 | 0.0003 | 0.174 | 0.836 | 1.597 | 1 (0.8%) |
| amostra de RF-VER-02 (100) | 860 | 0.0029 | 0.474 | 1.439 | 3.263 | 16 (1.9%) |

Por carteira: das 39 carteiras com episódio fechado e íntegro, 7 (17.9%) têm ao menos um episódio acima de 1 bp.

### CA-05.3 — funding

Formato conferido na documentação oficial (`POST /info`, `type = fundingHistory`, campos `coin`, `startTime`, `endTime` opcional; resposta com `coin`, `fundingRate`, `premium` e `time`). A documentação **não** informa o limite de registros por resposta, a ordenação nem a periodicidade.

| Medida | Valor |
|---|---|
| Semana consultada (BTC; bloco sorteado com a semente) | 2026-07-29T00:00:00Z a 2026-08-05T00:00:00Z |
| Registros devolvidos | 168 |
| Campos devolvidos e tipos | {'coin': 'str', 'fundingRate': 'str', 'premium': 'str', 'time': 'int'} |
| Intervalo entre registros (min / mediana / máx, s) | 3599.893 / 3600.000 / 3600.123 |
| Deslocamento do registro dentro da hora (min a máx, ms) | 0 a 127 |
| Horas cheias com ao menos um registro | 168 de 168 |
| Horas com mais de um registro | nenhuma |
| Registros fora das 168 horas | 0 |

### CA-05.4 — ativos e F9

Amostra de RF-VER-02: 100 carteiras, 54 com fills na janela. Notional somado de todos os fills da janela (volume, não desempenho). Existência do perpétuo na Binance conferida em 7 dias da janela (2026-07-01, 2026-07-10, 2026-07-18, 2026-07-19, 2026-07-26, 2026-08-04, 2026-08-31): "dias" é em quantos deles o arquivo diário do símbolo existe.

| # | Ativo | Fills | Notional (todos os fills) | Notional (só perpétuos) | Símbolo na Binance | Dias | Equivalente |
|---|---|---|---|---|---|---|---|
| 1 | `HYPE` | 14,322 | 11.04% | 27.38% | `HYPEUSDT` | 7/7 | sim |
| 2 | `BTC` | 2,739 | 9.34% | 23.17% | `BTCUSDT` | 7/7 | sim |
| 3 | `ETH` | 2,189 | 5.41% | 13.43% | `ETHUSDT` | 7/7 | sim |
| 4 | `ZEC` | 3,993 | 3.19% | 7.92% | `ZECUSDT` | 7/7 | sim |
| 5 | `PUMP` | 5,284 | 2.82% | 6.98% | `PUMPUSDT` | 7/7 | sim |
| 6 | `SOL` | 1,089 | 1.88% | 4.67% | `SOLUSDT` | 7/7 | sim |
| 7 | `LIT` | 3,834 | 1.04% | 2.58% | `LITUSDT` | 7/7 | sim |
| 8 | `ENA` | 1,658 | 0.98% | 2.44% | `ENAUSDT` | 7/7 | sim |
| 9 | `CASHCAT` | 4,522 | 0.65% | 1.61% | — | 0/7 | não |
| 10 | `INJ` | 1,419 | 0.44% | 1.10% | `INJUSDT` | 7/7 | sim |
| 11 | `DOGE` | 547 | 0.42% | 1.04% | `DOGEUSDT` | 7/7 | sim |
| 12 | `ASTER` | 581 | 0.34% | 0.84% | `ASTERUSDT` | 7/7 | sim |
| 13 | `TRUMP` | 439 | 0.21% | 0.52% | `TRUMPUSDT` | 7/7 | sim |
| 14 | `PENGU` | 621 | 0.19% | 0.46% | `PENGUUSDT` | 7/7 | sim |
| 15 | `GRAM` | 537 | 0.18% | 0.44% | `GRAMUSDT` | 6/7 | parcial |
| 16 | `VVV` | 437 | 0.18% | 0.44% | `VVVUSDT` | 7/7 | sim |
| 17 | `AAVE` | 646 | 0.17% | 0.42% | `AAVEUSDT` | 7/7 | sim |
| 18 | `FARTCOIN` | 669 | 0.16% | 0.39% | `FARTCOINUSDT` | 7/7 | sim |
| 19 | `XRP` | 338 | 0.16% | 0.39% | `XRPUSDT` | 7/7 | sim |
| 20 | `NEAR` | 513 | 0.13% | 0.33% | `NEARUSDT` | 7/7 | sim |
| 21 | `ADA` | 275 | 0.12% | 0.29% | `ADAUSDT` | 7/7 | sim |
| 22 | `XMR` | 943 | 0.12% | 0.29% | `XMRUSDT` | 7/7 | sim |
| 23 | `UNI` | 460 | 0.11% | 0.27% | `UNIUSDT` | 7/7 | sim |
| 24 | `kBONK` | 161 | 0.09% | 0.24% | `1000BONKUSDT` | 7/7 | sim |
| 25 | `SYRUP` | 257 | 0.09% | 0.21% | `SYRUPUSDT` | 7/7 | sim |
| 26 | `WLD` | 197 | 0.09% | 0.21% | `WLDUSDT` | 7/7 | sim |
| 27 | `kPEPE` | 118 | 0.08% | 0.21% | `1000PEPEUSDT` | 7/7 | sim |
| 28 | `LINK` | 295 | 0.06% | 0.16% | `LINKUSDT` | 7/7 | sim |
| 29 | `PURR` | 839 | 0.05% | 0.11% | — | 0/7 | não |
| 30 | `AVAX` | 94 | 0.04% | 0.09% | `AVAXUSDT` | 7/7 | sim |

Carteiras com fills na janela que teriam 50% ou mais do notional no universo (denominador: notional de todos os fills da carteira):

| Universo | Ativos | Carteiras | Com 50% ou mais | p25 da fração | Mediana | p75 |
|---|---|---|---|---|---|---|
| BTC, ETH e SOL | 3 | 54 | **6** | 0.0% | 0.0% | 21.4% |
| todos os listados com equivalente | 27 | 54 | **24** | 0.0% | 34.8% | 74.7% |

Listados só com equivalente em parte dos dias: ['GRAM'].

### Medidas auxiliares (só contagens)

| Medida | Valor |
|---|---|
| Carteiras analisadas (as duas amostras) | 120 |
| Maior número de fills de uma carteira na janela de seleção | 13,223 |
| Carteiras com mais de 10.000 / mais de 20.000 fills na janela | 5 / 0 |
| Maior número de fills de uma carteira no mesmo milissegundo | 256 |
| Carteiras com 20 ou mais fills no mesmo milissegundo | 43 |

### O que contradiz a spec

Este bloco confronta a RF-VER-05 com os requisitos 1.1 **propostos** e com o que a 1.0 assumia. Nada foi corrigido em spec.

**1. Nenhuma quebra de continuidade é explicada pela paginação da coleta; a causa continua sem identificação.**
Nas 7 carteiras com quebra, a recoleta com as fronteiras de página instrumentadas devolveu **exatamente os mesmos fills, na mesma ordem**, da primeira coleta (7 de 7). **Nenhuma das 100 quebras cai exatamente numa fronteira** e 16 atravessam uma. Nas 100 reconsultas do intervalo entre os dois fills quebrados (as 10 sorteadas e as 90 do complemento) **nenhuma devolveu um fill que faltava** na coleta. Pela regra de CA-05.1, o defeito não é nosso: a coleta não foi alterada, e as taxas de quebra seguem as de RF-VER-01 (0,82% dos pares na amostra de 20 e 0,16% na de 100). Isso é compatível com o que o texto da emenda diz ("a causa não foi identificada") e **não** o contradiz. As ressalvas estão em "O que não foi possível medir".

**2. A regra de 1 bp do notional passa em 98,3% dos episódios, mas elimina cerca de 18% das carteiras.**
Em 978 episódios fechados e íntegros, a razão entre a divergência de PnL e o notional tem mediana de 0,002 bps, p95 de 0,40, p99 de 1,41 e máximo de 3,26 bps; **1,7% dos episódios passam de 1 bp**, abaixo dos 5% que a própria emenda fixa para devolver RF-ING-04 CA-04.2 a emenda. Nos episódios de 2 fills a divergência é nula nos 51 (no máximo 9e-13 bps, ruído de ponto flutuante); nos de 3 a 4 fills, 2,0% passam de 1 bp; nos de 5 ou mais, 1,8%. Mas a regra emendada torna a **carteira** inelegível por divergência, e o limiar de 5% é por episódio: **7 das 39 carteiras com episódio fechado (17,9%)** têm ao menos um episódio acima de 1 bp. O D20 está sujeito a esta medida (a própria spec diz isso), e a medida o sustenta por episódio, mas o efeito por carteira é ordens de grandeza maior que a fração de episódios sugere.

**3. O funding existe para as 168 horas, mas o registro não cai na hora cheia.**
RF-ING-05 CA-05.1 pede "uma taxa de funding para cada hora cheia da janela". Em BTC, na semana de 2026-07-29 a 2026-08-05, a API devolveu **168 registros, exatamente um por hora**, com `coin`, `fundingRate`, `premium` e `time`. Porém `time` fica de **0 a 127 ms depois** do início da hora (o intervalo entre registros vai de 3.599,893 s a 3.600,123 s). Associar o registro à hora exige arredondar para baixo à hora; comparar `time` com o instante exato da hora cheia falharia em parte dos registros.

**4. Com o universo por regra, F9 passa em 24 de 54 carteiras, contra 6 de 54 com BTC, ETH e SOL.**
É o resultado que sustenta a direção da emenda (RF-SEL-08, D7). Com a lista dos 27 perpétuos do top 30 que têm equivalente na Binance em todos os 7 dias conferidos, a fração mediana do notional das carteiras no universo vai de 0,0% para 34,8% e o p75 de 21,4% para 74,7%. Quatro qualificações, que a decisão precisa ler junto:
- **Circularidade.** Os 30 ativos foram escolhidos pelo notional da própria amostra em que F9 foi medido, o que infla a cobertura por construção. O texto de RF-SEL-08 CA-08.1 também forma o universo com os fills das candidatas (e usa 20 ativos, não 30), então a circularidade não é só desta verificação.
- **"Equivalente" aqui é existência de arquivo diário**, não identidade de instrumento nem de escala de preço (`kBONK` e `kPEPE` foram associados a `1000BONKUSDT` e `1000PEPEUSDT` sem comparar preços).
- **Ativo popular sem equivalente:** `CASHCAT`, o 9º em notional (4.522 fills), e `PURR` não têm perpétuo na Binance; `GRAM` tem arquivo em 6 dos 7 dias. A condição (i) de RF-SEL-08 tira, portanto, ativo muito negociado.
- **Escala do critério (iii).** Só 6 dos 27 equivalentes têm 2.000 fills ou mais nesta amostra de 100 carteiras (`HYPE`, `BTC`, `ETH`, `ZEC`, `PUMP`, `LIT`), e `SOL` fica em 1.089. A condição é definida sobre 3.000 candidatas, então não dá para avaliá-la aqui.

**5. Até 256 fills compartilham o mesmo milissegundo numa carteira.**
43 das 120 carteiras têm ao menos um milissegundo com 20 ou mais fills. Isso sustenta a decisão da emenda de paginar com início inclusivo e deduplicação (RF-ING-02 CA-02.1): paginar a partir do milissegundo seguinte perderia fills sempre que uma página termina no meio de um milissegundo. O máximo observado (256) está bem abaixo do tamanho de página (2.000), e nem assim houve quebra de continuidade entre fills do mesmo milissegundo (0 de 100).

**6. O limiar de 20.000 fills por carteira (RF-ING-02 CA-02.3) não eliminaria ninguém nestas amostras.**
O maior número de fills na janela é 13.223, e 5 das 120 carteiras passam de 10.000. O limiar não é contradito, só não foi posto à prova por esta amostra.

**7. Defeito meu na verificação, corrigido e registrado.** A primeira versão da reconsulta de CA-05.1 somava as páginas sem deduplicar o milissegundo da fronteira, e o complemento chegou a mostrar "4 consultas devolveram fill que faltava", todas de uma carteira com 10.694 fills. Era contagem em duplicata, não fill ausente. A reconsulta passou a usar a mesma paginação e deduplicação da coleta, há teste de regressão que cai com o defeito, e os números acima são os da versão corrigida.

### O que não foi possível medir

1. **Fill omitido pela própria API.** A reconsulta usa o mesmo endpoint da coleta; ela só prova que a *coleta* não perdeu nada que a API devolve. Não há aqui uma segunda fonte independente (outro endpoint, assinatura de usuário) para saber se a API omite fills. A causa das quebras (fill ausente na resposta ou mudança de posição sem fill) continua sem resposta.
2. **Duas das 90 reconsultas do complemento não cobriram o intervalo todo.** São dois vãos de cerca de 20 dias, maiores que o que 2 páginas (≈ 4.000 fills) alcançam. Na parte coberta nada faltou, e a diferença de 1 e de 20 fills a menos nas duas devoluções é compatível com a segunda página cortar o último milissegundo no meio (há milissegundos com dezenas de fills), mas isso **não foi verificado**.
3. **Fronteiras da coleta original.** Elas não foram guardadas. As posições das fronteiras vêm da recoleta das 7 carteiras com quebra, idêntica à original, o que é evidência de reprodutibilidade e não registro. Na comparação por vão, as faixas altas têm poucas quebras (32 em 101 a 1000 posições, 8 acima de 1000): em 101 a 1000, 9 de 32 quebras (28%) atravessam uma fronteira contra 5 de 100 pares íntegros (5%), diferença que o vão médio maior das quebras poderia explicar, mas **isso não foi testado**.
4. **A origem da divergência de PnL.** Mede-se a divergência, não a causa. Há 39 carteiras com episódios fechados e íntegros; a regra de 5% é por episódio e o efeito por carteira (17,9%) vem de uma amostra pequena.
5. **Funding além de BTC e de uma semana.** O limite de registros por resposta e a ordenação não constam da documentação oficial e não foram descobertos (168 registros couberam numa resposta). Os valores das taxas não foram lidos: só formato, intervalo e cobertura.
6. **O universo por regra de verdade.** Esta amostra tem 100 carteiras (54 com fills na janela), contra um pool de 3.000 na emenda; as condições (iii) de volume mínimo e (iv) de proxy aprovado de RF-SEL-08 não foram avaliadas, e a equivalência com a Binance é só a existência do arquivo diário.
7. **A janela de avaliação.** Por regra, o conteúdo de fills a partir de 2026-09-01 não foi lido: toda consulta foi cortada no corte. O funding foi consultado só em semana da janela de seleção.
8. **Desempenho.** Nenhum PnL, retorno ou ranking de carteira foi calculado, impresso ou gravado. CA-05.2 devolve razões e contagens.

### Notas de método (RF-VER-05)

- **Execuções.** A RF-VER-05 rodou em 2026-10-06 por volta de 19:30 UTC; houve três execuções completas. A primeira reconsultou só as 10 quebras sorteadas (0 de 10 devolveram fill ausente); a segunda acrescentou o complemento e mostrou os 4 falsos positivos do defeito descrito acima; a terceira, com a correção, é a que alimenta esta seção. CA-05.2 e as medidas auxiliares foram recalculados depois, offline, sobre os mesmos dados.
- **O que é decisão do script.** O complemento de 90 reconsultas (a spec pede 10); a comparação por faixa de vão; as medidas auxiliares; a escolha de 7 dias da janela para a existência dos símbolos na Binance (os 5 sorteados, mais o primeiro e o último dia); a definição de "fronteira" (início de página nova na lista de fills da carteira, com a distinção entre "atravessa" e "exatamente na fronteira"); e o bloco de 7 dias do funding (sorteado com a semente entre os 8 blocos completos da janela).
- **Dados.** `data/verify/` (fora do git). Para as 7 carteiras recoletadas a janela de seleção foi paginada de novo; nada anterior à janela nem posterior ao corte foi lido.
- **Custo.** 227 requisições e 7.877 de peso, pico de 1.000 em 60 s contra o orçamento de 1.000, nenhum HTTP 429.
