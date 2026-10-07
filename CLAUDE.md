# CLAUDE.md — regras de trabalho neste repositório

copylab é um estudo de simulação de copy trading na Hyperliquid. O objetivo do projeto não é achar um trader lucrativo: é construir um **instrumento de medição confiável** e emitir um veredito mecânico contra um critério fixado antes de os dados serem lidos. Uma simulação que mente é pior que simulação nenhuma, porque parece informação. Aqui o resultado decide se dinheiro real entra em jogo.

---

## 1. Nenhuma implementação sem spec aprovada

Este repositório é **spec-driven**. A pasta `specs/` é a fonte da verdade.

**Antes de escrever qualquer linha de código de um módulo, leia, nesta ordem:**

1. `specs/README.md` — o fluxo, os gates e o estado atual
2. O `requirements.md` da fase em questão
3. **Todos** os ADRs em `specs/adr/`, não só o que parece relevante
4. `docs/STATE.md` e `HANDOFF.md`, se existirem

O fluxo é **requisitos → design → tarefas → implementação**. Cada transição é um gate explícito. Se a spec do módulo não estiver aprovada na etapa necessária, a resposta correta é parar e dizer que o gate não foi feito, não implementar com ressalva.

**O estado atual não mora neste arquivo.** Ele está em `specs/README.md` e `docs/STATE.md`. Não o copie para cá: cópia de estado envelhece e passa a mentir.

**Exceção declarada:** a verificação de dados (§4.1 dos requisitos da Fase 1) roda antes do design, em `scripts/verify/`, fora de `src/`. Ela mede e reporta. Não decide nada e não altera spec.

Subpacotes vazios estão vazios **de propósito**. Não os preencha por adiantamento. Anote a ideia em `HANDOFF.md` e siga.

Quando a spec estiver errada, corrija a spec primeiro e o código depois. Nunca o inverso, e nunca os dois no mesmo commit sem dizer.

## 2. Invariantes — não são sugestões

As decisões abaixo estão em ADR, e o status de cada um está em `specs/README.md`. Cada uma gera regras que um teste precisa provar.

### ADR-0003 — o seguidor executa em t + Δ, ao pior preço observado

Uma ordem do seguidor executada no instante τ só pode depender de eventos do líder com instante ≤ τ − Δ.

- O preço do fill do líder **nunca** é o preço do seguidor.
- O simulador expõe a cada componente apenas o que já era conhecível naquele instante. Leitura além disso levanta exceção. É garantia por construção, não por disciplina.
- Sem observação de preço em t + Δ, usa-se a próxima existente e registra-se o atraso efetivo. Nenhum preço é interpolado ou inventado.
- Sem preço em t + Δ, cada evento continua gerando a sua ordem, executada na primeira observação, e o seguidor conhece o líder pelos eventos cujas ordens já foram processadas (ADR-0008).
- **O teste que prova a invariante** (RF-SIM-01 CA-01.2): alterar arbitrariamente os eventos do líder depois de um corte c, e os preços e o funding depois de c + Δ e da última observação já consumida, não pode mudar nenhuma ordem executada até c + Δ. Um teste que altere cedo demais acusa lookahead onde há execução correta.

Qualquer conveniência que dê a um componente acesso ao futuro, mesmo indireto, mesmo "só para calcular um indicador", viola este ADR.

### ADR-0004 — seleção isolada no tempo e pré-registro

- A seleção com corte T lê apenas dados com timestamp < T. O teste de aceitação (RF-SEL-01 CA-01.2) altera tudo a partir de T e exige coorte e congelamento idênticos.
- Do leaderboard, a seleção lê só endereços e patrimônio. Campos de desempenho levantam exceção.
- A avaliação se recusa a rodar sem arquivo de congelamento, ou com hash divergente.
- **Nunca leia a janela de avaliação antes do congelamento**, nem para depurar, nem para "dar uma olhada". Nunca altere um parâmetro pré-registrado depois que uma janela de avaliação foi lida.

### ADR-0002 — exposição relativa, teto de 1x

- O alvo do seguidor é proporcional ao notional do líder dividido pela referência de exposição, que é medida só sobre o tempo em posição (ADR-0007) e congelada com a coorte.
- Nenhuma ordem que aumenta a exposição deixa a exposição bruta acima de teto × patrimônio. Excesso que vem de variação de preço é reduzido no evento seguinte, salvo a redução que cai abaixo da ordem mínima, que é contada.
- Ordem abaixo do mínimo não é enviada, e a diferença persiste. Zerar é sempre executável.
- A variante só compras é a mesma simulação com alvos negativos zerados, não um segundo simulador.

### ADR-0001 — Hyperliquid como fonte, somente leitura

- **Nenhuma chave privada, nenhuma assinatura e nenhum endpoint de ordem existem neste repositório.** Um teste de arquitetura sobre os imports garante isso (RNF-09). O piloto com dinheiro real tem spec própria e não começa aqui.
- Respeite 1.200 de peso por minuto por IP.
- A posição do líder é reconstruída dos fills, sempre não agregados. Na seleção, quebra de continuidade torna a carteira inelegível. Na avaliação, a mudança não observada é incorporada no fill seguinte e contada. Em nenhum caso a posição é remendada ou interpolada.

### ADR-0005 — o gate do piloto é verificação de consistência

- O gate tem quatro condições, é computado uma única vez e se recusa a ser recomputado com outros limites.
- O veredito de 30 dias segue as regras do congelamento, com ou sem piloto.
- Nenhum relatório apresenta o gate como evidência de que a cópia rende.

### ADR-0006 — dados em arquivos, hash pelo conteúdo

- Não há servidor de banco. Dado bruto não é editado; tabelas são arquivos Parquet sob o diretório de dados, que fica fora do git.
- O hash de um conjunto de dados é calculado do conteúdo em ordem canônica, nunca dos bytes do arquivo. Reescrever o mesmo conteúdo não muda o hash.
- Só `copylab.storage` conhece o diretório de dados e o formato dos arquivos. Livro-razão, seleção, simulador e analytics recebem dados já materializados e devolvem objetos ou texto: quem grava é a CLI.
- Linha dentro de uma janela congelada nunca é reescrita.

### Se uma decisão precisar mudar

Escreva um **ADR novo** declarando supersedência. ADRs são numerados e imutáveis: não edite nem apague o antigo. Use `specs/_templates/adr.md`.

Uma **errata** datada, acrescentada ao fim do ADR, corrige um fato e as consequências que dependiam dele, ou aponta para o ADR que o refina. O corpo do ADR não é tocado. Uma errata não pode alterar o que a seção Decisão determina nem inverter a escolha: isso exige ADR novo.

## 3. Convenções de código

- **Type hints obrigatórios**, inclusive nos testes. `mypy --strict` roda no CI. Sem `# type: ignore` sem comentário explicando.
- **`structlog`, nunca `print()`.** Toda saída observável passa por `copylab.logging.get_logger`.
- **Exceções da hierarquia do projeto:** `DataError`, `ConfigError`, `SimulationError` ou `LookaheadError`, de `copylab.exceptions`. Nunca `Exception` ou `ValueError` cru.
- **Tempo é inteiro de milissegundos UTC** do provedor ao relatório (RNF-07). A conversão para dia-calendário UTC acontece em um único módulo. Nenhum fuso local, nenhum `datetime` sem fuso.
- **Dinheiro é `float`**, com comparação de teste por tolerância explícita (`pytest.approx`), nunca igualdade exata (RNF-08).
- **Determinismo** (RNF-01). Mesmos dados e mesmos parâmetros produzem resultado idêntico. Toda aleatoriedade usa semente registrada. Nenhum `now()` dentro da lógica: o relógio da máquina é lido num único módulo, usado só pelo coletor, pela ingestão e pela CLI.
- **Configuração via `copylab.config.Settings`**, prefixo `COPYLAB_`. Nada de `os.getenv` espalhado, nada de constante mágica. Parâmetro pré-registrado vem do arquivo de parâmetros e de nenhum outro lugar.
- **Linha de 100 colunas**, `ruff` com `E, F, I, N, UP, B, SIM, RUF`.

### Testes

- **Fixtures de papel para seleção, simulador e analytics** (RNF-03). Séries construídas à mão, com resultado calculável no papel. Dado real de mercado não entra nesses testes.
- **A derivação do valor esperado vive no próprio teste, como comentário.** Quem revisa precisa auditar a conta sem refazê-la à parte.
- Se a fixture e a implementação discordarem, confira a conta à mão antes de mexer em qualquer um dos dois.
- Cobertura mínima de **85%, com ramos, em seleção, simulador, analytics e no livro-razão do líder** (RNF-02).
- Marque todo teste com `@pytest.mark.unit` ou `@pytest.mark.integration`. A suíte default roda **offline** (RNF-06).
- Teste comportamento observável, não detalhe interno.
- Um teste novo de invariante só vale depois de provar que tem dente: quebre o código de propósito, veja o teste cair, restaure, e registre a mutação na docstring.

### Commits

- **Pequenos e explícitos.** Um assunto por commit, mensagem no imperativo, dizendo também **por quê**.
- **Nunca `git add .`**, nem `git add -A`, nem `git commit -a`. Adicione cada arquivo pelo caminho.
- Prefixos: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.
- Não commite dado de mercado nem `.env`. Arquivos de congelamento e relatórios de veredito são commitados de propósito.
- Não reescreva histórico já publicado.

### Honestidade de resultado

Um número ruim é um resultado. Se a cópia perde para comprar e manter BTC, o relatório diz isso. Se taxa ou slippage estão em zero, o relatório sinaliza que o cenário é irrealista. Todo relatório declara os vieses de RF-ANA-06.

Um resultado bom demais merece mais desconfiança que um ruim: suspeite primeiro de lookahead ou de erro de fator, antes de suspeitar que a estratégia é boa.

Nunca ajuste uma premissa, uma janela ou um limiar para melhorar um resultado.

## 4. Comandos

`make install` · `make check`

`make check` é o portão local: encadeia `lint`, `typecheck` e `test`, exatamente o que o CI roda. Rode antes de qualquer commit.

| Comando | O que faz |
|---|---|
| `make install` | Instala dependências de runtime e de desenvolvimento |
| `make test` | Suíte default com cobertura (integração desmarcada) |
| `make test-unit` / `make test-integration` | Recortes por marcador |
| `make lint` / `make format` | `ruff check` / `ruff format` |
| `make typecheck` | `mypy --strict` |
| `make audit` | `pip-audit` nas dependências instaladas |
| `make check` | **lint + typecheck + test** |
| `make clean` | Remove caches e artefatos |

Dependências entram por `uv add` (ou `uv add --dev`), nunca editando `pyproject.toml` na mão sem atualizar `uv.lock`.

## 5. Antes de dizer que terminou

- [ ] `make check` passa, sem passo vermelho e sem teste pulado sem justificativa
- [ ] A spec correspondente está aprovada e o que foi feito não a extrapola
- [ ] Os critérios de aceitação citados têm teste que falharia sem a mudança
- [ ] Nenhum ADR foi violado
- [ ] Nada foi implementado por adiantamento, fora do escopo da tarefa
- [ ] `docs/STATE.md` e `HANDOFF.md` refletem o que mudou

Se algo ficou por fazer, diga o que e por quê. Não relate como concluído.
