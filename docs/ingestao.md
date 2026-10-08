# Ingestão — roteiro do marco M-B (Rota A)

O M-B traz para a máquina de análise tudo o que a seleção da Rota A vai ler da janela de seleção,
**2026-07-01 a 2026-08-31 (UTC)**:

| Passo | Comando | O que grava | Tempo estimado |
|---|---|---|---|
| 1 | `copylab ingest leaderboard` | Snapshot do leaderboard (bruto e derivado) e dos tamanhos de lote | segundos |
| 2 | `copylab ingest fills --route A --window selection --block 0` | Fills das 3.000 carteiras do bloco 0 do pool, com a cobertura de cada uma | **3 a 15 horas** |
| 3 | `copylab ingest market --route A --window selection` | Preço proxy por segundo e funding dos ativos candidatos e de BTC | 1 a 2 horas |
| 4 | edição de `config/collector_assets.toml` | Os candidatos que o coletor ainda não grava | minutos |

Tudo é somente leitura: nenhuma chave, nenhuma assinatura, nenhuma ordem (ADR-0001). A API de
informação é usada até **1.000 de peso por minuto** (`COPYLAB_WEIGHT_LIMIT_PER_MINUTE`), abaixo do
teto de 1.200 da corretora. O coletor, na outra máquina, usa WebSocket e não disputa esse orçamento.

**Nada de setembro.** Os comandos não aceitam datas: recebem rota e janela. A janela de seleção da
Rota A termina no corte, 2026-09-01 00:00 UTC, exclusive, e a de avaliação é recusada enquanto não
existir o congelamento (`preregistro/rota-a.json`). Não há como baixar setembro por engano com estes
comandos.

## 1. Preparar

Na máquina de análise, com o repositório atualizado:

```bash
git pull
make install
```

No `.env` da raiz (copie de `.env.example` se ainda não existir):

```bash
COPYLAB_DATA_DIR=/caminho/para/copylab-dados
COPYLAB_ENV=prod
```

- `COPYLAB_DATA_DIR` fora do repositório, com **pelo menos 5 GB livres**. O proxy por segundo de
  cerca de 21 ativos em 62 dias é a maior parte, da ordem de 1 GB pela conta de um dia de BTC
  (83 mil segundos); os fills ocupam menos. É estimativa: o número real aparece no disco no fim.
- `COPYLAB_ENV=prod` deixa o log em JSON, uma linha por evento, o que facilita filtrar. Em
  desenvolvimento o log sai colorido.

A máquina não pode dormir durante o passo 2. No macOS, rode os comandos com `caffeinate -i` na
frente, como abaixo; no Windows, siga a seção 6.2 de [`docs/coletor.md`](coletor.md).

Crie a pasta dos logs:

```bash
mkdir -p logs
```

## 2. Passo 1 — snapshot do leaderboard e dos lotes

```bash
uv run copylab ingest leaderboard
```

Leva segundos (o corpo do leaderboard tem cerca de 40 MB). A linha `ingest.snapshot` traz
`snapshot_ms`, o instante do snapshot. **Anote-o.** É ele que define o pool da Rota A.

Rode este passo **uma vez só**. Cada execução grava um snapshot novo, e nenhum é sobrescrito. Se
houver mais de um, os passos 2 e 3 param e pedem `--snapshot <ms>`, para a retomada nunca trocar
de pool no meio. Nesse caso, use sempre o mesmo `snapshot_ms` nos dois passos.

## 3. Passo 2 — fills do bloco 0 (o passo longo)

```bash
caffeinate -i uv run copylab ingest fills --route A --window selection --block 0 \
  >> logs/ingest-fills.log 2>&1; echo "saída: $?"
```

Em outro terminal, acompanhe:

```bash
tail -f logs/ingest-fills.log
```

Uma linha `ingest.fills.wallet` por carteira, com `progress` (por exemplo `412/3000`), o status, o
número de fills e de páginas, `elapsed_s` e `eta_s`, a estimativa do tempo que falta. **A estimativa
vale a partir de umas 100 carteiras:** o custo varia muito de uma carteira para outra.

**Quanto tempo.** Cada carteira custa 20 de peso se não operou na janela, e 20 mais 1 a cada 20
fills por página se operou. Na verificação de dados, quase metade das candidatas não tinha fill na
janela, e a média das ativas foi de 534 de peso: 3.000 carteiras dariam cerca de 893 mil de peso,
**perto de 15 horas** a 1.000 por minuto, o número dos requisitos. No teste de integração, as 5
primeiras do bloco custaram 280 de peso, o que daria menos de 3 horas. Planeje 15 horas; o `eta_s`
diz a verdade depois das primeiras centenas.

**Retomar depois de uma interrupção** (queda de rede, máquina desligada, `Ctrl+C`): rode o mesmo
comando de novo. A tabela `coverage` diz quais carteiras já foram ingeridas nesta janela; elas são
puladas sem nenhuma requisição, e a coleta recomeça da primeira sem cobertura. Uma carteira
interrompida no meio não grava nada e é coletada de novo do zero.

**Como saber que terminou.** O comando escreve `ingest.fills.done`, com `statuses` (quantas
carteiras `ok`, `frequência incompatível` e `falha`), o total de fills, os fills de perpétuo com
campo inválido, as divergências e `other_coins`, os nomes que não se encaixaram em nenhuma classe.
E a saída:

- `saída: 0` — todas as carteiras foram ingeridas. **Está completo.**
- `saída: 2` — a lista foi até o fim, mas alguma carteira falhou (a linha `ingest.fills.failed`
  diz quais). Rode o mesmo comando de novo: só as que falharam são coletadas.
- `saída: 1` — o comando parou antes de começar ou no meio, com a mensagem do motivo e do que fazer.

Para conferir depois, rode o comando mais uma vez: completo, ele termina em segundos, com todas as
3.000 carteiras puladas (`skipped`) e saída 0.

`frequência incompatível` é a carteira com mais de 20.000 fills na janela: a coleta dela para no
teto, nada é gravado, e ela fica fora da seleção (RF-ING-02 CA-02.3). Não é erro.

## 4. Passo 3 — proxy e funding dos ativos candidatos

Só depois do passo 2 completo, porque a ordem dos ativos sai dos fills de todas as candidatas:

```bash
caffeinate -i uv run copylab ingest market --route A --window selection \
  >> logs/ingest-market.log 2>&1; echo "saída: $?"
```

O comando ordena os perpétuos do primeiro dex pelo notional negociado pelas candidatas e, nessa
ordem, confere se cada um tem o perpétuo equivalente na Binance com arquivo em todos os 62 dias. Dos
que têm ao menos 2.000 fills de candidatas, baixa o proxy inteiro, um arquivo por dia, confere o
checksum, reduz a uma linha por segundo e apaga o arquivo bruto; dos demais, só confere que os
arquivos existem. Para quando 20 ativos cumprem a condição. BTC entra sempre. Depois grava o funding,
hora a hora, dos ativos baixados.

Acompanhe com `tail -f logs/ingest-market.log`: uma linha `ingest.market.asset` por ativo visitado
e uma `ingest.proxy.day` por dia baixado. Um dia de BTC tem cerca de 14 MB e levou 6,5 s no teste
de integração; os outros ativos são menores. Conte **1 a 2 horas**, quase tudo download.

**Retomar:** o mesmo comando. Dia de proxy já gravado e funding já gravado são pulados.

**Se faltar carteira:** se o passo 2 não terminou, o comando sai com 1 e diz qual comando
`ingest fills` rodar.

**Como saber que terminou:** `ingest.market.done`, com `meeting_condition_i` (os ativos que têm
arquivo em todos os dias, em ordem de notional), `proxied` (os que tiveram o proxy baixado: os
candidatos ao universo e BTC) e `funding`. Saída 0 é completo; saída 2 tem a lista de falhas em
`ingest.market.failure` (checksum divergente, rede esgotada, hora de funding faltante): rode o mesmo
comando de novo.

## 5. Passo 4 — acrescentar ao coletor os candidatos que faltam

Se algum ativo de `proxied` não está na lista do coletor, o passo 3 escreve:

```text
ingest.market.not_in_collector  coins=[...]  action=acrescente-os a config/collector_assets.toml ...
```

Esses ativos precisam de 3 dias de livro gravado antes da medida de custo (M-C), então quanto antes
entrarem, melhor:

1. Aqui, na máquina de análise, acrescente os nomes ao fim da lista `coins` de
   [`config/collector_assets.toml`](../config/collector_assets.toml), com a grafia da Hyperliquid
   (`kPEPE`, não `1000PEPE`). Rode `make check` e commite só esse arquivo, dizendo por quê
   ("ativos candidatos da Rota A que o coletor não gravava").
2. `git pull --rebase` e `git push`.
3. Na máquina do coletor, siga a seção 10 de [`docs/coletor.md`](coletor.md): `git pull`, e
   reinicie a tarefa do coletor para ele ler a lista nova. `collect status` deve passar a mostrar
   os ativos novos.

Se a mensagem não aparecer, todos os candidatos já estão na lista.

## 6. Conferência do marco

O M-B está feito quando:

- [ ] `ingest fills ... --block 0` sai com 0, e uma nova execução pula as 3.000 carteiras.
- [ ] `ingest market ...` sai com 0.
- [ ] Os candidatos que faltavam entraram na lista do coletor (passo 4), se havia algum.
- [ ] O resumo do passo 2 (`statuses`, `invalid_perp_fills`, `other_coins`) e o do passo 3
      (`meeting_condition_i`, `proxied`) foram copiados para o `HANDOFF.md`, com o `snapshot_ms`.

Nada de setembro foi baixado: os dois comandos só aceitam a janela de seleção da Rota A, que termina
em 2026-09-01 exclusive, e o teste de integração confere que nenhuma consulta passa do corte.

## Problemas

| Sintoma | O que fazer |
|---|---|
| `COPYLAB_DATA_DIR não está definido` | Falta o `.env` da seção 1 |
| `Não há snapshot do leaderboard` | Rode o passo 1 |
| `Há N snapshots do leaderboard` | Passe `--snapshot <ms>` com o do passo 1, nos passos 2 e 3 |
| `ingest.api.retry` de vez em quando | Normal: rede ou 429, com espera crescente. Só preocupa se `tentativas esgotadas` aparecer em sequência |
| `tentativas esgotadas` em muitas carteiras seguidas | A rede ou a API caiu. Pare com `Ctrl+C`, espere, e rode de novo: retoma |
| `mais de 2000 fills em ...` numa carteira | Mais de uma página no mesmo milissegundo, que a paginação por instante não atravessa. A carteira fica com `falha`; anote o endereço no `HANDOFF.md` |
| `Recusado: a janela de avaliação ...` | É a guarda: avaliação só depois do congelamento |
| A máquina dormiu | Ao acordar, o comando continua ou falha a carteira da vez; rode de novo para retomar |
