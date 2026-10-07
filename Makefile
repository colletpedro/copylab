# Makefile do copylab.
#
# `make check` é o portão local e roda exatamente os mesmos alvos que o job
# "quality" do CI (.github/workflows/ci.yml) invoca: lint, typecheck, test.
# Se divergirem, o CI é a fonte da verdade e este arquivo está errado.
#
# Não há alvos `up`, `down` e `logs`: não existe serviço. Os dados ficam em
# arquivos Parquet sob COPYLAB_DATA_DIR, sem servidor de banco (ADR-0006).

SHELL := /bin/bash

UV  ?= uv
RUN := $(UV) run

.DEFAULT_GOAL := help

.PHONY: help install test test-unit test-integration \
        lint format typecheck audit check clean

help: ## Lista os alvos disponíveis
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ─── Ambiente ────────────────────────────────────────────────────────────────

install: ## Instala dependências de runtime e de desenvolvimento
	$(UV) sync --all-groups

# ─── Testes ──────────────────────────────────────────────────────────────────

test: ## Suíte default (integração desmarcada) com cobertura — o que o CI roda
	$(RUN) pytest --cov --cov-report=term-missing --cov-report=xml

test-unit: ## Apenas os testes marcados como unit
	$(RUN) pytest -m unit

test-integration: ## Apenas os testes marcados como integration
	@# pytest devolve 5 quando não coleta nada. Na Fase 0 ainda não existe
	@# teste de integração, e um alvo vermelho por ausência seria ruído.
	@# REMOVER esta tolerância assim que o primeiro teste de integração entrar:
	@# a partir daí, "nenhum teste coletado" significa que a suíte sumiu.
	@$(RUN) pytest -m integration; status=$$?; \
		if [ $$status -eq 5 ]; then \
			echo "Nenhum teste de integração ainda (Fase 0)."; exit 0; \
		fi; \
		exit $$status

# ─── Qualidade ───────────────────────────────────────────────────────────────

lint: ## ruff check + verificação de formatação
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Aplica formatação e correções automáticas do ruff
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## mypy --strict (RNF-05)
	$(RUN) mypy src tests

audit: ## Vulnerabilidades conhecidas nas dependências instaladas
	@# --skip-editable pula o próprio copylab, que não está publicado no PyPI.
	$(RUN) pip-audit --skip-editable

check: lint typecheck test ## Portão local completo — espelha o job "quality" do CI

# ─── Limpeza ─────────────────────────────────────────────────────────────────

clean: ## Remove caches, artefatos de build e relatórios de cobertura
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build
	rm -f .coverage .coverage.* coverage.xml
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
