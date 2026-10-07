# Coletor — roteiro de operação

O coletor grava, sem parar, o livro de ofertas e os negócios dos ativos de
[`config/collector_assets.toml`](../config/collector_assets.toml), pelo WebSocket público da
Hyperliquid. Tudo o que ele deixa de gravar não se recupera, então ele roda numa máquina que
fica ligada o tempo todo (D10). Este roteiro vai do zero até o coletor gravando e o status
mostrando cobertura.

São três peças:

| Comando | O que faz | Quando roda |
|---|---|---|
| `copylab collect` | Grava até ser parado. Reconecta sozinho depois de queda de rede | Sempre |
| `copylab collect compact` | Converte os segmentos de cada dia encerrado em tabelas, confere as contagens e apaga os segmentos | Uma vez por dia, depois da meia-noite UTC |
| `copylab collect status` | Cobertura por ativo, latência e projeção de disco. Só lê arquivos | Quando quiser conferir; no mínimo, ao fim do primeiro dia |

Somente leitura: nenhuma chave, nenhuma assinatura de usuário, nenhuma ordem (ADR-0001).

> **Pendente: a seção 6 depende do sistema operacional da máquina secundária**, que ainda não
> foi informado. As seções 1 a 5 e 7 a 10 valem para macOS, Linux e WSL. No Windows nativo, o
> coletor não roda como está: ele usa `fcntl` (a trava que impede dois gravadores) e os sinais
> `SIGINT` e `SIGTERM`, que são de sistemas POSIX.

## 1. Pré-requisitos

- `git` e [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
  O `uv` instala o Python 3.12 sozinho.
- **Disco:** pelo menos 30 GB livres no volume do diretório de dados (RNF-10).
- **Relógio sincronizado** (NTP ligado). O instante de recebimento vem do relógio da máquina e
  entra na medida de latência. As lacunas são medidas no relógio da corretora, então um
  relógio errado não cria nem esconde lacuna, mas distorce a latência e a projeção de disco.
- **Rede:** conexão de saída para `wss://api.hyperliquid.xyz/ws` (porta 443).

## 2. Instalar

```bash
git clone https://github.com/colletpedro/copylab.git
```

```bash
cd copylab && make install
```

## 3. Configurar o diretório de dados

O diretório de dados fica fora do git e guarda os segmentos brutos e as tabelas. Use um
caminho absoluto, num disco com espaço:

```bash
cp .env.example .env
```

No `.env`, defina:

```
COPYLAB_DATA_DIR=/caminho/absoluto/para/copylab-dados
COPYLAB_ENV=prod
```

`COPYLAB_ENV=prod` faz o log sair em JSON, uma linha por evento, que é o formato para um
processo que roda sozinho. Os comandos rodam de dentro da pasta `copylab/`, onde estão o `.env`,
a lista de ativos e o arquivo de parâmetros.

## 4. Teste de dois minutos

Antes de deixar rodando, grave dois minutos e confira:

```bash
uv run copylab collect --duration-seconds 120
```

```bash
uv run copylab collect status
```

O status deve mostrar uma linha `collector.status.asset` por ativo, com `coverage_pct` perto
de 100, e uma linha `collector.status.disk`. Com dois minutos, a projeção de disco é grosseira;
a que vale é a do fim do primeiro dia (seção 8).

## 5. Ligar

```bash
uv run copylab collect
```

O processo grava até receber `Ctrl+C` (`SIGINT`) ou `SIGTERM`. Ao parar, ele descarrega e fecha
os segmentos abertos. Se a máquina desligar no meio, perde-se no máximo o que não tinha sido
descarregado (5 s, `COPYLAB_COLLECTOR_FLUSH_SECONDS`). Ao voltar, o coletor fecha os segmentos
interrompidos até o último bloco íntegro e segue gravando em segmentos novos.

Só um gravador pode rodar por diretório de dados. Um segundo é recusado com
"Outro gravador já está rodando".

## 6. Manter de pé, impedir a suspensão e agendar a compactação

**Pendente: depende do sistema operacional da máquina secundária.** Esta seção vai dizer, para
esse sistema:

- como fazer `uv run copylab collect` subir sozinho depois de um reinício e voltar se cair;
- como impedir que a máquina suspenda ou desligue o disco;
- como agendar `uv run copylab collect compact` uma vez por dia, depois de 00:10 UTC;
- onde fica o log do processo.

## 7. Compactação diária

```bash
uv run copylab collect compact
```

Converte os segmentos de cada dia UTC já encerrado nas tabelas `bbo`, `book` e `trades`, monta a
tabela `gaps` e só apaga os segmentos depois de conferir que cada mensagem virou linha. Pode rodar
quantas vezes quiser: um dia já compactado não é refeito, e uma compactação interrompida é refeita
igual. O dia de hoje nunca é compactado, porque ainda está sendo gravado. Um dia com segmento
deixado aberto por uma queda espera o coletor reiniciar e fechá-lo.

Para um dia específico: `uv run copylab collect compact --day 2026-10-07`.

## 8. Conferir o status

```bash
uv run copylab collect status
```

| Linha | Campo | O que olhar |
|---|---|---|
| `collector.status.asset` | `coverage_pct` | Fração do tempo sem lacuna desde o primeiro livro gravado do ativo. A Rota B exige 95% por ativo (§7.2) |
| | `gaps`, `gap_s` | Lacunas e o tempo somado delas. Lacuna é desconexão ou mais de 10 s sem livro |
| | `latency_p50_ms` a `p99_ms` | Recebimento menos o instante da corretora, nos negócios. Mistura rede e diferença de relógio |
| `collector.status.latency` | | O mesmo para todos os ativos, ao lado da grade de Δ (1, 5 e 30 s) |
| `collector.status.disk` | `projected_gb`, `within_budget` | Projeção linear do disco para 45 dias contra o orçamento de 30 GB |

**No fim do primeiro dia (marco M-A do plano):** anote `projected_gb`. Se passar de 30 GB, a
decisão volta para a conversa de arquitetura antes de qualquer outra coisa (risco 9 do design).
A projeção mede o que está no disco: antes da primeira compactação são os segmentos gzip, depois
dela, as tabelas. Confira de novo depois da primeira compactação.

## 9. Copiar as tabelas para a máquina de análise

Copie só o que a compactação produziu, nunca segmentos em escrita:

```bash
rsync -a --checksum /caminho/absoluto/para/copylab-dados/{bbo,book,trades,gaps} usuario@maquina-de-analise:/caminho/dos-dados/
```

As tabelas de dias encerrados não mudam mais, então copiar de novo só transfere os dias novos. A
conferência da cópia pelo hash de conteúdo (design §3.4) chega com a leitura do livro pelo
simulador (T-080); até lá, o `--checksum` do `rsync` confere os bytes.

## 10. Mudar a lista de ativos ou atualizar o código

```bash
git pull && make install
```

Depois, reinicie o coletor (pare e ligue de novo). A lista de ativos só muda por commit
(decisão 12 do design). Um ativo novo começa a ter cobertura a partir do reinício.

## Problemas

| Mensagem | Causa | O que fazer |
|---|---|---|
| `COPYLAB_DATA_DIR não está definido` | `.env` ausente, ou o comando rodou fora da pasta `copylab/` | Seção 3 |
| `Outro gravador já está rodando` | Já existe um `collect` sobre o mesmo diretório | Pare o outro, ou use outro diretório |
| `collector.segment_recovered` | O processo anterior caiu no meio de uma escrita | Nada: o segmento foi fechado até o último bloco íntegro |
| `collector.compact.skipped_open_segment` | Segmento de um dia encerrado ainda aberto | Ligue o coletor: ao subir, ele fecha o segmento |
| `collector.event kind=disconnect` | Queda de rede ou da corretora | Nada: ele reconecta sozinho, com espera crescente até 60 s |
