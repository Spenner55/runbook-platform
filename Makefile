.PHONY: up up-d down restart reset logs logs-api logs-web logs-runner logs-ai \
        ps migrate makemigrations makemigrations-app \
        test test-api test-api-v test-api-app test-runner test-web test-web-file \
        test-approvals test-artifacts test-audit test-auditor test-changes test-common \
        test-evidence test-executions test-integrations test-organizations test-policies \
        test-runbooks test-users test-workflows \
        seed-dev seed-execution-smoke \
        format format-check format-check-api format-check-ai format-check-runner format-check-web \
        lint lint-api lint-ai lint-runner lint-web lint-fix \
        check-prod check-migrations security-scan hardening-check bootstrap help \
        ci ci-full \
        api-shell ai-shell runner-shell web-shell db-shell \
        start-db stop-db start-api stop-api start-web stop-web start-runner stop-runner start-ai stop-ai

# ── Compose lifecycle ─────────────────────────────────────────────────────────

up: ## Build images and start all services (foreground)
	docker compose up --build

up-d: ## Build images and start all services (detached)
	docker compose up --build -d

down: ## Stop and remove containers (volumes preserved)
	docker compose down

stop: ## Stop containers without removing them
	docker compose stop

start: ## Start existing containers
	docker compose start

restart: ## Restart containers without rebuilding images
	docker compose restart

reset: ## DESTRUCTIVE: wipe volumes, rebuild, migrate, seed
	@echo "WARNING: This will delete all local data. Press Ctrl-C to abort."
	@sleep 3
	docker compose down --volumes
	docker compose up --build -d
	docker compose exec api python manage.py wait_for_db
	docker compose exec api python manage.py migrate
	docker compose exec api python manage.py seed_dev

# ── Logs ──────────────────────────────────────────────────────────────────────

logs: ## Tail logs for all services
	docker compose logs -f

logs-api: ## Tail logs for the api service
	docker compose logs -f api

logs-web: ## Tail logs for the web service
	docker compose logs -f web

logs-runner: ## Tail logs for the runner service
	docker compose logs -f runner

logs-ai: ## Tail logs for the ai service
	docker compose logs -f ai

# ── Status ────────────────────────────────────────────────────────────────────

ps: ## Show container status
	docker compose ps

# ── Database / migrations ─────────────────────────────────────────────────────

migrate: ## Apply pending Django migrations
	docker compose exec api python manage.py migrate

makemigrations: ## Generate migrations for all apps
	docker compose exec api python manage.py makemigrations

makemigrations-app: ## Generate migrations for APP= (e.g. make makemigrations-app APP=runbooks)
	docker compose exec api python manage.py makemigrations $(APP)

# ── Tests ─────────────────────────────────────────────────────────────────────

test-api: ## Run Django pytest suite
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest

test-api-v: ## Run Django pytest suite (verbose)
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest -v

test-api-app: ## Run Django tests for one app: make test-api-app APP=runbooks
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/$(APP)/tests/

test-approvals: ## Run approvals app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/approvals/tests/

test-artifacts: ## Run artifacts app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/artifacts/tests/

test-audit: ## Run audit app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/audit/tests/

test-auditor: ## Run auditor app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/auditor/tests/

test-changes: ## Run changes app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests/

test-common: ## Run common app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/common/tests/

test-evidence: ## Run evidence app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/evidence/tests/

test-executions: ## Run executions app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/executions/tests/

test-integrations: ## Run integrations app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/integrations/tests/

test-organizations: ## Run organizations app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/organizations/tests/

test-policies: ## Run policies app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/policies/tests/

test-runbooks: ## Run runbooks app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/runbooks/tests/

test-users: ## Run users app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/users/tests/

test-workflows: ## Run workflows app tests
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/workflows/tests/

test-runner: ## Run runner pytest suite
	docker compose exec runner pytest

test-web: ## Run web Vitest suite (single run)
	docker compose exec web npm test -- --run

test-web-file: ## Run a single web test file: make test-web-file FILE=src/routes/executions/ExecutionsPage.test.tsx
	docker compose exec web npm test -- --run $(FILE)

test: ## Run all test suites (API, runner, web)
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest
	docker compose exec runner pytest
	docker compose exec web npm test -- --run

# ── Seed data ─────────────────────────────────────────────────────────────────

seed-dev: ## Seed local database with development data (idempotent)
	docker compose exec api python manage.py seed_dev

seed-execution-smoke: ## Re-queue smoke test executions (idempotent fast reset)
	docker compose exec api python manage.py seed_dev --execution-smoke

# ── Code quality ──────────────────────────────────────────────────────────────

format: ## Auto-format all Python and TypeScript code
	docker compose exec api ruff format /app
	docker compose exec ai ruff format /app
	docker compose exec runner ruff format /app
	docker compose exec web npm run format

lint: ## Lint all Python and TypeScript code (read-only)
	docker compose exec api ruff check /app
	docker compose exec ai ruff check /app
	docker compose exec runner ruff check /app
	docker compose exec web npm run lint

lint-api: ## Ruff lint check for the api service only
	docker compose exec api ruff check /app

lint-ai: ## Ruff lint check for the ai service only
	docker compose exec ai ruff check /app

lint-runner: ## Ruff lint check for the runner service only
	docker compose exec runner ruff check /app

lint-web: ## ESLint check for the web service only
	docker compose exec web npm run lint

format-check: ## Check formatting across all services without writing changes
	docker compose exec api ruff format --check /app
	docker compose exec ai ruff format --check /app
	docker compose exec runner ruff format --check /app
	docker compose exec web npm run format:check

format-check-api: ## Check ruff formatting for the api service only
	docker compose exec api ruff format --check /app

format-check-ai: ## Check ruff formatting for the ai service only
	docker compose exec ai ruff format --check /app

format-check-runner: ## Check ruff formatting for the runner service only
	docker compose exec runner ruff format --check /app

format-check-web: ## Check prettier formatting for the web service only
	docker compose exec web npm run format:check

lint-fix: ## Auto-fix lint errors across all Python and TypeScript code
	docker compose exec api ruff check /app --fix
	docker compose exec ai ruff check /app --fix
	docker compose exec runner ruff check /app --fix
	docker compose exec web npx eslint . --fix

check-prod: ## Run Django production deployment checks with local-only env values
	docker compose exec \
	  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
	  -e DJANGO_SECRET_KEY=local-prod-check-secret-value-0123456789abcdefghijklmnopqrstuvwxyz-NOT-SECRET \
	  -e DATABASE_URL=postgresql://postgres:postgres@pgbouncer:5432/runbook_platform \
	  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,api \
	  -e CORS_ALLOWED_ORIGINS=http://localhost:5173 \
	  -e RUNNER_REGISTRATION_TOKEN=local-prod-check-runner-token \
	  -e CHANGE_DISPATCH_TOKEN_SECRET=local-prod-check-dispatch-token-secret \
	  -e INTEGRATION_FERNET_KEY=local-prod-check-fernet-key \
	  api python manage.py check --deploy --settings=config.settings.prod

check-migrations: ## Check model changes have migrations and no unapplied migrations remain
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api python manage.py makemigrations --check --dry-run
	docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api python manage.py migrate --check

security-scan: ## Run local dependency, npm, secret, and filesystem vulnerability scans
	docker compose exec api sh -c "python -m pip install --quiet pip-audit && pip-audit --progress-spinner off -r requirements/dev.txt && pip-audit --progress-spinner off -r requirements/prod.txt"
	docker compose exec ai sh -c "python -m pip install --quiet pip-audit && pip-audit --progress-spinner off -r requirements/dev.txt"
	docker compose exec runner sh -c "python -m pip install --quiet pip-audit && pip-audit --progress-spinner off -r requirements/dev.txt && pip-audit --progress-spinner off -r requirements.txt"
	docker compose exec web npm audit --audit-level=high
	docker run --rm -v "$$PWD:/repo" zricethezav/gitleaks:v8.24.2 detect --source=/repo --redact --no-git --verbose
	docker run --rm -v "$$PWD:/repo" aquasec/trivy:0.58.2 fs --exit-code 1 --severity HIGH,CRITICAL --scanners vuln --ignore-unfixed /repo

hardening-check: check-prod check-migrations security-scan ## Run all local hardening validation gates

# ── CI pipeline ───────────────────────────────────────────────────────────────

ci: ## Run the CI pipeline locally: lint → format-check → all tests → migration checks → prod check
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) test
	$(MAKE) check-migrations
	$(MAKE) check-prod

ci-full: ## Run the full CI pipeline including security scans (slow)
	$(MAKE) ci
	$(MAKE) security-scan

# ── Bootstrap ─────────────────────────────────────────────────────────────────

bootstrap: ## First-time setup: build, start, wait for DB, migrate, seed
	docker compose up --build -d
	docker compose exec api python manage.py wait_for_db
	docker compose exec api python manage.py migrate
	docker compose exec api python manage.py seed_dev
	@echo ""
	@echo "System is ready."
	@echo "  Web:    http://localhost:5173"
	@echo "  API:    http://localhost:8000"
	@echo "  AI:     http://localhost:8001"

# ── Shells ────────────────────────────────────────────────────────────────────

api-shell: ## sh into the api container
	docker compose exec api sh

ai-shell: ## sh into the ai container
	docker compose exec ai sh

runner-shell: ## sh into the runner container
	docker compose exec runner sh

web-shell: ## sh into the web container
	docker compose exec web sh

db-shell: ## psql into the postgres container
	docker compose exec postgres psql -U postgres -d runbook_platform

# ── Individual service start/stop (for targeted restarts) ────────────────────

start-db: ## Start the postgres container
	docker compose start postgres

stop-db: ## Stop the postgres container
	docker compose stop postgres

start-api: ## Start the api container
	docker compose start api

stop-api: ## Stop the api container
	docker compose stop api

start-web: ## Start the web container
	docker compose start web

stop-web: ## Stop the web container
	docker compose stop web

start-runner: ## Start the runner container
	docker compose start runner

stop-runner: ## Stop the runner container
	docker compose stop runner

start-ai: ## Start the ai container
	docker compose start ai

stop-ai: ## Stop the ai container
	docker compose stop ai

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
