# O que muda

<!-- Uma frase. O quê, não como. -->

## Spec correspondente

<!-- Link para a spec e a seção. Ex.: specs/00-plataforma/fase-1-requirements.md §4.5 -->

- **Spec:**
- **RFs cobertos:**
- **Critérios de aceitação verificados:**

---

## Checklist de gate

Este repositório é spec-driven. Um item não marcado é um gate reprovado, não uma
pendência a resolver depois do merge.

### Spec

- [ ] A spec correspondente existe, está **aprovada** e o PR não a extrapola
- [ ] Se o PR mudou o entendimento do problema, a spec foi atualizada **antes** do código
- [ ] `specs/README.md` reflete o estado real dos gates deste módulo

### ADRs

- [ ] Li **todos** os ADRs em `specs/adr/` e o PR não viola nenhum
- [ ] **ADR-0001** — nenhuma chave privada, assinatura ou endpoint de ordem no código
      (`test_architecture_read_only` verde); respeita 1.200 de peso por minuto por IP;
      a posição do líder é reconstruída dos fills e a quebra de continuidade torna a
      carteira inelegível, nunca é remendada
- [ ] **ADR-0002** — após as ordens de um evento, exposição bruta ≤ teto × patrimônio;
      ordem abaixo do mínimo não é enviada e a diferença persiste; zerar é sempre
      executável; a variante só compras é o mesmo motor com alvos negativos zerados
- [ ] **ADR-0003** — uma ordem executada em τ só depende de eventos do líder com
      instante ≤ τ − Δ; o preço do fill do líder nunca é o do seguidor; nenhum preço
      é interpolado ou inventado
- [ ] **ADR-0004** — a seleção com corte T lê só dado anterior a T e só endereço e
      patrimônio do leaderboard; a avaliação recusa rodar sem congelamento ou com hash
      divergente; nenhuma janela de avaliação foi lida antes do congelamento e nenhum
      parâmetro pré-registrado mudou depois de uma janela lida
- [ ] **ADR-0005** — o gate do piloto tem as quatro condições, é computado uma única
      vez e nenhum relatório o apresenta como evidência de que a cópia rende
- [ ] Se uma decisão arquitetural mudou, há um **novo ADR** declarando supersedência
      (o anterior não foi editado nem removido)

### Testes

- [ ] Cada critério de aceitação citado acima tem um teste que falharia sem esta mudança
- [ ] Teste de invariante novo provou ter dente (quebrei o código de propósito, vi o
      teste cair, restaurei) e a mutação está na docstring
- [ ] Testes de seleção, simulador e analytics usam **fixtures de papel**, com a conta
      derivada no próprio teste (RNF-03), não dado real de mercado
- [ ] Cobertura ≥ 85%, com ramos, em seleção, simulador e analytics (RNF-02)
- [ ] Comparações de valores monetários usam tolerância explícita (`pytest.approx`),
      nunca igualdade exata (RNF-08)
- [ ] A suíte default continua rodando offline (RNF-06)

### Qualidade

- [ ] `make check` passa localmente
- [ ] Type hints em tudo; `mypy --strict` limpo (RNF-05)
- [ ] Nenhum `print()` — saída observável passa por `structlog`
- [ ] Exceções são `DataError`, `ConfigError` ou `SimulationError`, nunca `Exception`
      ou `ValueError` cru
- [ ] Tempo é inteiro de milissegundos UTC, sem `datetime` sem fuso (RNF-07)
- [ ] Mesma entrada produz mesma saída; aleatoriedade com semente registrada; nenhum
      `now()` na lógica (RNF-01)
- [ ] Parâmetro pré-registrado vem do arquivo de parâmetros, não de constante nem de
      variável de ambiente

### Documentação

- [ ] `specs/CHANGELOG.md` atualizado se alguma spec ou ADR mudou de versão/status
- [ ] `docs/STATE.md` e `HANDOFF.md` refletem o que mudou
- [ ] `README.md` atualizado se mudou o modo de rodar, a estrutura ou as limitações
- [ ] Novos vieses ou premissas estão declarados (RF-ANA-06)

---

## Como verificar

<!-- Comandos exatos para reproduzir o resultado. Se o PR muda um número de
     simulação, cole o antes e o depois. -->

## Fora de escopo

<!-- O que foi deliberadamente deixado de fora, e para qual fase. -->
