.PHONY: help install test lint format format-check type-check docs clean pre-commit coverage check-all

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies using Poetry
	poetry install

install-dev: ## Install all dependencies including dev
	poetry install --with dev

test: ## Run tests with pytest
	poetry run pytest

test-verbose: ## Run tests with verbose output
	poetry run pytest -v

coverage: ## Run tests with coverage report
	poetry run pytest --cov --cov-report=html --cov-report=term

lint: ## Run Ruff linter
	poetry run ruff check .

lint-fix: ## Run Ruff linter with auto-fix
	poetry run ruff check --fix .

format: ## Format code with Ruff
	poetry run ruff format .

format-check: ## Check if code is formatted
	poetry run ruff format --check .

type-check: ## Run mypy type checker
	poetry run mypy photos_manager/

docstring-check: ## Check docstring coverage with interrogate
	poetry run interrogate -v photos_manager/

docstring-badge: ## Generate docstring coverage badge
	poetry run interrogate -v --generate-badge . photos_manager/

pre-commit: ## Run all pre-commit hooks
	poetry run pre-commit run --all-files

pre-commit-install: ## Install pre-commit hooks
	poetry run pre-commit install

docs-serve: ## Serve documentation locally
	poetry run mkdocs serve

docs-build: ## Build documentation
	poetry run mkdocs build

clean: ## Clean up generated files
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf site/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete

check-all: lint format-check type-check docstring-check test pre-commit ## Run all quality checks

build: ## Build the package
	poetry build

run: ## Run the CLI application
	poetry run photos --help

ci: lint type-check docstring-check test ## Run CI pipeline locally

update: ## Update dependencies
	poetry update

lock: ## Update lock file without upgrading dependencies
	poetry lock --no-update

shell: ## Open a Poetry shell
	poetry shell

version: ## Show current version
	poetry run photos version
