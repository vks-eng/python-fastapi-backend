# TaskForge API: developer shortcuts. Requires uv (https://docs.astral.sh/uv/) and,
# for the compose targets, Docker. Run `make help` for the list.
.DEFAULT_GOAL := help
RUN ?= uv run
COMPOSE ?= docker compose
MSG ?= describe change

.PHONY: help install dev lint format test cov migrate revision run up down logs seed seed-docker requirements clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies only
	uv sync --frozen --no-dev

dev: ## Install runtime + dev dependencies and git hooks
	uv sync --frozen
	$(RUN) pre-commit install || echo "pre-commit not installed; skipping hooks (pip install pre-commit)"

lint: ## Ruff lint + format check (same as CI)
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Auto-fix lint issues and format code
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

test: ## Run the test suite (TEST_DATABASE_URL or embedded pgserver)
	$(RUN) pytest

cov: ## Run tests with coverage report (fails under 85%)
	$(RUN) pytest --cov --cov-report=term-missing --cov-report=html

migrate: ## Apply database migrations (alembic upgrade head)
	$(RUN) alembic upgrade head

revision: ## Create a migration: make revision MSG="add column"
	$(RUN) alembic revision --autogenerate -m "$(MSG)"

run: ## Run the API locally with auto-reload
	$(RUN) uvicorn app.main:app --reload --port 8000

up: ## Build and start api + postgres + redis (runs migrations first)
	$(COMPOSE) up --build -d

down: ## Stop the compose stack
	$(COMPOSE) down

logs: ## Tail API logs
	$(COMPOSE) logs -f api

seed: ## Load demo users/tasks into the local database (dev only)
	$(RUN) python -m app.cli seed

seed-docker: ## Load demo users/tasks inside the compose stack (dev only)
	$(COMPOSE) run --rm -e ENVIRONMENT=development api python -m app.cli seed

requirements: ## Re-export requirements*.txt from uv.lock
	uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt
	{ echo "# Test / lint dependencies. Install with: pip install -r requirements-dev.txt"; \
	  echo "-r requirements.txt"; \
	  uv export --frozen --only-group dev --no-hashes --no-emit-project; } > requirements-dev.txt

clean: ## Remove caches and coverage artifacts
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
