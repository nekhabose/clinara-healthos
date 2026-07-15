.PHONY: help up down build migrate makemigrations shell test lint fmt worker web api ci

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Start the local stack (postgres, redis, api, worker, web)
	docker compose up --build -d

down: ## Stop the local stack
	docker compose down

build: ## Build images
	docker compose build

migrate: ## Apply Django migrations
	docker compose run --rm api python manage.py migrate

makemigrations: ## Generate Django migrations
	docker compose run --rm api python manage.py makemigrations

shell: ## Django shell
	docker compose run --rm api python manage.py shell

test: ## Run backend tests (includes the tenant-isolation harness)
	docker compose run --rm api pytest

lint: ## Ruff + mypy
	docker compose run --rm api sh -c "ruff check . && mypy ."

fmt: ## Format code
	docker compose run --rm api ruff format .

worker: ## Run a Celery worker locally
	docker compose run --rm api celery -A clinara.celery worker -l info

ci: lint test ## What CI runs
