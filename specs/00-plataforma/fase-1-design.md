# Fase 1 (estudo de simulação) — Design técnico

**Status:** em revisão — gate 2 pendente
**Versão:** 0.2
**Data:** 2026-10-07
**Requisitos:** `fase-1-requirements.md`, versão 1.3
**Próximo gate:** `specs/00-plataforma/fase-1-tasks.md` (não iniciado)

> Este documento diz **como** a fase é construída. O que ela faz está nos requisitos, e as decisões caras de reverter estão nos ADRs 0001 a 0008. Onde este texto e os requisitos divergirem, valem os requisitos, e este texto está errado.

---

## 1. Visão geral

A fase tem dois caminhos de dados que se encontram no simulador.

```
 API da Hyperliquid ──► ingestão ──► fills, funding, lotes ─┐
 arquivo da Binance ──► ingestão ──► preço proxy por segundo ├─► livro-razão ─► seleção ─► congelamento
 WebSocket ───────────► coletor ───► livro, negócios, lacunas┘        do líder        │            │
                                                                                      ▼            ▼
                                                                                  simulador ◄── parâmetros
                                                                                      │
                                                                                      ▼
                                                                    analytics ─► relatório, veredito, gate
```

O simulador é um só. A Rota A e a Rota B diferem apenas na fonte de preço que ele recebe: a série por segundo da Binance ou o livro gravado. Tudo o mais (espelhamento, custos, funding, contabilidade, métricas) é o mesmo código.

A seleção roda o mesmo simulador, sobre a janela de seleção, para ordenar as carteiras. Por isso o isolamento temporal é garantido na camada de leitura de dados, e não em cada chamador.

## 2. Arquitetura

### 2.1 Pacotes e regra de dependência

```
copylab/
├── timeutil.py     # único módulo que converte instante em dia ou hora
├── clock.py        # único módulo que lê o relógio da máquina
├── params.py       # parâmetros pré-registrados, carregados de arquivo versionado
├── ports.py        # protocolo de leitura de dados e o repositório limitado pelo corte
├── storage/        # diretório de dados, tabelas, leitura e escrita, hash de conteúdo
├── ingestion/      # provedor da API, orçamento de peso, paginação, proxy da Binance
├── collector/      # gravador de WebSocket, lacunas, compactação, status
├── leader/         # livro-razão do líder: posições, eventos, episódios, conferência de PnL
├── selection/      # pool, universo, filtros, referência de exposição, ranking, congelamento
├── sim/            # fontes de preço, espelhamento, execução, contabilidade, laço
├── analytics/      # métricas, benchmarks, decomposição, janela efetiva, veredito, gate, relatório
└── cli.py
```

As setas apontam para dentro:

- `leader`, `selection`, `sim` e `analytics` são lógica pura. Não importam `storage`, `ingestion`, `collector`, `clock`, rede nem arquivo. Leem dados pelo protocolo de `ports`, sem saber de onde vêm, e devolvem objetos, texto ou bytes. O gráfico também: `analytics/plot.py` devolve a imagem em bytes.
- Só `storage` conhece o diretório de dados e o formato dos arquivos (ADR-0006). `storage` implementa o protocolo de `ports`. `ingestion` e `collector` entregam tabelas a `storage` e não gravam por conta própria.
- Só `timeutil` importa `datetime`. Só `clock` importa `time`, e só `collector`, `ingestion` e `cli` importam `clock`. `asyncio` é permitido só no coletor.
- `sim` não conhece rotas: conhece o protocolo `PriceSource`.
- `cli` monta as peças, e é ela que grava congelamentos e relatórios.

Quatro testes de arquitetura, por AST, sustentam isso: somente leitura (RNF-09, já existente), fronteira de tempo (RNF-07), isolamento do armazenamento (ADR-0006) e pureza dos pacotes de lógica.

### 2.2 Dependências externas

| Biblioteca | Para quê | Onde pode ser importada |
|---|---|---|
| `polars` | Tabelas e arquivos Parquet | `storage`, `ingestion`, a compactação do `collector`, e como tipo de tabela nas bordas de `leader` e `selection` |
| `numpy` | Vetores de preço e busca binária no simulador | `sim`, `analytics` |
| `httpx` | API de informação e arquivos da Binance | `ingestion` |
| `websockets` | Coletor | `collector` |
| `matplotlib` | Gráfico | `analytics/plot.py` |
| `tomllib` (biblioteca padrão) | Arquivo de parâmetros e lista do coletor | `params.py`, `collector` |

Nenhum SDK da Hyperliquid entra: o provedor usa `httpx` direto, o que mantém o teste de somente leitura trivial.

Não há serviço para subir: nenhum `docker-compose` e nenhum banco (ADR-0006).

---

## 3. Componentes e contratos

### 3.1 Tempo (`copylab.timeutil` e `copylab.clock`)

```python
Ms = NewType("Ms", int)                # milissegundos UTC desde a época

def utc_day(t: Ms) -> int: ...         # dias inteiros desde a época
def day_start(day: int) -> Ms: ...
def hour_floor(t: Ms) -> Ms: ...       # início da hora que contém t
def second_of(t: Ms) -> int: ...       # segundos inteiros desde a época
def iso(t: Ms) -> str: ...             # só para log e relatório
def parse_utc_date(text: str) -> Ms: ...   # "2026-09-01" vira a meia-noite UTC desse dia
def from_date(d: date) -> Ms: ...      # para as datas que o TOML entrega
```

Todo timestamp cruza o sistema como `Ms`. A API já entrega milissegundos. Nos arquivos da Binance, a ingestão confere a ordem de grandeza do timestamp na borda e falha se ele não for milissegundo. Janelas são semiabertas, `[início, fim)`, em todo lugar.

`clock` tem três funções: `now() -> Ms`, `monotonic() -> float` e `sleep(segundos)`. São a única leitura do relógio da máquina. Servem para carimbar o que entra, no coletor e na ingestão, e para o orçamento de peso esperar. Nenhum cálculo de seleção, simulação ou métrica depende delas.

### 3.2 Armazenamento (`copylab.storage`)

Ver ADR-0006. O diretório de dados vem de `COPYLAB_DATA_DIR` e fica fora do git.

| Tabela | Partição | Colunas | Origem |
|---|---|---|---|
| `raw/leaderboard` | instante do snapshot | corpo bruto comprimido e sha256 | API |
| `leaderboard` | instante do snapshot | `address`, `account_value` | derivada do bruto; os campos de desempenho não são copiados |
| `fills` | endereço | `seq`, `time_ms`, `coin`, `kind`, `px`, `sz`, `side`, `start_position`, `dir`, `crossed`, `closed_pnl`, `fee`, `tid`, `oid`, `twap_id`, `liquidated_user` | API |
| `coverage` | endereço | `start_ms`, `end_ms`, `ingested_at_ms`, `n_fills`, `status`, `content_hash` | ingestão |
| `roles` | instante da coleta | `address`, `role` | API |
| `funding` | ativo | `hour_ms`, `time_ms`, `rate`, `premium` | API |
| `meta` | instante da coleta | `coin`, `sz_decimals` | API |
| `proxy` | ativo, dia | `second`, `low`, `high`, `last`, `n_trades` | Binance |
| `bbo` | ativo, dia | `time_ms`, `recv_ms`, `bid_px`, `bid_sz`, `ask_px`, `ask_sz` | coletor |
| `book` | ativo, dia | `time_ms`, `recv_ms`, e 5 níveis de preço e tamanho por lado | coletor |
| `trades` | ativo, dia | `time_ms`, `recv_ms`, `px`, `sz`, `side`, `buyer`, `seller`, `tid` | coletor |
| `gaps` | ativo | `start_ms`, `end_ms`, `reason` | coletor |
| `divergences` | endereço | `time_ms`, `tid`, `field`, `old`, `new`, `detected_at_ms` | ingestão |

`seq` é a posição do fill na ordem em que a API o devolveu para aquele endereço. Ela desempata fills do mesmo milissegundo (a verificação encontrou até 256) e é o que a conferência de continuidade percorre. `status`, em `coverage`, é `ok`, `frequência incompatível` ou `falha`.

```python
class Repository(Protocol):
    def leaderboard(self, snapshot: Ms) -> pl.DataFrame: ...
    def meta(self, snapshot: Ms) -> pl.DataFrame: ...
    def roles(self, snapshot: Ms) -> pl.DataFrame: ...
    def coverage(self, address: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def fills(self, address: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def funding(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def proxy(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def bbo(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def book(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def gaps(self, coin: str, start: Ms, end: Ms) -> pl.DataFrame: ...
    def content_hash(self, table: str, keys: Sequence[str], start: Ms, end: Ms) -> str: ...

class BoundedRepository:
    """Envolve um Repository e levanta LookaheadError em qualquer leitura com fim > cutoff."""
    def __init__(self, inner: Repository, cutoff: Ms) -> None: ...
```

O protocolo é só de leitura. `Repository` e `BoundedRepository` moram em `copylab.ports`, e `storage` os implementa. A escrita fica numa interface separada, `Writer`, que só `ingestion`, `collector` e a CLI recebem.

A seleção só recebe um `BoundedRepository`. É isso que prova RF-SEL-01 CA-01.1 por construção. Do leaderboard, a tabela derivada não tem colunas de desempenho, e o leitor do corpo bruto não é exposto no protocolo: RF-SEL-01 CA-01.3 também vale por construção. `LookaheadError` entra em `copylab.exceptions`, derivada de `CopylabError`.

**O que fica fora do corte.** O corte vale para fills, cobertura, funding, proxy e livro. Três leituras ficam fora, e as três são declaradas: o leaderboard, os tamanhos de lote e o tipo de conta. Elas são coletadas hoje, depois do corte da Rota A, porque a API não as devolve para uma data passada. Nenhuma traz desempenho. A seleção usa o snapshot mais recente de cada uma, e o instante e o hash dos três vão para o congelamento, de modo que a avaliação use exatamente os mesmos.

**Hash de conteúdo.** Calculado dos valores, em ordem canônica (chave da tabela), com os números lidos como padrões de bits de 64 bits e os textos como UTF-8 com prefixo de tamanho. Zero negativo é normalizado. Não depende da versão da biblioteca nem dos bytes do arquivo. Nos fills, a ordem canônica é a de `time_ms` e `seq`, e `seq` entra no hash, porque a posição e o preço de um evento dependem da ordem dos fills dentro do milissegundo.

**Escrita.** Toda escrita é atômica: arquivo temporário e troca de nome. Reingerir uma janela compara o conteúdo novo com o gravado, sem olhar `seq`. Se é igual, nada muda, e a ordem gravada fica. Se difere, a diferença é logada e gravada em `divergences`, com o valor anterior e o novo, e o conteúdo novo substitui o antigo, o que muda o hash (RF-ING-08 CA-08.2).

**Janela congelada.** Um congelamento cobre a janela de seleção e a janela de avaliação da sua rota. A exceção à regra acima são as linhas já gravadas com instante dentro de uma janela coberta. Essas nunca são reescritas: a divergência é logada e gravada, e o dado fica como estava. Gravar pela primeira vez os fills da janela de avaliação é permitido; mudar ou inserir linha num trecho já coletado, não. Sem isso, uma reingestão depois do congelamento tornaria a avaliação impossível para sempre, porque o hash deixaria de bater e o conteúdo original teria sido perdido. Quem diz ao `Writer` quais janelas estão congeladas é a CLI, que as lê dos congelamentos em `preregistro/`. O relatório da avaliação conta as divergências encontradas dentro de janela congelada.

### 3.3 Ingestão (`copylab.ingestion`)

```python
class InfoProvider(Protocol):
    def leaderboard(self) -> bytes: ...
    def user_fills(self, address: str, start: Ms, end: Ms) -> list[dict[str, object]]: ...  # uma página, não agregada
    def user_role(self, address: str) -> str: ...
    def meta(self) -> dict[str, object]: ...
    def funding_history(self, coin: str, start: Ms, end: Ms) -> list[dict[str, object]]: ...

class WeightBudget:
    def __init__(self, limit_per_minute: int, clock: Callable[[], float], sleep: Callable[[float], None]) -> None: ...
    def acquire(self, weight: int) -> None: ...   # bloqueia até caber na janela deslizante de 60 s
```

O relógio e a espera são injetados, então o orçamento é testável sem tempo real. O limite configurado tem default de 1.000 por minuto, abaixo do teto de 1.200 da corretora (RF-ING-07 CA-07.1), e cada página de fills reserva 120 antes de a resposta chegar.

**Paginação de fills** (RF-ING-02 CA-02.1). A próxima página começa no instante do último fill recebido, inclusive. Os fills desse milissegundo já vistos são descartados por multiconjunto de chaves. Uma página com menos de 2.000 fills encerra a janela. Ao passar de 20.000 fills na janela, a coleta para e a carteira é marcada (CA-02.3).

**Classificação** (CA-02.4). Pelo nome do ativo e pelo `meta`: perpétuo do primeiro dex se o nome está no `meta`; HIP-3 se tem prefixo de dex; spot se começa com `@` ou contém `/`; token de resultado se começa com `#`; senão, outro. Todo nome classificado como "outro" é listado no relatório, para que um perpétuo que saiu do `meta` não suma em silêncio.

**Retomada.** A tabela `coverage` registra, por endereço, o que já foi ingerido. Uma ingestão interrompida recomeça do primeiro endereço sem cobertura. Falha em um endereço é registrada e não aborta os demais (RF-ING-07 CA-07.2).

**Guarda da janela de avaliação.** Os comandos de ingestão, de fills e de dados de mercado, recebem rota e janela, não datas. Eles recusam a janela de avaliação de uma rota enquanto não existir o congelamento dela, e recusam a janela de seleção da Rota B enquanto não existir o congelamento da Rota A, porque essa janela contém setembro. Não há exceção para proxy e funding: nada da janela de avaliação é baixado antes do congelamento (RF-SEL-05 CA-05.4).

**Tipo de conta.** Consultado só para as carteiras que passaram nos outros filtros, e gravado em `roles` com o instante da coleta.

**Preço proxy** (RF-ING-06). Para cada ativo e dia: baixa o arquivo de negócios agregados e o `.CHECKSUM`, confere, e reduz a uma linha por segundo com mínimo, máximo, último e contagem. O arquivo bruto é apagado em seguida. O mapa de nomes entre as corretoras (por exemplo `kPEPE` e `1000PEPEUSDT`) fica no arquivo de parâmetros, e a condição de nível de CA-06.3 é o que denuncia um mapa ou uma escala errada.

**Quais ativos recebem proxy.** Os perpétuos do primeiro dex são percorridos em ordem decrescente de notional das candidatas, enquanto tiverem ao menos 2.000 fills. Para cada um, o nome na Binance vem da regra do arquivo de parâmetros: o mesmo nome com `USDT`, o prefixo `k` trocado por `1000`, e as exceções listadas. A condição (i) do universo é conferida baixando: se falta o arquivo de algum dia da janela, o ativo falha nela e é reportado. A busca para quando 20 ativos a cumprem. BTC entra sempre.

### 3.4 Coletor (`copylab.collector`)

Um processo assíncrono, uma conexão, três assinaturas por ativo (melhor compra e venda, livro rápido e negócios) e um ping periódico. A lista de ativos fica em `config/collector_assets.toml`, versionada. Ela começa com os 27 ativos com equivalente na Binance encontrados na verificação, que incluem BTC, e recebe os ativos candidatos que faltarem quando o pool de uma rota é ingerido.

- **Gravação.** Cada mensagem é gravada como veio, com o instante de recebimento, em segmentos de uma hora por ativo e canal, comprimidos, com descarga periódica. Um segmento em escrita tem sufixo próprio e é renomeado ao fechar. Depois de uma queda, o segmento interrompido é lido até o último bloco íntegro.
- **Lacunas.** Há um registro por ativo, no relógio da corretora, que é o relógio em que o simulador as consulta. Uma lacuna vai do instante da última mensagem do livro rápido antes dela ao instante da primeira depois. Há lacuna em dois casos: uma desconexão detectada entre as duas mensagens, ou mais de 10 s entre elas. Negócios e melhor compra e venda não entram na regra.
- **Compactação.** Uma etapa separada converte os segmentos fechados de um dia nas tabelas `bbo`, `book` e `trades`, confere as contagens contra os segmentos e só então os apaga. A partir daí a tabela compactada é o registro. A primeira mensagem de cada assinatura é um retrato do passado e é descartada.
- **Status.** Lê o registro de lacunas e os arquivos, sem falar com o processo: cobertura por ativo, latência de recebimento e projeção de disco para 45 dias.

O coletor não tem lógica de domínio. Se a máquina dormir ou a rede cair, o resultado é uma lacuna registrada, nunca um dado inventado.

Os dados chegam à máquina de análise por cópia do diretório das tabelas compactadas, e o hash de conteúdo confere a cópia.

### 3.5 Livro-razão do líder (`copylab.leader`)

Transforma fills de perpétuos em posições, eventos e episódios. É usado pela seleção e pelo simulador, e por isso é um pacote próprio, com o mesmo piso de cobertura.

```python
@dataclass(frozen=True, slots=True)
class LeaderEvent:
    t: Ms
    coin: str
    kind: Kind             # perpétuo do primeiro dex ou HIP-3
    prev_position: float   # posição declarada antes do primeiro fill do evento
    position: float        # posição depois do último fill do evento, com sinal
    touched_zero: bool     # dentro do evento, a posição partiu de zero, chegou a zero ou cruzou o zero
    px: float              # preço do último fill do evento
    notional: float        # soma de |sz| × px dos fills do evento
    unobserved: bool       # a posição anterior declarada não era a que se tinha
    n_fills: int

@dataclass(frozen=True, slots=True)
class Episode:
    coin: str
    opened: Ms
    closed: Ms | None
    side: int                      # +1 ou -1
    opened_from_flat: bool         # falso quando a posição já existia no início da janela
    traded_notional: float
    opening_notional: float        # fills que aumentam o módulo da posição
    opening_taker_notional: float  # idem, só com crossed = true
    n_fills: int

def build_events(fills: pl.DataFrame, lots: Mapping[str, float]) -> list[LeaderEvent]: ...
def build_episodes(fills: pl.DataFrame, lots: Mapping[str, float]) -> list[Episode]: ...
def continuity_breaks(fills: pl.DataFrame, lots: Mapping[str, float]) -> list[Break]: ...
def pnl_divergence_bps(fills: pl.DataFrame, episode: Episode) -> float: ...
```

Regras:

- **Abrangência.** Posições e eventos são reconstruídos para todos os perpétuos, do primeiro dex e HIP-3, porque o filtro F8 conta os dois. O simulador só age sobre os do universo. Um fill de HIP-3 sem campo de posição interpretável é ignorado e contado.
- **Posição.** Para cada fill, posição depois = `start_position` mais `sz` com o sinal do lado. O `start_position` do fill é a verdade: se ele difere da posição que se tinha em mais de um lote, que é a tolerância de RF-ING-03 CA-03.1, houve mudança não observada (RF-SIM-02 CA-02.8).
- **Um evento por líder, ativo e milissegundo.** Os fills de um mesmo milissegundo viram um evento, com a posição final. Uma ordem do líder dividida em 256 fills gera uma decisão do seguidor, não 256. `touched_zero` guarda o que a agregação esconderia: uma posição que vai de 10 a zero e a 3 no mesmo milissegundo fechou um episódio e abriu outro.
- **Zero.** Posição com módulo abaixo de meio lote é zero. Para HIP-3, cujo lote não está no `meta` coletado, a posição depois de um fill é zero quando o módulo dela é menor que 10⁻⁹ vezes o tamanho desse fill.
- **Episódio.** De zero a zero, construído fill a fill, não evento a evento. Um fill que cruza o zero encerra um episódio e abre outro no mesmo instante, com o tamanho dividido entre os dois. O `closed_pnl` desse fill pertence ao episódio que fecha.
- **Conferência de PnL.** Só para episódios abertos a partir de zero e fechados dentro da janela. Reconstrução por custo médio, comparada com a soma de `closed_pnl`, em bps do notional negociado (RF-ING-04 CA-04.2). Episódio que já estava aberto no início da janela não tem custo de entrada conhecido e fica fora.

### 3.6 Seleção (`copylab.selection`)

```python
def sample_pool(leaderboard: pl.DataFrame, min_account_value: float, blocks: int, block_size: int, seed: int) -> list[str]: ...
def candidate_assets(repo: BoundedRepository, pool: Sequence[str], window: Window, params: Params) -> list[AssetFacts]: ...
def form_universe(assets: Sequence[AssetFacts], costs: CostParams, params: Params) -> Universe: ...
def wallet_facts(repo: BoundedRepository, address: str, window: Window, universe: Universe) -> WalletFacts: ...
def apply_filters(facts: WalletFacts, role: str | None, params: Params) -> FilterOutcome: ...
def reference_exposure(events: Sequence[LeaderEvent], universe: Universe, window: Window) -> float | None: ...
def rank(eligible: Sequence[str], results: Mapping[str, SubaccountResult]) -> list[Ranked]: ...
def control_cohorts(eligible: Sequence[str], k: int, n: int, seed: int) -> list[tuple[str, ...]]: ...
def dump_freeze(freeze: Freeze) -> str: ...
def parse_freeze(text: str) -> Freeze: ...
def check_freeze(freeze: Freeze, repo: Repository, params: Params) -> None: ...   # levanta se hash ou parâmetro diverge
```

**Ordem dentro de `select`.** Pool, ativos candidatos, conferência do proxy, universo, fatos por carteira, filtros F2 a F10, tipo de conta das sobreviventes, F1, N\*, contagem de elegíveis, ranking, coortes de controle, congelamento.

- **Pool** (RF-SEL-07). Endereços que passam em F2, postos na ordem do SHA-256 do texto `semente:pool:endereço`. O bloco `n` é a fatia `[3000·n, 3000·(n+1))` dessa ordem, o que torna a ampliação determinística. Com menos de 20 elegíveis e o bloco seguinte ainda não ingerido, `select` para com código de saída diferente de zero e diz qual bloco ingerir. A cada ampliação, universo e filtros são refeitos sobre o pool inteiro.
- **Ativos candidatos.** Contam só as carteiras do pool com cobertura `ok`. Carteira marcada "frequência incompatível" tem histórico parcial e não entra na soma.
- **Conferência do proxy** (RF-ING-06 CA-06.3). Cada fill de perpétuo do primeiro dex é comparado ao último preço do segundo do proxy que contém o instante do fill: `diferença = (preço do fill / último − 1) × 10⁴`. Fill em segundo sem negócio é pulado e contado. A mediana é por dia. O desvio de um fill é o módulo da diferença dele para a mediana do seu dia, e o p95 é tomado sobre todos os fills da janela. O nível é o maior módulo de mediana diária.
- **Universo** (RF-SEL-08). `form_universe` aplica as cinco condições e registra, para cada ativo, a condição que o excluiu.
- **Filtros** (RF-SEL-02). `wallet_facts` calcula uma vez tudo o que os filtros precisam. Cada filtro é uma função pura de `WalletFacts` e `Params`. F1 depende do tipo de conta, que a CLI manda coletar só para as carteiras que passaram em F2 a F10, e entra numa segunda passada.
- **N\*** (RF-SEL-03, ADR-0007). A exposição bruta é uma função em degraus entre eventos. Contam só os degraus com exposição positiva. N\* é o menor valor de exposição tal que o tempo passado nele ou abaixo dele é pelo menos 95% do tempo em posição, sem interpolação. Antes do primeiro fill de um ativo na janela, a posição é o `start_position` desse fill, avaliada ao preço dele.
- **Ranking** (RF-SEL-04). Simula cada elegível na janela de seleção, no cenário primário, com subconta de capital primário, sobre o `BoundedRepository`, com o preço proxy nas duas rotas, porque o livro gravado não cobre a janela de seleção de nenhuma delas. Ordena por Sharpe diário, com Sharpe indefinido no fim, descarta retorno não positivo e desempata por endereço.
- **Aleatoriedade.** Uma semente só, a de §7.2, e nenhum gerador de números aleatórios de biblioteca. A coorte de controle de número `i`, para um dado K, são os K primeiros elegíveis na ordem do SHA-256 de `semente:controle:K:i:endereço`. O sorteio não muda com a versão de nenhuma biblioteca e pode ser conferido à mão.
- **Congelamento** (RF-SEL-05). `dump_freeze` produz um texto JSON com chaves ordenadas, para que o mesmo conteúdo gere os mesmos bytes, e a CLI o grava em `preregistro/`. Contém todos os elegíveis, com N\*, Sharpe e retorno na janela de seleção, e não só a coorte, porque as coortes por capital são prefixos do ranking e as coortes de controle saem da lista de elegíveis. Contém também o instante e o hash dos snapshots de leaderboard, lotes e tipo de conta. A lista completa de campos: rota, corte, as duas janelas, versão do código, hash dos parâmetros, valores de custo usados, universo com a condição de cada ativo, blocos do pool usados, funil, elegíveis, coorte por capital, semente e número das coortes de controle, e instante e hash de cada conjunto de dados lido. A versão do código é o commit do git, que a CLI informa, e `select` se recusa a rodar com alteração não commitada em `src/` ou em `preregistro/`.

**Definição operacional dos filtros.** Os limiares estão em §7.3 dos requisitos. O que segue fixa como cada um é medido.

| Filtro | Como é medido |
|---|---|
| F1 | `role` igual a usuário comum na tabela `roles` |
| F2 | `account_value` do snapshot |
| F3 | Nenhuma quebra de continuidade em ativo do universo dentro da janela; nenhum fill de perpétuo do primeiro dex com campo inválido; todo episódio do universo aberto e fechado na janela com divergência de PnL dentro da tolerância; cobertura com status `ok` |
| F4 | Número de episódios do universo abertos a partir de zero e fechados dentro da janela |
| F5 | Os 8 blocos são os 56 dias que terminam no corte. Conta o bloco em que ao menos um episódio do universo foi aberto a partir de zero |
| F6 | Mediana da duração dos mesmos episódios de F4 |
| F7 | Nos episódios do universo abertos a partir de zero na janela: notional dos fills que aumentam o módulo da posição com `crossed = true`, dividido pelo notional de todos os fills que aumentam |
| F8 | Mediana, ponderada pelo tempo e medida sobre o tempo em posição, do número de perpétuos com posição diferente de zero. Posição já aberta no início da janela conta desde o início |
| F9 | Notional dos fills em ativos do universo, dividido pelo notional de todos os fills da carteira na janela, em qualquer instrumento |
| F10 | Nenhum fill com `liquidated_user` igual ao endereço da carteira |

### 3.7 Simulador (`copylab.sim`)

```python
class PriceSource(Protocol):
    def available_from(self, coin: str, t: Ms) -> Ms | None: ...     # primeiro instante ≥ t com observação utilizável
    def ladder(self, coin: str, t: Ms, side: Side) -> Ladder: ...    # níveis de preço e tamanho contra o seguidor
    def mark(self, coin: str, t: Ms) -> float: ...
    def horizon(self) -> Ms: ...                                     # observação mais avançada já consumida

@dataclass(frozen=True, slots=True)
class Frictions:
    delay_ms: int
    slippage_bps: Mapping[str, float]
    fee_bps: float
    funding: bool
    size_constraints: bool          # lote, ordem mínima e teto

@dataclass(frozen=True, slots=True)
class Mirror:
    peak: float
    cap: float
    min_notional: float
    long_only: bool

def run_subaccount(
    tape: LeaderTape, reference: float, universe: Universe, prices: PriceSource,
    funding: FundingTable, lots: Mapping[str, float], capital: float,
    window: Window, frictions: Frictions, mirror: Mirror,
) -> SubaccountResult: ...
```

**Cursor.** O laço tem um cursor de tempo que só ele avança, e só para a frente. As três entradas de informação do simulador estão presas a ele:

- `LeaderTape.until(t)` devolve os eventos do líder até `t` e levanta `LookaheadError` se `t` for maior que o cursor menos o atraso.
- `PriceSource.ladder` e `PriceSource.mark` levantam o mesmo erro para um instante além do cursor.
- `FundingTable.rate(coin, hora)` levanta o mesmo erro para uma hora além do cursor.

É a invariante de RF-SIM-01 CA-01.3, imposta por construção.

**Visão do líder.** O motor não reconstrói o estado do líder a partir de todos os eventos até um instante. Ele o atualiza a cada execução processada, com o evento dela (ADR-0008). Um evento cuja execução ainda espera preço não entra na visão. Sem atraso de preço, a visão é igual aos eventos até `t`.

**Instantes, sim; conteúdos, não** (RF-SIM-01 CA-01.3). O laço precisa saber quando acordar. `LeaderTape.next_wake(depois)` e `PriceSource.available_from` devolvem só instantes futuros: quando há um próximo evento e quando há uma próxima observação. Nenhum dos dois devolve preço, lado ou tamanho. O teste de mutação de CA-01.2 altera também esses instantes depois do corte, e as ordens decididas antes dele não podem mudar.

**Leitura de preço além de `τ`.** A fonte de preço pode consumir uma observação posterior a `τ` em dois casos previstos no ADR-0003: a observação seguinte do livro, na Rota B, e o resto do segundo de execução, na Rota A. `horizon()` devolve a observação mais avançada já consumida, e é dela em diante que o teste de mutação altera os preços.

**Fonte da Rota A (`ProxySource`).** `available_from(c, t)` é `t` se o segundo que contém `t` tem negócio, e senão o início do primeiro segundo posterior que tem. A escada tem um nível só, sem limite de tamanho: o máximo do segundo para compra, o mínimo para venda. A marcação é o último preço do último segundo anterior ao de `τ`.

**Fonte da Rota B (`BookSource`).** Os instantes são os da corretora, que é o relógio dos fills; o de recebimento serve só para medir latência. `available_from(c, t)` é `t` fora de lacuna, e senão a primeira observação depois da lacuna. A escada toma a última observação de melhor compra e venda com instante ≤ `τ` e a primeira com instante > `τ`. O primeiro nível é o pior dos dois preços para o seguidor, com o tamanho da observação que deu esse preço, ou o menor dos dois tamanhos se os preços empatam. Os níveis seguintes são os do livro rápido mais recente com instante ≤ `τ` cujo preço é pior que o do primeiro. A marcação é o ponto médio da última observação ≤ `τ`.

**Cotação e slippage.** O motor aplica o slippage do ativo a todos os níveis da escada, contra o seguidor, antes de qualquer conta. A cotação de um lado é o preço do primeiro nível já com slippage. Na Rota B o mapa de slippage é vazio, porque o livro já é o preço real. Na comparação de fontes de RF-SIM-03 CA-03.4, a perna do proxy usa o slippage primário congelado da Rota A, e a perna do livro, nenhum.

**`SubaccountResult`** traz as ordens, os pagamentos de funding, a curva diária de patrimônio, a alavancagem máxima observada e o instante dela, os contadores de não cópia, o estado final, os eventos pendentes e a marca de conta congelada.

### 3.8 Analytics (`copylab.analytics`)

```python
def daily_returns(equity: Sequence[tuple[int, float]]) -> list[float]: ...
def sharpe(returns: Sequence[float]) -> float | None: ...                 # desvio amostral; None quando ele é zero
def max_drawdown(equity: Sequence[tuple[int, float]]) -> Drawdown: ...
def portfolio(subaccounts: Sequence[SubaccountResult], capital: float) -> PortfolioResult: ...
def benchmark_buy_and_hold(prices: PriceSource, funding: FundingTable, lots: Mapping[str, float], capital: float, window: Window, frictions: Frictions, mirror: Mirror) -> SubaccountResult: ...
def decomposition(run: Callable[[Frictions], PortfolioResult], primary: Frictions) -> list[Step]: ...
def effective_window(start: Ms, days: int, max_extension_days: int, min_coverage: float, gaps: Mapping[str, Sequence[Gap]]) -> Window | None: ...
def verdict(portfolio: PortfolioResult | None, benchmark: SubaccountResult, route: Route, window: Window | None) -> Verdict: ...
def pilot_gate(route_a: Verdict, week_book: PortfolioResult | None, week_proxy: PortfolioResult | None, week: Window | None, params: Params) -> Gate: ...
def render_plot(...) -> bytes: ...                                        # imagem PNG em memória
def render_selection_report(...) -> str: ...
def render_evaluation_report(...) -> str: ...
def render_gate_report(...) -> str: ...
```

- **Carteira.** Como as subcontas são independentes, o patrimônio da carteira é a soma, dia a dia, mais o capital parado quando a coorte é menor que K (RF-SIM-07 CA-07.1).
- **Episódio copiado.** Episódio da própria subconta: a posição dela em um ativo sai de zero e volta a zero. Os que estão abertos no fim da janela são contados à parte e não entram na taxa de acerto.
- **Taxa de acerto.** Fração dos episódios copiados fechados cujo resultado líquido, depois de taxas e funding, é positivo.
- **Giro.** Soma do notional executado na janela, dividida pela média dos patrimônios diários.
- **Não cópia** (RF-ANA-04). Para cada evento do líder, a fração não copiada é `1 − tamanho executado / tamanho que o alvo pediria sem teto, mínimo nem profundidade`, limitada entre 0 e 1. O notional não copiado é o notional do evento vezes essa fração, e o motivo é a primeira restrição que cortou a ordem.
- **Excesso sobre o teto** (RF-SIM-02 CA-02.7). Número de execuções que terminaram com exposição acima de `teto × patrimônio` e o maior excesso, em dólares e em fração do patrimônio.
- **Grade** (RF-SIM-08). Onze cenários na Rota A: os nove pares de capital e Δ com o slippage primário, mais slippage zero e slippage em dobro no capital e no Δ primários. Nove na Rota B, que não tem slippage. A variante só compras roda em todos.
- **Benchmark.** Uma subconta sintética: compra de BTC a 1x no primeiro instante da janela mais o atraso do cenário, pela mesma fonte de preço, com a mesma taxa e o mesmo funding, marcada no fim. O tamanho sai da mesma regra de teto de §4.3, com lote.
- **Decomposição.** Seis execuções, cada uma com um `Frictions` que liga um fator a mais. O primeiro degrau tem atraso zero e tudo desligado. Na Rota B o degrau do slippage não muda nada, e o relatório diz por quê.
- **Coortes de controle.** Cada elegível é simulado uma vez por cenário e por capital de subconta. O resultado de uma coorte é a soma das subcontas dos seus membros, então mil coortes não custam mil simulações.
- **Contadores de não cópia.** Cinco saem do laço. O de "fora do universo" sai da tabela de fills: conta fills e notional do líder, na janela, em qualquer instrumento que não esteja no universo.
- **Veredito.** Três resultados possíveis: critério atingido, critério não atingido e rota inconclusiva. O terceiro só existe na Rota B, quando a cobertura não fecha dentro da extensão.
- **Janela efetiva e gate.** Ver §4.4.

Os relatórios são texto em Markdown, e a CLI os grava. Junto com o relatório de avaliação, ela grava `preregistro/resultado-<rota>.json`, com o veredito, as métricas do cenário primário, a versão do código e os hashes dos dados. É esse arquivo que o gate lê para a condição (i).

| Relatório | Conteúdo |
|---|---|
| Seleção | Funil por filtro, universo com a condição que excluiu cada ativo e a cobertura, conferência do proxy por ativo e por dia, diagnóstico das quebras, nomes classificados como "outro", coorte e ranking, com N\* e as horas em posição que o sustentam |
| Avaliação | Veredito, grade de cenários, benchmarks, decomposição, contadores, quebra por ativo, controle só compras, execuções atrasadas e atraso efetivo por ativo, divergências em janela congelada, latência medida, conferência do livro contra o proxy (Rota B), avisos de amostra e a seção fixa de vieses |
| Gate | As quatro condições, uma a uma, a declaração de que é verificação de consistência, o número de episódios da semana e o teto de capital |

O texto da seção de vieses é uma constante, e um teste confere que ela está nos três.

### 3.9 Parâmetros, custos e CLI

`preregistro/parametros.toml` contém tudo o que §7.2 e §7.3 dos requisitos listam, mais o mapa de nomes entre as corretoras. `params.py` o carrega num modelo imutável e expõe o hash dos valores carregados, em forma canônica. Nenhum limiar aparece como literal no código. O teste que prova isso é de comportamento: para cada limiar, uma carteira sintética na fronteira muda de lado quando o valor no arquivo muda.

`preregistro/custos.json` contém o meio-spread mediano por ativo (RF-COL-05 CA-05.2). A medida é esta: nos 3 primeiros dias UTC completos, a contar do primeiro dia em que o ativo foi gravado, em que a cobertura dele foi de ao menos 95%, cada observação de melhor compra e venda tem meio-spread `(venda − compra) / (2 × ponto médio)`, em bps, e peso igual ao tempo até a observação seguinte, sem contar tempo dentro de lacuna. O valor gravado é a mediana ponderada. O arquivo guarda, por ativo, o valor, o intervalo usado e o hash dos dados. Cada ativo é medido uma vez: o comando acrescenta os ativos que ainda não estão no arquivo e nunca altera um valor já gravado. BTC é sempre medido. Cada congelamento copia os valores que usou.

| Comando | O que faz |
|---|---|
| `copylab ingest leaderboard` | Grava um snapshot do leaderboard e um dos lotes |
| `copylab ingest fills --route A --window selection` | Fills do pool, com retomada. A janela de avaliação só depois do congelamento |
| `copylab ingest market --route A --window selection` | Funding e proxy dos ativos candidatos e de BTC. A janela de avaliação só depois do congelamento |
| `copylab collect` / `collect status` / `collect compact` | Coletor |
| `copylab costs measure` | Mede os ativos que ainda não estão em `custos.json` |
| `copylab select --route A` | Universo, filtros, ranking, congelamento. Na Rota B, com `--cutoff` |
| `copylab window open --freeze <arquivo>` | Registra a publicação do congelamento da Rota B |
| `copylab evaluate --freeze <arquivo>` | Simula a janela de avaliação e escreve o relatório e o arquivo de resultado |
| `copylab gate --freeze <arquivo>` | Computa o gate do piloto, uma vez |

---

## 4. Fluxos

### 4.1 Ordem das operações da fase

1. O coletor entra em operação com a lista provisória.
2. Snapshot do leaderboard e dos lotes, sorteio do pool e ingestão dos fills da janela de seleção da Rota A.
3. Ingestão de funding e proxy dos ativos candidatos, só da janela de seleção. A lista do coletor recebe os candidatos que ainda não estavam nela.
4. Com ao menos 3 dias de coletor para todos esses ativos, `costs measure`.
5. `select --route A`: universo, filtros, N\*, ranking, congelamento. Commit do congelamento.
6. Ingestão da janela de avaliação da Rota A: fills dos elegíveis, funding e proxy. `evaluate`. Relatório de triagem e arquivo de resultado.
7. Snapshot novo, pool novo e ingestão da janela de seleção da Rota B. O corte da Rota B é uma meia-noite UTC para a qual o arquivo da Binance do dia anterior já foi publicado, o que costuma levar um dia, e a janela de seleção são os 62 dias que terminam nele. Ativo candidato que ainda não estava no coletor entra nele e espera 3 dias de gravação para ser medido por `costs measure`. `select --route B --cutoff`. O coletor passa a gravar o universo da Rota B.
8. Commit e `push` do congelamento da Rota B, e `window open`, tudo antes da meia-noite UTC seguinte.
9. A cada dia da janela da Rota B, ingestão incremental dos fills dos elegíveis e compactação do coletor.
10. Completa a semana ao vivo, `gate`. Completos os 30 dias, `evaluate`.

Os passos 2 a 6 não dependem de esperar por dado novo, exceto os 3 dias do passo 4, que correm em paralelo com a construção do resto. Os dias entre o corte da Rota B e o início da janela de avaliação não entram em nenhuma das duas janelas.

### 4.2 O laço do simulador

O laço de uma subconta percorre, em ordem de instante, quatro tipos de ocorrência:

| Prioridade no mesmo instante | Ocorrência | Origem |
|---|---|---|
| 1 | Funding de uma hora cheia | tabela de funding |
| 2 | Execução em um ativo | evento do líder em `t`, executado a partir de `t + Δ` |
| 3 | Amostra diária de patrimônio | meia-noite UTC |
| 4 | Fim da janela | parâmetro |

A ordem dentro do mesmo instante é fixa e faz parte do contrato. Funding antes da execução, porque o funding incide sobre a posição que existia durante a hora. Amostra depois, porque o patrimônio do dia é o do fim do dia. O funding do instante `H` usa o registro com `hour_ms = H` e incide sobre as posições abertas em `H`. No teste de mutação, um funding é posterior a um instante quando o `hour_ms` dele é. Execuções no mesmo instante seguem a ordem do instante do evento que as originou e, no empate, a alfabética do ativo.

A janela é semiaberta. Nenhuma ocorrência com instante igual ou posterior ao fim acontece: no fim, a subconta só é marcada. O funding da hora que coincide com o fim fica de fora, para a carteira e para o benchmark.

O patrimônio é marcado em toda ocorrência. É nessas marcações que se detecta patrimônio não positivo e que se registra a alavancagem máxima observada.

### 4.3 Processamento de uma execução

Cada evento do líder gera uma execução (ADR-0008). Para um evento em `c` no instante `t`, o instante nominal é `t + Δ`, e a execução acontece em `τ`, o primeiro instante a partir dele em que a fonte de preço tem observação de `c`. Quase sempre os dois coincidem. Quando não coincidem, nada é contabilizado antes de `τ`, a execução usa o patrimônio e os preços de `τ`, e o atraso efetivo fica registrado (RF-SIM-01 CA-01.5). Se `τ` não existe ou não é anterior ao fim da janela, o evento fica pendente.

1. **Visão do líder.** O seguidor conhece o líder pelos eventos cujas execuções já foram processadas, mais o evento desta execução. Em cada ativo vale a posição do último evento processado. Um ativo passa a ser rastreado no primeiro evento processado, dentro da janela, em que a posição do líder nele toca o zero: parte de zero, chega a zero ou cruza o zero. Até lá o alvo nele é zero. Variante só compras: posição negativa conta como zero.
2. **Patrimônio.** `P₀` é o patrimônio da subconta em `τ`, à marcação. Se for ≤ 0, a subconta congela e o laço termina.
3. **Razões.** Para cada ativo rastreado `j`, com a posição e o preço do último fill que estão na visão: `r_j = posição_j × preço_j / N*`.
4. **Fator do teto.** `g = pico × Σ|r_j|` e `f = min(1, teto / g)`.
5. **Alvos.** `alvo_j = pico × f × r_j × P₀`, em dólares, com sinal. A soma dos módulos nunca passa de `teto × P₀`.
6. **Reduções exigidas pelo teto.** A exposição projetada é a soma das posições atuais dos demais ativos, à marcação, mais o módulo de `alvo_c`. Se ela passa de `teto × P₀`, a diferença é o excesso `E`. Cada ativo `j ≠ c` cuja posição atual, à marcação, excede em módulo o seu alvo tem uma sobra `s_j`, e `S` é a soma das sobras. Alvo de sinal contrário ao da posição conta como zero. Cada um desses ativos recebe uma redução de `s_j × E / S` dólares, convertida em tamanho pela cotação do lado que reduz. É o mínimo que devolve a carteira ao teto, repartido em proporção: `E` nunca passa de `S`, e uma redução nunca cruza o zero. A ordem é a alfabética. O gatilho é a exposição real da subconta, e não o fator `f`: uma posição que cresceu porque o preço andou também dispara a redução. Se a fonte de preço não tem observação de `j` em `τ`, a redução não é enviada e é contada, e o passo 8 impede aumentos enquanto o excesso durar.
7. **Ordem em `c`.** O lado sai da comparação entre `alvo_c` e a posição atual à marcação. Com a cotação desse lado, o tamanho-alvo é `alvo_c / cotação`. Se a diferença para o tamanho atual não tem o sinal do lado, não há ordem. A ordem tem uma parte que reduz a posição atual e, se o alvo vai além dela ou cruza o zero, uma parte que aumenta. Quando cruza o zero, são duas ordens no mesmo instante: o fechamento e a abertura.
8. **Limite da parte que aumenta.** Ela é o maior múltiplo do lote, até o tamanho pedido, para o qual o estado depois da ordem satisfaz `exposição bruta ≤ teto × patrimônio`, com a posição inteira em `c`, a que já existia e a nova, avaliada ao preço médio da ordem, tanto no patrimônio quanto na exposição, os demais ativos à marcação e a taxa da ordem já descontada. Com um nível só de preço, isso equivale a `X ≤ (teto × P − O) / (1 + teto × taxa)`, em que `X` é o notional adicional, e `P` e `O` são o patrimônio e a exposição bruta depois das reduções, com `c` à cotação. O que não coube conta como "teto atingido".
9. **Lote e mínimo.** O tamanho de cada ordem é arredondado para baixo, em módulo, ao lote. Se o notional à cotação fica abaixo do mínimo e a ordem não zera a posição, ela não é enviada e entra no contador. Não existe fila de ordens: o alvo é recalculado do zero na próxima execução daquele líder naquele ativo, e é assim que a diferença persiste.
10. **Execução.** Primeiro as reduções do passo 6, depois a parte que reduz em `c`, depois a que aumenta. Cada ordem percorre a escada até o tamanho pedido ou o fim dos níveis. Ordens no mesmo instante e no mesmo ativo consomem a mesma escada em sequência: cada uma continua de onde a anterior parou. O que sobra por falta de nível conta como "profundidade excedida". O preço da ordem é o médio ponderado dos níveis usados. Taxa sobre o notional executado. Atualiza posição, custo médio, PnL realizado e saldo.
11. **Registro.** Cada ordem guarda o instante do evento que a originou, o instante nominal, o instante da execução, ativo, lado, tamanho pedido e executado, preço, taxa e motivo.

Sem restrições de tamanho, que é o caso dos cinco primeiros degraus da decomposição, `f = 1` e os passos 6, 8 e 9 não se aplicam. A escada continua valendo, porque ela é o modelo de preço.

O teto é garantido onde o seguidor age: nenhuma ordem que aumenta a exposição passa dele, e a conta já desconta a taxa. Onde ele pode ficar violado depois de um evento é nos dois casos que as erratas do ADR-0002 descrevem: a redução necessária cai abaixo da ordem mínima, ou o ativo a reduzir não tem preço naquele instante. Esse excesso é contado, e o passo 8 impede qualquer aumento enquanto ele durar.

### 4.4 A janela da Rota B

A janela de avaliação da Rota B não é escolhida por ninguém: é função de um instante registrado e das lacunas gravadas.

1. **Publicação.** O instante de publicação é o do commit do congelamento, lido do git, e não o momento em que alguém roda um comando. Depois do `push`, `copylab window open` confere que esse commit está no remoto e grava `preregistro/rota-b-publicacao.json`, com o hash do congelamento, o commit e o instante dele. O comando se recusa a rodar a partir da primeira meia-noite UTC posterior ao commit. Assim, rodar mais tarde não desloca a janela, e quem perde o prazo precisa de um congelamento novo. O arquivo é versionado e nunca é sobrescrito.
2. **Início.** A primeira meia-noite UTC posterior à publicação em que o coletor está gravando todos os ativos do universo e BTC (RF-SEL-05 CA-05.3, RF-SEL-08 CA-08.4). "Gravando" é: fora de lacuna naquele instante.
3. **Fim.** `effective_window(início, dias, extensão, cobertura mínima, lacunas)`. Se, ao fim dos `dias`, todo ativo tem cobertura de ao menos 95%, a janela termina ali. Senão, termina na primeira meia-noite UTC, dentro da extensão máxima, em que todo ativo acumulou `dias` inteiros de tempo sem lacuna. Se nenhuma serve, o resultado é ausente e a janela é inconclusiva. Para a semana ao vivo, 7 dias e extensão de 3. Para o veredito, 30 dias e extensão de 15.
4. **Gate.** `gate` calcula a semana por essa função. Se os dados ainda não alcançam o fim da semana, o comando sai sem gravar nada e diz quanto falta. Se a semana é inconclusiva, grava `preregistro/gate.json` com esse resultado, que conta como não atingido. Nos demais casos, simula a semana com o livro e com o proxy e grava o resultado. Depois de gravado, o comando se recusa a rodar de novo.
5. **Veredito.** `evaluate` usa a mesma função com 30 dias. Janela inconclusiva dá o resultado "rota inconclusiva", que não é critério atingido nem critério não atingido (ADR-0004). O que isso significa para um piloto em andamento é assunto da spec dele.

---

## 5. Contabilidade

Uma subconta guarda saldo em dólares e, por ativo, tamanho com sinal e custo médio.

- Abrir ou aumentar: o custo médio é a média ponderada. Nada é realizado.
- Reduzir ou fechar: realiza `tamanho reduzido × (preço − custo médio) × sinal da posição`, que entra no saldo.
- Cruzar o zero: são duas ordens. A primeira fecha tudo e realiza, a segunda abre ao preço dela.
- Funding de uma hora: `tamanho com sinal × marcação × taxa da hora`, debitado quando positivo.
- Taxa e funding saem do saldo e são acumulados em contadores próprios.

Patrimônio em qualquer instante: `saldo + Σ tamanho × (marcação − custo médio)`.

Identidade de conciliação (RF-SIM-06 CA-06.2), conferida ao fim de toda simulação:

```
patrimônio final − capital inicial = PnL realizado + PnL não realizado − taxas − funding pago
```

A tolerância é relativa, de 1e-9. Ela vale também com posição aberta no fim, com posição vendida e com a subconta congelada. As parcelas do lado direito são recalculadas a partir da lista de ordens e da lista de pagamentos de funding, por um caminho que não passa pelo saldo. Sem isso a identidade fecharia por construção e o teste não provaria nada.

A curva de patrimônio tem um ponto por meia-noite UTC, mais o instante inicial e o final.

---

## 6. Decisões de design

Decisões locais, baratas de reverter. As caras estão nos ADRs.

| # | Decisão | Alternativa | Por quê |
|---|---|---|---|
| 1 | Um evento por líder, ativo e milissegundo | Um evento por fill | Uma ordem dividida em centenas de fills geraria centenas de decisões idênticas |
| 2 | O alvo é calculado no instante da execução, com a visão do líder naquele instante | Calcular na decisão e guardar | O patrimônio e a cotação só existem em `τ` |
| 3 | O notional do líder usa o preço do último fill dele | Preço de mercado em `τ` | É a mesma régua de N\*, e depende só dos fills |
| 4 | Numa execução em `c`, os outros ativos só recebem a redução mínima que o teto exige, repartida em proporção | Rebalancear todos a cada evento, ou reduzir cada um até o alvo | Evita giro causado por deriva de preço, que a ordem mínima tornaria errático |
| 5 | A redução pelo teto dispara pela exposição real da subconta | Disparar só quando o fator `f` é menor que 1 | O fator vem do líder. Uma posição do seguidor que cresceu por variação de preço ficaria acima do teto sem que nada a reduzisse |
| 6 | Dimensionar pela cotação do lado, já com slippage e com a taxa descontada | Dimensionar pela marcação | Garante o teto aos preços de execução e contra o patrimônio depois da ordem |
| 7 | Ordens no mesmo instante e ativo consomem a mesma escada em sequência | Cada ordem vê a escada inteira | Depois de uma lacuna, várias ordens executam no mesmo instante. Sem isso a profundidade seria contada várias vezes |
| 8 | Cruzar o zero são duas ordens | Uma ordem só | O fechamento é sempre executável e a abertura passa pelo mínimo e pelo teto. Com uma ordem só, as duas regras se misturariam |
| 9 | Cada elegível é simulado uma vez por cenário; coortes são somas | Simular cada coorte | Subcontas são independentes. Mil coortes de controle saem de dezenas de simulações |
| 10 | Curva de patrimônio diária | Curva por evento | Sharpe e drawdown são definidos sobre dias UTC nos requisitos |
| 11 | O coletor grava a mensagem bruta; a compactação é outra etapa | Gravar já em tabela | O coletor precisa ser o código mais simples do sistema. Um erro de parsing não pode custar dado |
| 12 | Lista de ativos do coletor em arquivo versionado | Derivar do universo em tempo real | O coletor roda antes de existir universo, e mudar a lista é um ato deliberado |
| 13 | Ingestão retomável por endereço | Tudo ou nada | São cerca de 15 horas por bloco de 3.000 carteiras |
| 14 | Paralelismo por processo, um por carteira, com a saída ordenada por endereço | Sequencial | O resultado não pode depender da ordem de término |
| 15 | Congelamento guarda todos os elegíveis | Guardar só a coorte | As coortes por capital e as de controle derivam da lista |
| 16 | `float` de 64 bits, tamanhos arredondados ao lote na formação da ordem | `Decimal` | Mesma decisão do quantlab. A conciliação a 1e-9 cabe |
| 17 | Limiar zero de posição em meio lote | Igualdade exata | Preço e tamanho chegam como texto decimal e viram binário |
| 18 | O ranking da seleção usa o preço proxy nas duas rotas | Livro gravado na Rota B | O coletor não cobre os 62 dias da janela de seleção. A condição (i) do universo já exige o proxy |
| 19 | Os 8 blocos de F5 terminam no corte | Começar no início da janela | Os 6 dias que sobram ficam no começo, e o comportamento mais recente entra inteiro |
| 20 | Livro lido pelo instante da corretora | Pelo instante de recebimento | É o mesmo relógio dos fills do líder. A latência de recebimento já está dentro de Δ |
| 21 | Janela da Rota B como função da publicação e das lacunas | Datas informadas à mão | Num estudo pré-registrado, o início e a extensão não podem ser escolha de quem roda |
| 22 | Parâmetros em TOML, lido pela biblioteca padrão | YAML | Sem dependência nova. Em YAML, um nome de ativo como `ON` ou `NO` viraria booleano sem aviso |
| 23 | Sorteios por ordenação de SHA-256, sem gerador de biblioteca | `random` ou `numpy` com semente | O resultado não muda com a versão da biblioteca e se confere à mão |
| 24 | Nenhum dado da janela de avaliação é baixado antes do congelamento, nem proxy nem funding | Isentar dados de mercado, que não falam de carteiras | A regra fica sem exceção para explicar. O custo é baixar setembro depois, o que leva minutos |
| 25 | Lacunas registradas no relógio da corretora | No relógio de recebimento | É o relógio em que o simulador pergunta se há preço |
| 26 | A publicação da Rota B é o instante do commit, com prazo para registrar | O instante em que o comando é rodado | Rodar o comando um dia depois deslocaria a janela, e isso seria uma escolha |
| 27 | `seq` entra no hash dos fills | Hash sem a ordem da API | O preço e a posição de um evento dependem da ordem dos fills no milissegundo. Dois conjuntos com o mesmo hash precisam dar o mesmo resultado |
| 28 | `evaluate` grava um arquivo de resultado além do relatório | O gate ler o relatório em texto | O gate precisa do veredito da Rota A num formato que se confere por hash |

---

## 7. Riscos e limites deste design

1. **Quebras de continuidade sem causa conhecida.** O design as trata sem explicá-las. A hipótese a investigar é que parte dos fills de TWAP some do histórico depois de alguns meses, o que afetaria mais a Rota A que a Rota B. O diagnóstico de RF-ING-03 CA-03.4 existe para testar isso com o primeiro bloco de ingestão.
2. **Segundos sem negócio no proxy.** Em ativos pouco líquidos da Binance, o segundo de execução pode não ter negócio, e a execução passa para o próximo que tem. O relatório mostra a distribuição desse atraso por ativo.
3. **Operações dentro de uma lacuna.** Na Rota B, se o líder abre e fecha uma posição enquanto o coletor está fora do ar, as duas ordens do seguidor executam ao mesmo preço, depois da lacuna: ele paga spread e taxas e não captura o movimento (ADR-0008). O erro é para o lado pessimista. A cobertura mínima limita o efeito, e o relatório conta as execuções atrasadas.
4. **Custo medido em outubro, aplicado de julho a setembro.** O meio-spread do coletor vale para a época em que foi medido. A semana ao vivo é a conferência disso.
5. **Lotes e tipo de conta de hoje.** A seleção de julho e agosto usa o tamanho de lote e o tipo de conta coletados em outubro. Uma mudança entre as duas datas não é observável.
6. **Uma máquina, uma conexão.** O coletor não tem redundância. A regra de cobertura dos requisitos é a resposta.
7. **A API pode mudar.** Formatos lidos em outubro de 2026. Os provedores validam o formato na borda e falham alto.
8. **Coorte de uma carteira no cenário primário.** O design não mitiga. É propriedade do capital escolhido.
9. **Disco do coletor.** A verificação mediu cerca de 2 GB comprimidos por 45 dias, para 3 ativos, com o livro default. Este design grava 27 ativos ou mais, com o livro rápido, que chega dez vezes mais vezes com um quarto dos níveis. A extrapolação é grosseira e pode passar do orçamento de 30 GB. O primeiro dia de coletor mede o número real, pelo comando de status. Se a projeção passar do orçamento, a lista do coletor é cortada pelos ativos de menor notional, por emenda.
10. **Ordem dos fills no mesmo milissegundo.** O design supõe que a API devolve os fills de um milissegundo numa ordem que encadeia a posição. A verificação não encontrou quebra dentro do mesmo milissegundo em 100 casos, mas essa ordem não é documentada.
11. **O piloto não está aqui.** Nada neste design envia ordem. O teste de somente leitura continua valendo para todo o repositório.

---

## 8. Invariantes e testes nomeados

### 8.1 Invariantes centrais

| Invariante | Como é garantida | Teste que prova |
|---|---|---|
| Nenhuma ordem depende de informação posterior a `τ − Δ` (RF-SIM-01, ADR-0003, ADR-0008) | Fita, fonte de preço e tabela de funding são as únicas entradas, e as três recusam leitura além do cursor | `test_mutating_future_does_not_change_orders_decided_before_cutoff`; `test_reading_beyond_information_set_raises` |
| O preço do líder nunca é o preço do seguidor (ADR-0003) | A execução só lê `PriceSource` | `test_follower_price_is_independent_of_leader_fill_price` |
| A seleção não lê nada a partir do corte (RF-SEL-01) | Só recebe `BoundedRepository` | `test_mutating_evaluation_window_does_not_change_frozen_cohort`; `test_selection_reading_at_or_after_cutoff_raises` |
| A seleção não lê desempenho do leaderboard | A tabela derivada não tem essas colunas | `test_selection_reading_leaderboard_performance_raises` |
| A avaliação não roda sem congelamento coerente (RF-SEL-05) | `check_freeze` confere hashes e parâmetros | `test_evaluate_refuses_without_matching_freeze` |
| Nada da janela de avaliação é coletado antes do congelamento (RF-SEL-05 CA-05.4) | Guarda nos comandos de ingestão | `test_evaluation_ingest_requires_freeze` |
| Dado congelado não é reescrito (ADR-0006) | A escrita recusa alterar linha dentro de janela congelada | `test_frozen_rows_are_never_rewritten` |
| Nenhuma ordem que aumenta a exposição passa do teto (ADR-0002 e sua errata) | Passo 8 de §4.3 | `test_gross_exposure_never_exceeds_cap_after_event` |
| Só compras é o mesmo motor com alvos negativos zerados | Uma marca em `Mirror`, sem segundo caminho de código | `test_long_only_variant_equals_engine_with_shorts_dropped` |
| Identidade de conciliação (RF-SIM-06) | Parcelas recalculadas das ordens e do funding | `test_reconciliation_identity_closes` |
| Cópia ideal reproduz o líder na escala do seguidor | `Frictions` com tudo desligado | `test_ideal_copy_reproduces_leader_pnl_at_follower_scale` |
| A janela da Rota B não é escolhida à mão | Função da publicação e das lacunas | `test_route_b_window_is_function_of_publication_and_gaps` |
| O gate é computado uma vez (ADR-0005) | O comando recusa se o arquivo existe | `test_pilot_gate_refuses_recomputation` |
| Determinismo (RNF-01) | Sem relógio na lógica, sementes registradas, saídas ordenadas | `test_same_inputs_give_identical_outputs` |
| Hash independe de arquivo e de ordem de escrita (ADR-0006) | Hash de conteúdo em ordem canônica | `test_content_hash_ignores_file_bytes_and_row_order` |
| Escrita interrompida não corrompe tabela (ADR-0006) | Arquivo temporário e troca de nome | `test_interrupted_write_leaves_previous_table_intact` |
| Somente leitura (RNF-09) | Nenhum cliente de ordem no repositório | `test_architecture_no_order_or_signing_imports` |
| Tempo em milissegundos, uma fronteira (RNF-07) | Só `timeutil` importa `datetime`; só `clock` lê o relógio | `test_architecture_time_boundary` |
| Armazenamento isolado (ADR-0006) | Só `storage` lê e escreve Parquet e conhece o diretório de dados | `test_architecture_storage_isolation` |
| Pacotes de lógica são puros | `leader`, `selection`, `sim` e `analytics` não importam rede, arquivo nem relógio | `test_architecture_logic_packages_are_pure` |
| Nenhum limiar fora do arquivo de parâmetros (RF-SEL-02) | `params.py` é a única fonte | `test_thresholds_come_only_from_parameter_file` |

Dois nomes vêm de ADRs aceitos e ficam como estão, embora o enunciado tenha sido refinado: `test_mutating_future_does_not_change_orders_decided_before_cutoff` prova RF-SIM-01 CA-01.2 pelo relógio da execução, e `test_gross_exposure_never_exceeds_cap_after_event` prova o item (i) de RF-SIM-02 CA-02.7. O teste de somente leitura já existe no repositório com outro nome, `test_source_tree_has_no_order_or_signing_imports`, e é renomeado para o do ADR-0001 na primeira tarefa. `LookaheadError` também entra em `copylab.exceptions` na primeira tarefa, e a docstring de `DataError` deixa de citar leitura proibida.

Todo teste de invariante só é aceito depois de provar que tem dente: quebra-se o código de propósito, o teste cai, o código é restaurado, e a mutação fica registrada na docstring.

### 8.2 Mapa de critérios para testes

Os critérios de RF-VER são verificações sobre dado real, já executadas, e não entram no mapa. Três critérios são operacionais e não se provam só por teste: RF-COL-04 CA-04.2, RF-SEL-05 CA-05.3 e RF-SEL-08 CA-08.4. O teste mapeado prova a regra, e o DoD confere o fato.

**Ingestão**

| Requisito | Critério | Teste |
|---|---|---|
| RF-ING-01 | CA-01.1 | `test_leaderboard_snapshot_is_timestamped_hashed_and_never_overwritten` |
| RF-ING-02 | CA-02.1 | `test_pagination_inclusive_start_dedupes_boundary_millisecond` |
| RF-ING-02 | CA-02.2 | `test_reingesting_window_keeps_fill_count_and_hash` |
| RF-ING-02 | CA-02.3 | `test_wallet_over_fill_cap_stops_and_is_marked_incompatible` |
| RF-ING-02 | CA-02.4 | `test_out_of_universe_fills_are_kept_and_flagged`; `test_fill_is_classified_by_instrument_kind` |
| RF-ING-02 | CA-02.5 | `test_perp_fill_with_invalid_field_makes_wallet_ineligible`; `test_non_perp_fill_without_price_counts_zero_notional` |
| RF-ING-03 | CA-03.1 | `test_position_continuity_detects_missing_fill` |
| RF-ING-03 | CA-03.2 | `test_break_in_selection_window_makes_wallet_ineligible` |
| RF-ING-03 | CA-03.3 | `test_break_in_evaluation_window_does_not_exclude_cohort_wallet` |
| RF-ING-03 | CA-03.4 | `test_break_report_groups_by_age_and_twap_neighbourhood` |
| RF-ING-04 | CA-04.1 | `test_episode_runs_flat_to_flat_and_flip_splits_at_same_instant` |
| RF-ING-04 | CA-04.2 | `test_pnl_divergence_over_10bps_of_notional_makes_wallet_ineligible`; `test_pnl_check_skips_episodes_open_at_window_start` |
| RF-ING-05 | CA-05.1 | `test_funding_record_is_floored_to_hour_and_missing_hour_fails` |
| RF-ING-05 | CA-05.2 | `test_lot_size_is_stored_with_collection_instant` |
| RF-ING-06 | CA-06.1 | `test_proxy_series_has_low_high_last_and_leaves_empty_seconds_absent` |
| RF-ING-06 | CA-06.2 | `test_proxy_checksum_mismatch_fails` |
| RF-ING-06 | CA-06.3 | `test_proxy_invalid_on_dispersion_or_level` |
| RF-ING-06 | CA-06.4 | `test_proxy_report_includes_daily_median_and_its_range` |
| RF-ING-07 | CA-07.1 | `test_rate_budget_never_exceeds_limit` |
| RF-ING-07 | CA-07.2 | `test_wallet_failure_does_not_abort_and_sets_exit_code` |
| RF-ING-07 | CA-07.3 | `test_rate_limited_response_backs_off_then_fails_explicitly` |
| RF-ING-08 | CA-08.1 | `test_result_records_ingestion_instants_and_content_hash` |
| RF-ING-08 | CA-08.2 | `test_changed_fill_is_logged_and_changes_hash`; `test_frozen_rows_are_never_rewritten` |

**Coletor**

| Requisito | Critério | Teste |
|---|---|---|
| RF-COL-01 | CA-01.1 | `test_recorder_writes_bbo_and_fast_book_with_both_timestamps_compressed` |
| RF-COL-02 | CA-02.1 | `test_disconnect_reconnects_and_records_gap_per_asset`; `test_gaps_are_recorded_in_exchange_time` |
| RF-COL-02 | CA-02.2 | `test_book_silence_over_10s_is_gap_and_trades_silence_is_not` |
| RF-COL-02 | CA-02.3 | `test_status_reports_gap_free_fraction_per_asset` |
| RF-COL-03 | CA-03.1 | `test_trades_are_recorded_with_both_addresses_and_timestamps` |
| RF-COL-03 | CA-03.2 | `test_latency_report_gives_median_p95_p99` |
| RF-COL-04 | CA-04.1 | `test_restart_neither_duplicates_nor_corrupts_segments` |
| RF-COL-04 | CA-04.2 | `test_status_projects_disk_usage_against_budget` |
| RF-COL-05 | CA-05.1 | `test_book_vs_proxy_report_gives_median_and_p95_per_asset` |
| RF-COL-05 | CA-05.2 | `test_half_spread_median_is_written_once_to_cost_parameters`; `test_half_spread_median_is_time_weighted`; `test_cost_file_adds_assets_and_never_changes_existing_value` |

**Seleção**

| Requisito | Critério | Teste |
|---|---|---|
| RF-SEL-01 | CA-01.1 | `test_selection_reading_at_or_after_cutoff_raises` |
| RF-SEL-01 | CA-01.2 | `test_mutating_evaluation_window_does_not_change_frozen_cohort`; `test_reference_exposure_ignores_data_at_or_after_cutoff` |
| RF-SEL-01 | CA-01.3 | `test_selection_reading_leaderboard_performance_raises` |
| RF-SEL-01 | CA-01.4 | `test_cost_parameters_come_from_frozen_file` |
| RF-SEL-02 | CA-02.1 | `test_funnel_reports_counts_in_execution_order_and_order_does_not_change_result` |
| RF-SEL-02 | CA-02.2 | `test_thresholds_come_only_from_parameter_file` |
| RF-SEL-02 | CA-02.3 | `test_wallet_failing_exactly_one_filter_is_removed_by_it` |
| RF-SEL-03 | CA-03.1 | `test_reference_exposure_is_time_weighted_p95_over_time_in_position`; `test_reference_exposure_ignores_flat_time` |
| RF-SEL-03 | CA-03.2 | `test_wallet_without_reference_exposure_is_ineligible` |
| RF-SEL-04 | CA-04.1 | `test_ranking_orders_by_daily_sharpe_of_simulated_copy` |
| RF-SEL-04 | CA-04.2 | `test_cohort_takes_top_k_with_positive_return_ties_by_address` |
| RF-SEL-04 | CA-04.3 | `test_short_cohort_and_empty_cohort_outcome` |
| RF-SEL-04 | CA-04.4 | `test_cohort_per_capital_is_prefix_of_single_ranking` |
| RF-SEL-05 | CA-05.1 | `test_freeze_file_contains_all_required_fields` |
| RF-SEL-05 | CA-05.2 | `test_evaluate_refuses_without_matching_freeze` |
| RF-SEL-05 | CA-05.3 | `test_route_b_window_starts_first_utc_midnight_after_publication`; `test_route_b_window_is_function_of_publication_and_gaps`; `test_window_open_refuses_after_first_midnight_following_commit` |
| RF-SEL-05 | CA-05.4 | `test_evaluation_ingest_requires_freeze`; `test_market_ingest_of_evaluation_window_requires_freeze`; `test_route_b_selection_ingest_requires_route_a_freeze` |
| RF-SEL-06 | CA-06.1 | `test_control_cohorts_per_distinct_k_without_replacement` |
| RF-SEL-06 | CA-06.2 | `test_control_cohorts_are_deterministic_for_seed` |
| RF-SEL-06 | CA-06.3 | `test_control_cohorts_enumerate_all_when_fewer_than_n` |
| RF-SEL-07 | CA-07.1 | `test_pool_sample_is_seeded_over_sorted_f2_addresses` |
| RF-SEL-07 | CA-07.2 | `test_pool_grows_in_blocks_until_20_eligibles_or_exhausted`; `test_universe_is_reformed_when_pool_grows` |
| RF-SEL-07 | CA-07.3 | `test_pool_growth_depends_only_on_eligible_count` |
| RF-SEL-08 | CA-08.1 | `test_universe_requires_all_five_conditions` |
| RF-SEL-08 | CA-08.2 | `test_universe_is_formed_before_dependent_filters_and_frozen` |
| RF-SEL-08 | CA-08.3 | `test_universe_report_names_excluding_condition_and_coverage` |
| RF-SEL-08 | CA-08.4 | `test_route_b_window_waits_for_collector_covering_universe` |
| RF-SEL-08 | CA-08.5 | `test_btc_is_always_collected_and_ingested` |

**Simulador**

| Requisito | Critério | Teste |
|---|---|---|
| RF-SIM-01 | CA-01.1 | `test_order_executes_at_event_time_plus_delay` |
| RF-SIM-01 | CA-01.2 | `test_mutating_future_does_not_change_orders_decided_before_cutoff` |
| RF-SIM-01 | CA-01.3 | `test_reading_beyond_information_set_raises`; `test_funding_read_beyond_cursor_raises`; `test_follower_price_is_independent_of_leader_fill_price` |
| RF-SIM-01 | CA-01.4 | `test_event_past_window_end_is_reported_pending` |
| RF-SIM-01 | CA-01.5 | `test_missing_price_uses_next_observation_and_records_delay`; `test_delayed_execution_is_processed_at_effective_instant`; `test_delayed_order_uses_view_of_processed_events`; `test_round_trip_inside_gap_pays_costs_and_captures_nothing` |
| RF-SIM-02 | CA-02.1 | `test_target_at_reference_exposure_equals_peak_times_equity`; `test_target_scales_linearly_with_leader_notional` |
| RF-SIM-02 | CA-02.2 | `test_cap_scales_all_targets_proportionally_reductions_first`; `test_other_assets_only_receive_reductions`; `test_cap_reductions_are_minimal_and_proportional` |
| RF-SIM-02 | CA-02.3 | `test_preexisting_leader_position_is_ignored_until_flat`; `test_tracking_starts_when_leader_position_touches_zero` |
| RF-SIM-02 | CA-02.4 | `test_below_minimum_order_is_skipped_and_delta_persists`; `test_order_size_is_floored_to_lot` |
| RF-SIM-02 | CA-02.5 | `test_full_close_executes_below_minimum` |
| RF-SIM-02 | CA-02.6 | `test_long_only_variant_equals_engine_with_shorts_dropped` |
| RF-SIM-02 | CA-02.7 | `test_gross_exposure_never_exceeds_cap_after_event`; `test_drifted_exposure_triggers_cap_reductions`; `test_unsendable_cap_reduction_is_counted_and_blocks_increases`; `test_cap_reduction_without_price_is_counted` |
| RF-SIM-02 | CA-02.8 | `test_unobserved_position_change_is_absorbed_at_next_fill_and_counted` |
| RF-SIM-03 | CA-03.1 | `test_route_a_uses_worst_price_of_execution_second` |
| RF-SIM-03 | CA-03.2 | `test_route_b_uses_worst_of_adjacent_book_snapshots` |
| RF-SIM-03 | CA-03.3 | `test_route_b_order_beyond_depth_fills_partially_and_counts` |
| RF-SIM-03 | CA-03.4 | `test_source_comparison_shares_cohort_scenario_and_interval`; `test_proxy_leg_of_comparison_uses_frozen_slippage` |
| RF-SIM-04 | CA-04.1 | `test_taker_fee_is_debited_and_recorded_on_order` |
| RF-SIM-04 | CA-04.2 | `test_zero_fee_or_zero_slippage_is_flagged_unrealistic` |
| RF-SIM-05 | CA-05.1 | `test_funding_payment_sign_and_amount` |
| RF-SIM-05 | CA-05.2 | `test_no_position_no_funding` |
| RF-SIM-05 | CA-05.3 | `test_funding_closed_form_ten_hours` |
| RF-SIM-06 | CA-06.1 | `test_equity_is_cash_plus_unrealized_at_mark` |
| RF-SIM-06 | CA-06.2 | `test_reconciliation_identity_closes` |
| RF-SIM-06 | CA-06.3 | `test_open_position_at_end_is_marked_and_reported_separately` |
| RF-SIM-06 | CA-06.4 | `test_subaccount_freezes_at_nonpositive_equity_with_explicit_missing_metrics` |
| RF-SIM-07 | CA-07.1 | `test_subaccounts_are_independent_with_capital_over_k`; `test_short_cohort_leaves_remaining_capital_idle` |
| RF-SIM-07 | CA-07.2 | `test_portfolio_equity_is_sum_of_subaccounts` |
| RF-SIM-08 | CA-08.1 | `test_grid_runs_every_scenario_and_only_primary_feeds_verdict`; `test_grid_has_eleven_scenarios_in_route_a_and_nine_in_route_b` |

**Analytics**

| Requisito | Critério | Teste |
|---|---|---|
| RF-ANA-01 | CA-01.1 | `test_sharpe_uses_sqrt_365_and_zero_risk_free` |
| RF-ANA-01 | CA-01.2 | `test_sharpe_undefined_when_std_is_zero` |
| RF-ANA-01 | CA-01.3 | `test_max_drawdown_uses_running_peak_with_dates` |
| RF-ANA-01 | CA-01.4 | `test_result_breaks_down_by_asset_and_two_groups` |
| RF-ANA-02 | CA-02.1 | `test_benchmark_buy_and_hold_btc_same_costs_and_funding` |
| RF-ANA-02 | CA-02.2 | `test_zero_delay_reference_uses_same_price_source` |
| RF-ANA-02 | CA-02.3 | `test_selected_cohort_percentile_among_control_cohorts` |
| RF-ANA-03 | CA-03.1 | `test_decomposition_has_six_steps_in_fixed_order`; `test_ideal_copy_reproduces_leader_pnl_at_follower_scale` |
| RF-ANA-03 | CA-03.2 | `test_decomposition_step_differences_sum_to_total` |
| RF-ANA-04 | CA-04.1 | `test_non_copy_counters_by_reason` |
| RF-ANA-05 | CA-05.1 | `test_verdict_requires_positive_and_above_benchmark` |
| RF-ANA-05 | CA-05.2 | `test_route_a_verdict_is_labelled_triage` |
| RF-ANA-05 | CA-05.3 | `test_verdict_fails_without_cohort_or_with_frozen_subaccount`; `test_inconclusive_route_is_neither_pass_nor_fail` |
| RF-ANA-05 | CA-05.4 | `test_thirty_day_verdict_ignores_gate_and_pilot` |
| RF-ANA-06 | CA-06.1 | `test_report_contains_fixed_bias_section` |
| RF-ANA-07 | CA-07.1 | `test_small_sample_warning_does_not_change_verdict` |
| RF-ANA-08 | CA-08.1 | `test_pilot_gate_requires_all_four_conditions`; `test_pilot_gate_fails_on_each_single_condition`; `test_gate_reads_route_a_result_file` |
| RF-ANA-08 | CA-08.2 | `test_live_week_extends_then_fails_on_low_coverage`; `test_gate_waits_until_live_week_is_complete` |
| RF-ANA-08 | CA-08.3 | `test_pilot_gate_refuses_recomputation` |
| RF-ANA-08 | CA-08.4 | `test_gate_report_states_consistency_check_and_capital_cap` |

**CLI**

| Requisito | Critério | Teste |
|---|---|---|
| RF-CLI-01 | CA-01.1 | `test_evaluate_prints_and_writes_report_with_verdict_first` |
| RF-CLI-01 | CA-01.2 | `test_missing_data_fails_with_actionable_message_and_exit_code` |
| RF-CLI-02 | CA-02.1 | `test_plot_has_equity_panel_and_drawdown_panel` |

### 8.3 Requisitos não funcionais

| Requisito | Como é verificado |
|---|---|
| RNF-01 Determinismo | `test_same_inputs_give_identical_outputs`, que inclui a execução em paralelo |
| RNF-02 Cobertura | Piso de 85%, com ramos, em `copylab.leader`, `copylab.selection`, `copylab.sim` e `copylab.analytics`. O `pyproject.toml` ganha `copylab.leader` na medição |
| RNF-03 Fixtures de papel | Revisão: a derivação do valor esperado está escrita no teste |
| RNF-04 Performance | `test_performance_budgets`, marcado como integração, sobre dado sintético do tamanho pedido |
| RNF-05 Tipagem | `mypy --strict` no CI |
| RNF-06 Ambiente | A suíte default roda sem rede e sem serviço |
| RNF-07 Tempo | `test_architecture_time_boundary` e `test_architecture_logic_packages_are_pure` |
| RNF-08 Dinheiro | Revisão: comparações com `pytest.approx` |
| RNF-09 Somente leitura | `test_architecture_no_order_or_signing_imports` |
| RNF-10 Custo e disco | `test_status_projects_disk_usage_against_budget` e a medida do primeiro dia de coletor |
| RNF-11 Limites da API | `test_rate_budget_never_exceeds_limit`. O coletor não usa assinatura de usuário |

---

## 9. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.2 | 2026-10-07 | Resposta à leitura cruzada do Claude Code. Corrigido: nenhum dado da janela de avaliação é baixado antes do congelamento; `seq` entra no hash dos fills; a publicação da Rota B é o instante do commit; custos medidos uma vez por ativo, e não uma vez só; redução pelo teto mínima e proporcional; protocolo de leitura em `ports`; gráfico devolvido em bytes; lacunas no relógio da corretora. Definido: métricas de RF-ANA-01, composição da grade, campos do congelamento, arquivo de resultado, sorteio por SHA-256, quais ativos recebem proxy |
| 0.1 | 2026-10-06 | Rascunho inicial, sobre os requisitos 1.2. Já incorpora uma revisão independente, que encontrou dois defeitos (execução atrasada contabilizada no instante nominal, e teto que não disparava redução quando o preço andava) e várias definições que faltavam |
