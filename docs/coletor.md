# Coletor — roteiro de operação (Windows)

O coletor grava, sem parar, o livro de ofertas e os negócios dos ativos de
[`config/collector_assets.toml`](../config/collector_assets.toml), pelo WebSocket público da
Hyperliquid. Tudo o que ele deixa de gravar não se recupera, então ele roda na máquina secundária,
que fica ligada o tempo todo (D10). Este roteiro é para essa máquina, com **Windows nativo**, e vai
do zero até o coletor gravando sozinho e o status mostrando cobertura.

São três peças:

| Comando | O que faz | Quando roda |
|---|---|---|
| `copylab collect` | Grava até ser parado. Reconecta sozinho depois de queda de rede | Sempre, por uma tarefa agendada |
| `copylab collect compact` | Converte os segmentos de cada dia encerrado em tabelas, confere as contagens e apaga os segmentos | Uma vez por dia, depois da meia-noite UTC |
| `copylab collect status` | Cobertura por ativo, latência e projeção de disco. Só lê arquivos | Quando quiser conferir; no mínimo, ao fim do primeiro dia |

Somente leitura: nenhuma chave, nenhuma assinatura de usuário, nenhuma ordem (ADR-0001).

Os comandos são de PowerShell. Os caminhos `C:\copylab` (o código) e `C:/copylab-dados` (os dados)
são exemplos: troque os dois em todo o roteiro se usar outros.

## 1. Pré-requisitos

- **Git:** `winget install --id Git.Git -e`.
- **uv** (instala o Python 3.12 sozinho):

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  Feche e abra o terminal depois, para o `uv` entrar no `PATH`. Com esse instalador ele fica em
  `%USERPROFILE%\.local\bin\uv.exe`; instalado por `winget install --id astral-sh.uv -e`, fica em
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe`. As tarefas da seção 6 descobrem o
  caminho real com `(Get-Command uv).Source`, então funcionam nos dois casos.
- **Disco:** pelo menos 30 GB livres no volume dos dados (RNF-10).
- **Relógio sincronizado.** Em Configurações > Hora e idioma > Data e hora: "Definir horário
  automaticamente" ligado, e "Sincronizar agora". O instante de recebimento vem do relógio da
  máquina e entra na medida de latência. As lacunas são medidas no relógio da corretora, então um
  relógio errado não cria nem esconde lacuna, mas distorce a latência.
- **Rede:** conexão de saída para `wss://api.hyperliquid.xyz/ws` (porta 443).

## 2. Instalar

```powershell
git clone https://github.com/colletpedro/copylab.git C:\copylab
```

```powershell
cd C:\copylab; uv sync
```

## 3. Configurar o diretório de dados

```powershell
Copy-Item .env.example .env; notepad .env
```

No `.env`, acrescente (com barra normal no caminho, que dispensa escape):

```
COPYLAB_DATA_DIR=C:/copylab-dados
```

E troque `COPYLAB_ENV=dev` por `COPYLAB_ENV=prod`, para o log sair em JSON, uma linha por evento.
Crie a pasta dos logs das tarefas:

```powershell
New-Item -ItemType Directory -Force C:\copylab-dados\logs
```

Os comandos rodam de dentro de `C:\copylab`, onde estão o `.env`, a lista de ativos e o arquivo de
parâmetros.

## 4. Teste de dois minutos

```powershell
uv run copylab collect --duration-seconds 120
```

```powershell
uv run copylab collect status
```

O status deve mostrar uma linha `collector.status.asset` por ativo, com `coverage_pct` perto de 100,
e uma linha `collector.status.disk`. Com dois minutos, a projeção de disco é grosseira; a que vale é
a do fim do primeiro dia (seção 8).

## 5. Rodar à mão (para testar)

```powershell
uv run copylab collect
```

Grava até `Ctrl+C`, que fecha os segmentos com calma. Se o processo for morto, ou a máquina
desligar, perde-se no máximo o que não tinha sido descarregado (5 s,
`COPYLAB_COLLECTOR_FLUSH_SECONDS`): ao voltar, o coletor fecha os segmentos interrompidos até o
último bloco íntegro e segue em segmentos novos. Só um gravador roda por diretório de dados; um
segundo é recusado com "Outro gravador já está rodando". Pare o teste antes da seção 6.

## 6. Manter de pé, impedir a suspensão e agendar a compactação

Num PowerShell **como administrador**, dentro de `C:\copylab`.

### 6.1 O coletor como tarefa que sobe com a máquina

A tarefa sobe na inicialização, sem precisar de login, e um segundo gatilho a dispara a cada minuto.
Com `-MultipleInstances IgnoreNew`, o disparo é ignorado enquanto o coletor está de pé e religa o
processo se ele caiu.

> **Não use `-RestartCount`/`-RestartInterval` para isso.** Medido no Windows 11: matar o processo à
> força deixou a tarefa em `Ready` (`LastTaskResult` 1) por mais de 2 minutos, sem reiniciar, mesmo
> com `-RestartCount 999`. O reinício por falha do Agendador não cobre processo encerrado. Com o
> gatilho repetitivo abaixo, o coletor voltou em 53 s.

```powershell
$uv = (Get-Command uv).Source
$acao = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d C:\copylab && `"$uv`" run copylab collect >> C:\copylab-dados\logs\coletor.log 2>&1"
$gatilhoBoot = New-ScheduledTaskTrigger -AtStartup
$gatilhoRepete = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$quem = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U
$regras = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "copylab-coletor" -Action $acao -Trigger @($gatilhoBoot, $gatilhoRepete) -Principal $quem -Settings $regras
Start-ScheduledTask -TaskName "copylab-coletor"
```

O processo da tarefa pertence a outro token: um terminal comum recebe "Acesso negado" ao tentar
encerrá-lo. Para testar a queda, use um PowerShell como administrador:
`taskkill /F /T /PID <pid do uv>`.

Conferir que está rodando e ver o log:

```powershell
Get-ScheduledTaskInfo -TaskName "copylab-coletor"; Get-Content C:\copylab-dados\logs\coletor.log -Tail 5
```

A linha `collector.event` com `"kind": "connect"` diz que ele está gravando.

### 6.2 Impedir a suspensão

Na tomada, a máquina não suspende, não hiberna e não desliga o disco:

```powershell
powercfg /change standby-timeout-ac 0; powercfg /change hibernate-timeout-ac 0; powercfg /change disk-timeout-ac 0
```

Se for um notebook, fechar a tampa e apertar o botão de energia também não podem suspender. Na
máquina testada, `powercfg /q` com o apelido `LIDACTION` não devolveu nada; os GUIDs abaixo foram
aceitos pelo `powercfg` (saída 0) sem depender do apelido:

```powershell
$b = '4f971e89-eebd-4455-a8de-9e59040e7347'
powercfg /setacvalueindex SCHEME_CURRENT $b 5ca83367-6e45-459f-a27b-476b1d01c936 0   # tampa
powercfg /setacvalueindex SCHEME_CURRENT $b 7648efa3-dd9c-4e3e-b566-50f929386280 0   # botão de energia
powercfg /setactive SCHEME_CURRENT
```

**Este passo não é opcional em notebook com "espera moderna"** (`powercfg /a` lista "Espera (S0
Ocioso com Baixo Consumo de Energia)"). Medido: com `standby-timeout-ac` em 0, a máquina entrou em
espera mesmo assim, o coletor ficou congelado por horas e a cobertura caiu para 2,3% em 11 horas
(`Get-WinEvent -LogName System`, eventos 506/507 do Kernel-Power, mostram quando dormiu e acordou).
Depois de aplicar, confira no status (seção 8) que `gaps` para de crescer.

O Windows Update ainda reinicia a máquina de vez em quando. Em Configurações > Windows Update >
Opções avançadas, ajuste o "Horário ativo" para reduzir isso. Um reinício vira uma lacuna registrada,
e a tarefa da seção 6.1 religa o coletor na subida.

### 6.3 Compactação diária, às 00:15 UTC

O horário é calculado em UTC e convertido para o fuso da máquina (em Brasília, 21:15):

```powershell
$uv = (Get-Command uv).Source
$acao = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c cd /d C:\copylab && `"$uv`" run copylab collect compact >> C:\copylab-dados\logs\compactacao.log 2>&1"
$hora = (Get-Date).ToUniversalTime().Date.AddMinutes(15).ToLocalTime()
$gatilho = New-ScheduledTaskTrigger -Daily -At $hora
$quem = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U
$regras = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "copylab-compactacao" -Action $acao -Trigger $gatilho -Principal $quem -Settings $regras
```

`-StartWhenAvailable` faz a compactação rodar assim que a máquina voltar, se ela estava desligada no
horário.

### 6.4 Opcional: tirar a pasta de dados da varredura do antivírus

O coletor fecha 82 segmentos por hora, trocando o nome de cada um. Se o Microsoft Defender ou o
indexador estiverem lendo o arquivo naquele instante, o Windows recusa a troca; o coletor tenta de
novo por até 2 s e registra `collector.segment_rename_retry`. Se essa linha aparecer com frequência
no log, exclua a pasta de dados da verificação em tempo real (é uma decisão de segurança sua: a pasta
só tem dado público de mercado):

```powershell
Add-MpPreference -ExclusionPath "C:\copylab-dados"
```

## 7. Compactação à mão

```powershell
uv run copylab collect compact
```

Converte os segmentos de cada dia UTC já encerrado nas tabelas `bbo`, `book` e `trades`, monta a
tabela `gaps` e só apaga os segmentos depois de conferir que cada mensagem virou linha. Pode rodar
quantas vezes quiser: um dia já compactado não é refeito, e uma compactação interrompida é refeita
igual. O dia de hoje nunca é compactado. Um dia com segmento deixado aberto por uma queda espera o
coletor subir e fechá-lo. Para um dia específico: `uv run copylab collect compact --day 2026-10-07`.

## 8. Conferir o status

```powershell
uv run copylab collect status
```

| Linha | Campo | O que olhar |
|---|---|---|
| `collector.status.asset` | `coverage_pct` | Fração do tempo sem lacuna desde o primeiro livro gravado do ativo. A Rota B exige 95% por ativo (§7.2). Com o coletor parado, cai: o silêncio desde a última mensagem conta como lacuna |
| | `gaps`, `gap_s` | Lacunas e o tempo somado delas. Lacuna é desconexão ou mais de 10 s sem livro |
| | `latency_p50_ms` a `p99_ms` | Recebimento menos o instante da corretora, nos negócios. Mistura rede e diferença de relógio |
| `collector.status.latency` | | O mesmo para todos os ativos, ao lado da grade de Δ (1, 5 e 30 s) |
| `collector.status.disk` | `projected_gb`, `within_budget` | Projeção linear do disco para 45 dias contra o orçamento de 30 GB |

**No fim do primeiro dia (marco M-A do plano):** depois da primeira compactação (seção 6.3, ou à mão
na seção 7), anote `projected_gb`. Se passar de 30 GB, a decisão volta para a conversa de arquitetura
antes de qualquer outra coisa (risco 9 do design). No teste de dois minutos em outra máquina, a
projeção deu 28,5 GB: perto do orçamento, mas grosseira demais para decidir.

## 9. Copiar as tabelas para a máquina de análise

Copie só o que a compactação produziu, nunca segmentos em escrita, e pule os temporários de escrita
(`.*.tmp`). Para uma pasta compartilhada da máquina de análise:

```powershell
foreach ($t in "bbo", "book", "trades", "gaps") { robocopy "C:\copylab-dados\$t" "\\maquina-de-analise\copylab-dados\$t" /E /XF .*.tmp }
```

As tabelas de dias encerrados não mudam mais, então copiar de novo só transfere os dias novos. A
conferência da cópia pelo hash de conteúdo (design §3.4) chega com a leitura do livro pelo simulador
(T-080).

## 10. Mudar a lista de ativos ou atualizar o código

```powershell
cd C:\copylab; git pull; uv sync
```

```powershell
Stop-ScheduledTask -TaskName "copylab-coletor"; Start-ScheduledTask -TaskName "copylab-coletor"
```

Parar a tarefa mata o processo: perde-se no máximo o que não tinha sido descarregado, e a subida
seguinte fecha o segmento interrompido. A lista de ativos só muda por commit (decisão 12 do design).

## Problemas

| Mensagem | Causa | O que fazer |
|---|---|---|
| `COPYLAB_DATA_DIR não está definido` | `.env` ausente, ou o comando rodou fora de `C:\copylab` | Seção 3 |
| `Outro gravador já está rodando` | A tarefa já está gravando sobre o mesmo diretório | Pare a tarefa antes de rodar à mão |
| `collector.segment_recovered` | O processo anterior foi morto no meio de uma escrita | Nada: o segmento foi fechado até o último bloco íntegro |
| `collector.segment_rename_retry` | Outro processo segurava o arquivo na hora de fechar | Nada, se for raro; se for frequente, seção 6.4 |
| `collector.compact.skipped_open_segment` | Segmento de um dia encerrado ainda aberto | Confira se a tarefa do coletor está rodando: ao subir, ele fecha o segmento |
| `collector.event`, `"kind": "disconnect"` | Queda de rede ou da corretora | Nada: ele reconecta sozinho, com espera crescente até 60 s |
