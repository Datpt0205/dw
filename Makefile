# ===========================================================================
# Digital Worker Platform — developer commands
# Requires: uv, pnpm, GNU make, docker (for infra/docker targets)
# Run inside Git Bash on Windows.
# ===========================================================================

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# Load local .env (if present) and export its variables to all recipes.
ifneq (,$(wildcard .env))
include .env
export
endif

COMPOSE := docker compose --env-file .env -f infra/compose/docker-compose.yml

.PHONY: help bootstrap infra-up infra-down dev docker-up docker-down \
        db-migrate db-seed migrate seed lint format typecheck \
        test-unit test-integration test-architecture test-contract \
        test-e2e test-all eval-smoke test-eval-smoke \
        generate-contracts release-manifest ci

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- bootstrap --
bootstrap: ## Install all Python + Node dependencies and local config
	uv sync --all-packages
	pnpm install
	@if [ ! -f .env ]; then cp .env.example .env && echo ">> created .env from .env.example — fill in secrets"; fi
	-uv run pre-commit install
	@echo ">> bootstrap complete"

# -------------------------------------------------------------------- infra --
infra-up: ## Start data plane (Postgres/Qdrant/Valkey/MinIO/Keycloak) in Docker
	$(COMPOSE) --profile infra up -d --wait

infra-down: ## Stop data plane containers (volumes preserved)
	$(COMPOSE) --profile infra down

docker-up: ## Build and start the FULL stack (infra + api + worker + web)
	$(COMPOSE) --profile full up --build -d --wait

docker-down: ## Stop the full stack
	$(COMPOSE) --profile full down

# ----------------------------------------------------------------- database --
db-migrate: ## Run database migrations (alias: migrate)
	uv run alembic -c db/alembic.ini upgrade head

migrate: db-migrate ## Alias for db-migrate

db-seed: ## Seed demo tenants/users/data (idempotent; available from phase 1)
	@if [ -f scripts/seed_demo.py ]; then \
		uv run python scripts/seed_demo.py; \
	else \
		echo "ERROR: scripts/seed_demo.py arrives in phase 1 (see docs/implementation/IMPLEMENTATION_PLAN.md)"; \
		exit 1; \
	fi

seed: db-seed ## Alias for db-seed

# ---------------------------------------------------------------------- dev --
dev: ## Run API + worker + web locally (infra must be up)
	bash scripts/dev.sh

# ------------------------------------------------------------------ quality --
format: ## Auto-format Python + TypeScript
	uv run ruff format .
	uv run ruff check --fix .
	pnpm run format

lint: ## Lint Python + TypeScript (no writes)
	uv run ruff check .
	uv run ruff format --check .
	pnpm run format:check
	pnpm run -r --if-present lint

typecheck: ## Type-check Python (mypy strict) + TypeScript (tsc)
	uv run mypy
	pnpm run -r --if-present typecheck

# -------------------------------------------------------------------- tests --
test-unit: ## Fast unit tests (no external services)
	uv run pytest -m unit

test-integration: ## Integration tests (requires `make infra-up` first)
	uv run pytest -m integration

test-architecture: ## Import-boundary + declared-dependency checks
	uv run lint-imports
	uv run python scripts/verify_architecture.py

test-contract: ## API/event/tool contract tests
	uv run pytest -m contract || test $$? -eq 5  # exit 5 = no tests collected yet

test-e2e: ## End-to-end vertical slice tests (requires full stack)
	uv run pytest -m e2e || test $$? -eq 5

eval-smoke: ## Evaluation smoke suite (available from phase 5)
	@if [ -f scripts/run_evals.py ]; then \
		uv run python scripts/run_evals.py --smoke; \
	else \
		echo "ERROR: scripts/run_evals.py arrives in phase 5 (see docs/implementation/IMPLEMENTATION_PLAN.md)"; \
		exit 1; \
	fi

test-eval-smoke: eval-smoke ## Alias for eval-smoke

test-all: test-unit test-architecture test-contract test-integration test-e2e ## Everything except evals

# ---------------------------------------------------------------- contracts --
generate-contracts: ## Export OpenAPI snapshot + regenerate TS types
	uv run python scripts/generate_contracts.py
	pnpm exec openapi-typescript contracts/openapi/openapi.json \
		-o packages/typescript/api-client/src/generated/schema.d.ts

release-manifest: ## Generate the immutable release manifest (phase 5)
	@if [ -f scripts/release_manifest.py ]; then \
		uv run python scripts/release_manifest.py; \
	else \
		echo "ERROR: scripts/release_manifest.py arrives in phase 5"; \
		exit 1; \
	fi

# ----------------------------------------------------------------------- ci --
ci: lint typecheck test-unit test-architecture test-contract ## Local CI gate (grows per phase)
	@echo ">> local CI gate passed"
