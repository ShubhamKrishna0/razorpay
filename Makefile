# Convenience targets. Everything here also works as a plain shell command.

.PHONY: help install backend frontend dev test bench seed clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt
	cd backend && cp -n .env.example .env || true
	cd frontend && npm install && cp -n .env.example .env || true

backend: ## Run the API on :8000
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

frontend: ## Run the dashboard on :5173
	cd frontend && npm run dev

test: ## Run the backend test suite
	cd backend && .venv/bin/python -m pytest

bench: ## Run the benchmark sweep from the CLI
	cd backend && .venv/bin/python -m app.cli benchmark --sizes 1000,10000,100000

seed: ## Generate a dataset and reconcile it from the CLI
	cd backend && .venv/bin/python -m app.cli demo --size 25000

clean: ## Remove generated artifacts
	rm -rf backend/var frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
