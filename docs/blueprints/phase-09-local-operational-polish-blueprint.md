# Phase 09 Blueprint: Local Operational Polish

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 09 |
| Objective | Make the local development environment fast, repeatable, and consistent across machines — without touching production infra. |
| Status | Implemented; retained as planning blueprint |
| Depends on | Phases 01–08 (domain models, service layer, APIs, runner, React slice, tests) |
| Authored | 2026-04-15 |
| Repo root reviewed | `/home/dylan/code/runbook-platform` |
| In scope | Makefile improvements, seed data system, pre-commit hooks, Python + JS/TS linting/formatting stack, Docker-first workflow enforcement |
| Out of scope | CI/CD pipeline changes beyond `ci.yml` linting gates, production deployment, AWS infra, container security hardening, secrets management, feature flags |

### Current repo alignment notes

As of 2026-04-27, the root Makefile includes local lifecycle, migration, test, seed, lint, format, shell, and per-service start/stop targets. `seed_dev`, `wait_for_db`, ruff, Prettier, ESLint, Vitest, and CI gates are present. Current local workflow is documented in `docs/runbooks/local-development.md`.

---

## 2. Executive Summary

The system is functionally complete through phase 08. The developer experience is not. Running the system requires remembering undocumented commands, there is no canonical seed data so every dev starts with an empty database, formatting is unenforced and will diverge across contributors, and the Makefile is missing a dozen day-to-day targets.

This phase delivers four things in strict priority order:

1. **Makefile** — a single, documented interface to every common operation. Devs never need to remember raw `docker compose` invocations.
2. **Seed data** — one Django management command (`seed_dev`) that populates a usable local state in under five seconds.
3. **Linting/formatting stack** — `ruff` for Python, `eslint` + `prettier` for TypeScript, both wired into Makefile targets.
4. **pre-commit** — hooks that enforce formatting and catch trailing whitespace before a commit lands. The CI gate is downstream; pre-commit is the fast local gate.

Everything runs inside Docker. No tool needs to be installed on the host beyond `docker` and `make`.

---

## 3. Current State Analysis

### 3.1 Makefile

```
# apps/api/Makefile — current state (13 targets)
up, up-d, down, restart, logs, ps,
api-shell, ai-shell, runner-shell, web-shell, db-shell,
migrate, makemigrations, bootstrap
```

**Gaps:**
- No `test-api`, `test-runner`, or `test-web` targets — devs must remember full `docker compose exec` invocations.
- No `format` or `lint` targets — no single command to apply or check style.
- No `seed-dev` target.
- `bootstrap` is silent about what it does and has no `--wait` guard for Postgres healthcheck.
- `restart` does a full `down && up --build` which rebuilds images unnecessarily; a `docker compose restart` is faster when images haven't changed.
- `makemigrations` has no app-name variant.
- No `.PHONY` declaration — targets with file-name collisions would silently no-op.

### 3.2 Seed data

No management command exists. No fixture files exist. Every developer who runs `make bootstrap` gets a completely empty database. This means:
- Manual SQL or API calls required to do anything meaningful in the UI.
- Tests that depend on "known state" have to create their own fixtures.
- Demo and onboarding are blocked.

### 3.3 Linting / formatting

**Python (api, ai, runner):**
- No `ruff`, `black`, or `isort` configured.
- No `pyproject.toml` at the repo root or per-service.
- `apps/api/requirements/dev.txt` lists only `pytest` and `pytest-django` — no formatter or linter.

**TypeScript (web):**
- ESLint is installed (`eslint ^9.39.4`) and `eslint.config.js` exists.
- No `prettier` — no auto-formatting enforced.
- No `format` script in `apps/web/package.json`.

### 3.4 Pre-commit

No `.pre-commit-config.yaml` exists. No git hooks are configured beyond samples in `.git/hooks/`.

### 3.5 Docker workflow

`docker-compose.yml` is correctly structured with healthchecks and volume mounts. The main gap is that the `bootstrap` target doesn't guard against the API container not being ready before running migrations (the healthcheck on `postgres` is correct, but the API service itself might not have finished starting).

### 3.6 CI

`ci.yml` runs `npm run build` and `python -m compileall`. It does not run:
- Any linter (eslint, ruff)
- Any formatter check
- Any test suite

This is acceptable for this phase — we'll add lint gates to CI as a verification step at the end.

---

## 4. Target Developer Workflow (End-to-End)

After this phase, the full day-one developer workflow is:

```bash
# 1. Clone and configure
git clone <repo>
cd runbook-platform
cp .env.example .env          # edit DJANGO_SECRET_KEY, RUNNER_REGISTRATION_TOKEN

# 2. Install pre-commit (one-time, host-side only)
pip install pre-commit
pre-commit install             # installs .git/hooks/pre-commit

# 3. Start the system
make bootstrap                 # build images + start services + migrate + seed

# 4. Verify everything is running
make ps                        # shows all containers healthy
make logs                      # optional: tail combined logs

# 5. Develop
# Edit files — hot-reload is active for api (Django runserver), web (Vite HMR), ai (uvicorn --reload)

# 6. Format before committing
make format                    # runs ruff format + prettier write
make lint                      # must exit 0 before pushing

# 7. Run tests
make test-api                  # Django pytest
make test-runner               # runner pytest

# 8. Reset to clean state
make reset                     # down --volumes + bootstrap (destructive: wipes DB)
```

Every command above runs inside Docker. The only host dependency is `docker`, `make`, and optionally `pre-commit` for the git hook.

---

## 5. Makefile Design

### 5.1 Principles

- All targets are `.PHONY`.
- Every target has a `## comment` for `make help` auto-generation.
- Docker is the executor — no raw `python` or `npm` calls that bypass the container.
- `bootstrap` is the safe "from nothing" entry point.
- `reset` is the destructive "nuke and rebuild" entry point; it is clearly named.
- Targets compose (`format` calls sub-targets, `lint` calls sub-targets).

### 5.2 Target breakdown

#### `up`
- **Purpose**: Build images (if stale) and start all services in the foreground.
- **Command**: `docker compose up --build`
- **Notes**: Use for initial startup or when you want to watch logs. `--build` ensures images are fresh but is slower than `docker compose up` without it for iterative runs. Acceptable here because the use-case is first-run.

#### `up-d`
- **Purpose**: Same as `up` but detached (background).
- **Command**: `docker compose up --build -d`

#### `down`
- **Purpose**: Stop and remove containers. Does NOT remove volumes.
- **Command**: `docker compose down`

#### `restart`
- **Purpose**: Restart containers without rebuilding images. Faster than `down + up --build`.
- **Command**: `docker compose restart`
- **Notes**: Use when you changed `.env` or config but did not change `Dockerfile` or `requirements.txt`. If `requirements.txt` changed, use `up` or `up-d` instead.

#### `reset`
- **Purpose**: Full teardown including volumes, then bootstrap from scratch. Destructive — wipes the database.
- **Command**: `docker compose down --volumes && docker compose up --build -d && docker compose exec api python manage.py migrate && docker compose exec api python manage.py seed_dev`
- **Notes**: Named `reset`, not `clean`, to signal that data is lost. Should print a warning line.

#### `logs`
- **Purpose**: Tail combined logs for all services.
- **Command**: `docker compose logs -f`

#### `logs-api` / `logs-web` / `logs-runner` / `logs-ai`
- **Purpose**: Tail logs for a single service.
- **Commands**: `docker compose logs -f api`, etc.

#### `ps`
- **Purpose**: Show container status.
- **Command**: `docker compose ps`

#### `migrate`
- **Purpose**: Apply pending Django migrations.
- **Command**: `docker compose exec api python manage.py migrate`
- **Prereq**: API container must be running.

#### `makemigrations`
- **Purpose**: Generate new Django migrations (all apps).
- **Command**: `docker compose exec api python manage.py makemigrations`

#### `makemigrations-app`
- **Purpose**: Generate migrations for a specific app (passed via `APP=` variable).
- **Command**: `docker compose exec api python manage.py makemigrations $(APP)`
- **Usage**: `make makemigrations-app APP=runbooks`

#### `test-api`
- **Purpose**: Run the full Django pytest suite inside the API container.
- **Command**: `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest`
- **Notes**: Passes the test settings module via env var so the container doesn't need to be rebuilt.

#### `test-api-v`
- **Purpose**: Same as `test-api` with verbose output (`-v`).
- **Command**: `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest -v`

#### `test-runner`
- **Purpose**: Run the runner pytest suite inside the runner container.
- **Command**: `docker compose exec runner pytest`

#### `seed-dev`
- **Purpose**: Populate the database with canonical development seed data.
- **Command**: `docker compose exec api python manage.py seed_dev`
- **Notes**: The management command is idempotent — running it twice does not create duplicates.

#### `format`
- **Purpose**: Apply auto-formatting to all Python and TypeScript code.
- **Sub-commands**:
  - `docker compose exec api ruff format /app`
  - `docker compose exec ai ruff format /app`
  - `docker compose exec runner ruff format /app`
  - `docker compose exec web npm run format`

#### `lint`
- **Purpose**: Check formatting and lint rules without modifying files. Must exit 0 for CI.
- **Sub-commands**:
  - `docker compose exec api ruff check /app`
  - `docker compose exec ai ruff check /app`
  - `docker compose exec runner ruff check /app`
  - `docker compose exec web npm run lint`

#### `bootstrap`
- **Purpose**: The canonical first-run entry point. Builds images, starts services, waits for readiness, migrates, seeds.
- **Command sequence**:
  1. `docker compose up --build -d`
  2. `docker compose exec api python manage.py wait_for_db` (see §6.4)
  3. `docker compose exec api python manage.py migrate`
  4. `docker compose exec api python manage.py seed_dev`
- **Notes**: After this command, the system is fully ready. No additional manual steps required.

#### `help`
- **Purpose**: Print all available targets with their descriptions.
- **Implementation**: `grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'`

### 5.3 Full Makefile structure

```makefile
.PHONY: up up-d down restart reset logs logs-api logs-web logs-runner logs-ai \
        ps migrate makemigrations makemigrations-app \
        test-api test-api-v test-runner seed-dev \
        format lint bootstrap help \
        api-shell ai-shell runner-shell web-shell db-shell

# ── Compose lifecycle ─────────────────────────────────────────────────────────

up: ## Build images and start all services (foreground)
	docker compose up --build

up-d: ## Build images and start all services (detached)
	docker compose up --build -d

down: ## Stop and remove containers (volumes preserved)
	docker compose down

restart: ## Restart containers without rebuilding images
	docker compose restart

reset: ## DESTRUCTIVE: wipe volumes, rebuild, migrate, seed
	@echo "WARNING: This will delete all local data. Press Ctrl-C to abort."
	@sleep 3
	docker compose down --volumes
	docker compose up --build -d
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

test-runner: ## Run runner pytest suite
	docker compose exec runner pytest

# ── Seed data ─────────────────────────────────────────────────────────────────

seed-dev: ## Seed local database with development data
	docker compose exec api python manage.py seed_dev

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

# ── Bootstrap ─────────────────────────────────────────────────────────────────

bootstrap: ## First-time setup: build, start, migrate, seed
	docker compose up --build -d
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

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
```

---

## 6. Seed Data System Design

### 6.1 Philosophy

- Seed data is **idempotent** — `seed_dev` can be run multiple times without creating duplicates.
- Seed data is **realistic** — it uses real field values, not `test`, `foo`, `bar`.
- Seed data is **minimal** — one of each domain object, enough to navigate the UI end-to-end.
- The command lives in a dedicated Django app management command, not a fixture file, so it can use Python logic and service layer calls.

### 6.2 Seed data specification

```
Organization:
  name: "Acme Platform Engineering"
  slug: "acme-platform-eng"

Runbook:
  title: "Deploy to Production"
  description: "Standard procedure for deploying a new release to the production environment."
  organization: (above)

Workflow:
  name: "deploy-production-v1"
  runbook: (above)
  definition:
    name: "Deploy to Production"
    steps:
      - id: "check-health"
        name: "Pre-deploy health check"
        type: "shell"
        risk: "low"
        command: "curl -sf http://internal/health || exit 1"
        requiresApproval: false
      - id: "deploy"
        name: "Run deployment script"
        type: "shell"
        risk: "high"
        command: "./scripts/deploy.sh --env production"
        requiresApproval: true
      - id: "smoke-test"
        name: "Post-deploy smoke test"
        type: "shell"
        risk: "low"
        command: "pytest tests/smoke/ -q"
        requiresApproval: false

Execution (optional, created only if SEED_EXECUTION=1 env var is set):
  workflow: (above)
  status: "succeeded"
  triggered_by: "seed_dev"
```

### 6.3 Implementation: management command

**File**: `apps/api/apps/common/management/commands/seed_dev.py`

The command must:
1. Use `get_or_create` on a stable lookup field for every record (idempotency).
2. Call the service layer, not the ORM directly — this validates business logic.
3. Print a summary of what was created vs. already existed.
4. Accept an optional `--with-execution` flag.
5. Be safe to run in production (it must check `settings.DEBUG` and abort if false — seed data must never run against prod).

```python
"""
Management command: seed_dev

Populates the local development database with a minimal, canonical dataset.
Safe to run multiple times (idempotent via get_or_create).
Aborts if DEBUG is False.

Usage:
    python manage.py seed_dev
    python manage.py seed_dev --with-execution
"""
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Seed local development database with canonical test data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-execution",
            action="store_true",
            default=False,
            help="Also create a seed execution record.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev refuses to run when DEBUG=False. "
                "This command is for local development only."
            )

        from apps.organizations.models import Organization
        from apps.runbooks.models import Runbook
        from apps.workflows.models import Workflow

        # Organization
        org, org_created = Organization.objects.get_or_create(
            slug="acme-platform-eng",
            defaults={"name": "Acme Platform Engineering"},
        )
        self._report("Organization", org.name, org_created)

        # Runbook
        runbook, rb_created = Runbook.objects.get_or_create(
            title="Deploy to Production",
            organization=org,
            defaults={
                "description": (
                    "Standard procedure for deploying a new release "
                    "to the production environment."
                ),
            },
        )
        self._report("Runbook", runbook.title, rb_created)

        # Workflow
        workflow_definition = {
            "name": "Deploy to Production",
            "steps": [
                {
                    "id": "check-health",
                    "name": "Pre-deploy health check",
                    "type": "shell",
                    "risk": "low",
                    "command": "curl -sf http://internal/health || exit 1",
                    "requiresApproval": False,
                },
                {
                    "id": "deploy",
                    "name": "Run deployment script",
                    "type": "shell",
                    "risk": "high",
                    "command": "./scripts/deploy.sh --env production",
                    "requiresApproval": True,
                },
                {
                    "id": "smoke-test",
                    "name": "Post-deploy smoke test",
                    "type": "shell",
                    "risk": "low",
                    "command": "pytest tests/smoke/ -q",
                    "requiresApproval": False,
                },
            ],
        }
        workflow, wf_created = Workflow.objects.get_or_create(
            name="deploy-production-v1",
            runbook=runbook,
            defaults={"definition": workflow_definition},
        )
        self._report("Workflow", workflow.name, wf_created)

        # Optional execution
        if options["with_execution"]:
            from apps.executions.models import Execution
            execution, ex_created = Execution.objects.get_or_create(
                workflow=workflow,
                triggered_by="seed_dev",
                defaults={"status": "succeeded"},
            )
            self._report("Execution", str(execution.id), ex_created)

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))

    def _report(self, model, name, created):
        verb = "Created" if created else "Already exists"
        self.stdout.write(f"  [{verb}] {model}: {name}")
```

### 6.4 `wait_for_db` management command

The `bootstrap` target needs to wait for the API container's Django stack to be ready before running migrations. Django's runserver starts before the application is fully initialized on first build. Add a minimal `wait_for_db` command.

**File**: `apps/api/apps/common/management/commands/wait_for_db.py`

```python
"""
Management command: wait_for_db

Blocks until the configured database is reachable.
Used in bootstrap and CI before running migrations.

Usage:
    python manage.py wait_for_db
    python manage.py wait_for_db --timeout 60
"""
import time
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the database is available."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Maximum seconds to wait (default: 30).",
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]
        self.stdout.write("Waiting for database...")
        elapsed = 0
        while elapsed < timeout:
            try:
                connections["default"].ensure_connection()
                self.stdout.write(self.style.SUCCESS("Database ready."))
                return
            except OperationalError:
                time.sleep(1)
                elapsed += 1
        raise SystemExit(f"Database not ready after {timeout}s.")
```

**Update `bootstrap` in Makefile:**
```makefile
bootstrap:
	docker compose up --build -d
	docker compose exec api python manage.py wait_for_db
	docker compose exec api python manage.py migrate
	docker compose exec api python manage.py seed_dev
```

### 6.5 Management command directory structure

```
apps/api/apps/common/
├── __init__.py
├── models.py          (BaseModel — already exists)
└── management/
    ├── __init__.py
    └── commands/
        ├── __init__.py
        ├── seed_dev.py
        └── wait_for_db.py
```

The `management/` directory and its `__init__.py` files must be created — Django will not discover commands otherwise.

---

## 7. Pre-commit Configuration Design

### 7.1 Philosophy

- pre-commit runs on the host (not inside Docker) because it hooks into git.
- It only validates formatting and catches obvious issues — it does not run the full test suite (too slow for a commit hook).
- Hooks must be fast: total time under 5 seconds for a normal commit.
- All Python formatting is delegated to ruff (not a separate black + isort).
- All JS/TS formatting is delegated to prettier.

### 7.2 Hook selection

| Hook | Purpose | Speed |
|---|---|---|
| `trailing-whitespace` | Remove trailing spaces on all files | <0.1s |
| `end-of-file-fixer` | Ensure single newline at EOF | <0.1s |
| `check-merge-conflict` | Catch unresolved merge markers | <0.1s |
| `check-yaml` | Validate YAML syntax | <0.1s |
| `ruff-format` | Auto-format Python (runs `ruff format`) | ~0.5s |
| `ruff` | Lint Python (runs `ruff check --fix`) | ~0.5s |
| `prettier` | Format TypeScript/JavaScript/JSON/YAML | ~1s |

### 7.3 `.pre-commit-config.yaml`

```yaml
# .pre-commit-config.yaml
# Hooks run on every git commit.
# To install: pip install pre-commit && pre-commit install
# To run manually: pre-commit run --all-files

repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-merge-conflict
      - id: check-yaml
        args: [--unsafe]  # allows custom tags in docker-compose.yml

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.0
    hooks:
      - id: ruff-format
        files: ^apps/(api|ai|runner)/
      - id: ruff
        args: [--fix]
        files: ^apps/(api|ai|runner)/

  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v4.0.0-alpha.8
    hooks:
      - id: prettier
        files: ^apps/web/
        types_or: [ts, tsx, javascript, json]
        additional_dependencies:
          - prettier@3.4.2
```

### 7.4 Installation instructions (for CLAUDE.md / README)

```bash
# Host-side only (one-time per machine)
pip install pre-commit
pre-commit install

# Verify hooks run
pre-commit run --all-files
```

---

## 8. Linting and Formatting Stack Decisions

### 8.1 Python: ruff

**Decision: ruff replaces black + isort + flake8**

Rationale:
- `ruff` is 10–100× faster than black + isort + flake8 combined.
- Single binary, single config block in `pyproject.toml`.
- Drop-in compatible with black formatting output.
- Actively maintained; handles Python 3.12 syntax fully.

**`ruff` is NOT added to `requirements/base.txt`** — it is a dev/tooling dependency, not a runtime dependency. It goes in `requirements/dev.txt`.

**Config location**: A single `pyproject.toml` at the repo root. This avoids per-service config drift.

```toml
# pyproject.toml (repo root)
[tool.ruff]
target-version = "py312"
line-length = 88
src = ["apps/api", "apps/ai", "apps/runner"]

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "UP",  # pyupgrade
]
ignore = [
    "E501",  # line too long — handled by ruff format
]

[tool.ruff.format]
# Match black defaults
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

**Dockerfile change**: The three Python service Dockerfiles currently install only `base.txt`. Since `ruff` is needed inside the container for `make format` and `make lint`, it must be added to `requirements/dev.txt` for the API and to analogous dev requirements for AI and runner.

**Alternative approach**: Run `ruff` from the host via pre-commit (which installs ruff into a virtual env managed by pre-commit) and do NOT add it to any `requirements.txt`. This keeps containers leaner. **This phase uses the Docker-inside approach** to keep `make format` and `make lint` container-native and not require anything on the host beyond `docker` and `make`.

### 8.2 TypeScript: eslint + prettier

**Decision: add `prettier` for auto-formatting; keep `eslint` for lint**

ESLint is already installed and configured via `eslint.config.js`. It covers lint rules. Prettier handles formatting (indentation, quotes, trailing commas, line length). They have distinct responsibilities and do not overlap when properly configured.

**Packages to add to `apps/web/package.json`:**

```json
"devDependencies": {
  "prettier": "^3.4.2",
  "eslint-config-prettier": "^10.1.5"
}
```

- `prettier` — the formatter.
- `eslint-config-prettier` — disables ESLint rules that conflict with prettier's output. Import it last in `eslint.config.js`.

**`apps/web/.prettierrc`:**

```json
{
  "semi": false,
  "singleQuote": true,
  "tabWidth": 2,
  "trailingComma": "es5",
  "printWidth": 100
}
```

**`apps/web/.prettierignore`:**

```
dist/
node_modules/
```

**New `package.json` scripts:**

```json
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "lint": "eslint .",
  "format": "prettier --write \"src/**/*.{ts,tsx}\"",
  "format:check": "prettier --check \"src/**/*.{ts,tsx}\"",
  "preview": "vite preview"
}
```

**Update `eslint.config.js`:**

Add `eslint-config-prettier` as the last extend to disable conflicting rules:

```js
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import prettier from 'eslint-config-prettier'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      prettier,  // must be last
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
])
```

### 8.3 What is explicitly NOT added

| Tool | Reason not added |
|---|---|
| `mypy` | Would require type stubs for all deps; not worth the cost at this stage |
| `bandit` | Security scanner; useful but out of scope for this DX phase |
| `black` | Replaced by `ruff format` |
| `isort` | Replaced by `ruff --select I` |
| `flake8` | Replaced by `ruff check` |
| `stylelint` | No CSS files; Tailwind not in use |
| `commitlint` | Would require team convention agreement; out of scope |
| Husky | npm-based hook manager; pre-commit is sufficient and language-agnostic |

---

## 9. File-by-File Implementation Plan

### 9.1 Files to create

| File | Purpose |
|---|---|
| `pyproject.toml` | `ruff` config, repo root |
| `.pre-commit-config.yaml` | pre-commit hook definitions, repo root |
| `apps/web/.prettierrc` | prettier config |
| `apps/web/.prettierignore` | prettier ignore list |
| `apps/api/apps/common/management/__init__.py` | Django management discovery |
| `apps/api/apps/common/management/commands/__init__.py` | Django management discovery |
| `apps/api/apps/common/management/commands/seed_dev.py` | Seed data command |
| `apps/api/apps/common/management/commands/wait_for_db.py` | DB readiness command |

### 9.2 Files to modify

| File | Change |
|---|---|
| `Makefile` | Full replacement per §5.3 |
| `apps/api/requirements/dev.txt` | Add `ruff>=0.9,<1.0` |
| `apps/ai/requirements.txt` | Introduce `requirements/` split: `base.txt` + `dev.txt`; add `ruff` to dev |
| `apps/runner/requirements.txt` | Introduce `requirements/` split: `base.txt` + `dev.txt`; add `ruff` to dev |
| `apps/ai/Dockerfile` | Install from `base.txt` only (same as API pattern) |
| `apps/runner/Dockerfile` | Install from `base.txt` only (same as API pattern) |
| `apps/web/package.json` | Add `prettier`, `eslint-config-prettier`; add `format` and `format:check` scripts |
| `apps/web/eslint.config.js` | Add `eslint-config-prettier` as final extend |
| `docker-compose.yml` | No changes required |
| `.github/workflows/ci.yml` | Add `ruff check` and `prettier --check` lint gates |

### 9.3 AI and runner requirements split

**Current state:** Both `apps/ai/requirements.txt` and `apps/runner/requirements.txt` are single flat files.

**Target state:** Mirror the API pattern:

```
apps/ai/requirements/
├── base.txt       # runtime deps only
└── dev.txt        # base.txt + ruff + pytest

apps/runner/requirements/
├── base.txt       # runtime deps only
└── dev.txt        # base.txt + ruff + pytest
```

`apps/ai/Dockerfile` and `apps/runner/Dockerfile` must be updated to copy from the new paths.

---

## 10. Step-by-Step Execution Checklist

Each step is self-contained. Complete and verify each before proceeding to the next.

---

### Step 1 — Create `pyproject.toml` at repo root

**Purpose**: Centralize ruff configuration for all three Python services.

**Files touched**: `pyproject.toml` (new)

**Exact commands**: None — create the file with content from §8.1.

**Expected result**: File exists at `/home/dylan/code/runbook-platform/pyproject.toml`.

**Verification**:
```bash
cat pyproject.toml
# Must contain [tool.ruff] section
```

---

### Step 2 — Split AI and runner requirements into base/dev

**Purpose**: Separate runtime dependencies from dev tooling; align with the API pattern.

**Files touched**:
- `apps/ai/requirements.txt` → delete; replaced by:
  - `apps/ai/requirements/base.txt`
  - `apps/ai/requirements/dev.txt`
- `apps/runner/requirements.txt` → delete; replaced by:
  - `apps/runner/requirements/base.txt`
  - `apps/runner/requirements/dev.txt`

**Exact content**:

`apps/ai/requirements/base.txt`:
```
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
pydantic-settings>=2.0,<3.0
httpx>=0.27,<1.0
```

`apps/ai/requirements/dev.txt`:
```
-r base.txt
ruff>=0.9,<1.0
pytest>=8.0,<9.0
```

`apps/runner/requirements/base.txt`:
```
httpx>=0.27,<1.0
pydantic>=2.0,<3.0
```

`apps/runner/requirements/dev.txt`:
```
-r base.txt
ruff>=0.9,<1.0
pytest>=8.0,<9.0
```

**Expected result**: Four new files; two old flat files removed.

**Verification**:
```bash
ls apps/ai/requirements/
ls apps/runner/requirements/
```

---

### Step 3 — Update AI and runner Dockerfiles

**Purpose**: Point Dockerfiles at the new `requirements/base.txt` paths.

**Files touched**: `apps/ai/Dockerfile`, `apps/runner/Dockerfile`

**Change**: Update the `COPY` and `RUN pip install` lines in each Dockerfile to reference `apps/ai/requirements/base.txt` and `apps/runner/requirements/base.txt` respectively. Pattern mirrors `apps/api/Dockerfile`:

```dockerfile
COPY apps/ai/requirements/base.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
```

**Verification**:
```bash
docker compose build ai runner
# Must complete without error
```

---

### Step 4 — Add `ruff` to Python dev requirements

**Purpose**: Enable `make format` and `make lint` targets from inside containers.

**Files touched**: `apps/api/requirements/dev.txt`, `apps/ai/requirements/dev.txt`, `apps/runner/requirements/dev.txt`

**Changes**:

`apps/api/requirements/dev.txt`:
```
-r base.txt
ruff>=0.9,<1.0
pytest>=8.0,<9.0
pytest-django>=4.9,<5.0
```

**Note**: `ruff` is a dev dependency. The production Dockerfiles install `base.txt` only. To use `make lint` and `make format`, the running containers must have `dev.txt` installed. Two approaches:

**Option A (simpler)**: Install `dev.txt` in the Dockerfile unconditionally. For local dev this is fine; the containers are not production images.

**Option B (correct)**: Add a `build.target` to `docker-compose.yml` to select a `dev` stage in a multi-stage Dockerfile.

**This phase uses Option A** to avoid multi-stage Dockerfile complexity. The Dockerfile installs `dev.txt` by default. If production hardening is needed later, that is a separate concern.

Update `apps/api/Dockerfile`:
```dockerfile
COPY apps/api/requirements/dev.txt /tmp/requirements.txt
```
(change from `base.txt` to `dev.txt`)

Do the same for AI and runner Dockerfiles.

**Verification**:
```bash
docker compose build
docker compose exec api ruff --version
docker compose exec ai ruff --version
docker compose exec runner ruff --version
# Each must print a version string
```

---

### Step 5 — Create management command directory structure

**Purpose**: Django requires specific directory layout to discover management commands.

**Files touched** (all new):
- `apps/api/apps/common/management/__init__.py`
- `apps/api/apps/common/management/commands/__init__.py`

Both files are empty.

**Verification**:
```bash
docker compose exec api python manage.py help | grep -E "seed_dev|wait_for_db"
# Will return nothing yet — that's expected. This step just creates the dirs.
ls apps/api/apps/common/management/
# Must show __init__.py and commands/
```

---

### Step 6 — Create `wait_for_db` management command

**Purpose**: Block `bootstrap` until the database is reachable, preventing migration failures on first start.

**Files touched**: `apps/api/apps/common/management/commands/wait_for_db.py` (new)

**Content**: See §6.4.

**Verification**:
```bash
docker compose up -d postgres
docker compose exec api python manage.py wait_for_db
# Must print "Database ready." without error
```

---

### Step 7 — Create `seed_dev` management command

**Purpose**: Populate the development database with one organization, one runbook, and one workflow.

**Files touched**: `apps/api/apps/common/management/commands/seed_dev.py` (new)

**Content**: See §6.3.

**Note**: The `get_or_create` calls reference model classes that must already exist (Organization, Runbook, Workflow, Execution). If any of these models do not yet exist (phases 02–05 incomplete), the command will fail at import time with an `ImportError`. Adjust imports to match actual model locations.

**Verification**:
```bash
docker compose exec api python manage.py seed_dev
# Must print:
#   [Created] Organization: Acme Platform Engineering
#   [Created] Runbook: Deploy to Production
#   [Created] Workflow: deploy-production-v1
#   Seed complete.

docker compose exec api python manage.py seed_dev
# Must print:
#   [Already exists] Organization: Acme Platform Engineering
#   [Already exists] Runbook: Deploy to Production
#   [Already exists] Workflow: deploy-production-v1
#   Seed complete.
# (idempotency verified)
```

---

### Step 8 — Replace Makefile

**Purpose**: Install the full set of documented targets.

**Files touched**: `Makefile`

**Content**: Full replacement per §5.3.

**Verification**:
```bash
make help
# Must list all targets with descriptions

make ps
# Must show running containers

make lint
# Must run ruff on all Python services and eslint on web

make format
# Must run ruff format + prettier write without error
```

---

### Step 9 — Add prettier to the web app

**Purpose**: Enforce consistent TypeScript formatting.

**Files touched**: `apps/web/package.json`, `apps/web/eslint.config.js`, `apps/web/.prettierrc` (new), `apps/web/.prettierignore` (new)

**Step 9a**: Install packages

```bash
# Run inside the web container or locally if Node is available on host
docker compose exec web npm install --save-dev prettier@3.4.2 eslint-config-prettier@10.1.5
```

This updates `package.json` and `package-lock.json` automatically.

**Step 9b**: Add `.prettierrc` and `.prettierignore` per §8.2.

**Step 9c**: Update `eslint.config.js` to import and extend `eslint-config-prettier` last (per §8.2).

**Step 9d**: Add `format` and `format:check` scripts to `package.json` per §8.2.

**Verification**:
```bash
docker compose exec web npm run format
# Must write-format all .ts/.tsx files without error

docker compose exec web npm run lint
# Must exit 0 (assuming source is now formatted)

docker compose exec web npm run format:check
# Must exit 0 immediately after running format
```

---

### Step 10 — Create `.pre-commit-config.yaml`

**Purpose**: Wire formatting and lint checks into the git commit lifecycle.

**Files touched**: `.pre-commit-config.yaml` (new)

**Content**: See §7.3.

**Verification** (host-side):
```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
# All hooks must pass or auto-fix and pass on re-run
```

---

### Step 11 — Update CI to add lint gates

**Purpose**: Make CI enforce the same checks that pre-commit runs locally.

**Files touched**: `.github/workflows/ci.yml`

**Changes**: Add two new steps to the `web` job and two to `python-services`:

```yaml
# In the web job, after npm ci:
- run: npm run lint
  working-directory: apps/web
- run: npm run format:check
  working-directory: apps/web

# In the python-services job, after pip install:
- run: pip install ruff
- run: ruff check apps/api apps/ai apps/runner
- run: ruff format --check apps/api apps/ai apps/runner
```

**Verification**:
```bash
# Push a branch with clean code
# CI must pass all lint steps
```

---

### Step 12 — Update `bootstrap` target with `wait_for_db`

**Purpose**: Make `make bootstrap` reliable on first run when Postgres is starting up.

**Files touched**: `Makefile` (already replaced in step 8 — verify the bootstrap target includes `wait_for_db`)

**Verification**:
```bash
make down
docker volume rm runbook-platform_postgres_data 2>/dev/null || true
make bootstrap
# Must complete without "connection refused" errors on migrate
# Must print "System is ready." with URL list
```

---

## 11. Verification Plan

### 11.1 Full end-to-end smoke test

Run this sequence on a clean machine (or after `make reset`):

```bash
# 1. Clone and configure
cp .env.example .env
# (Edit DJANGO_SECRET_KEY and RUNNER_REGISTRATION_TOKEN to non-default values)

# 2. Bootstrap
make bootstrap
# Expected: all containers start, migrations run, seed data created

# 3. Verify services
make ps
# Expected: all 5 containers (postgres, api, ai, runner, web) show "running"

curl http://localhost:8000/api/v1/
# Expected: 200 or 404 with JSON (not connection refused)

curl http://localhost:8001/health
# Expected: {"status": "ok"}

# 4. Verify seed data
docker compose exec api python manage.py shell -c "
from apps.organizations.models import Organization
print(Organization.objects.filter(slug='acme-platform-eng').count())
"
# Expected: 1

# 5. Verify formatting
make format
git diff --stat
# Expected: no diff (code was already formatted) OR diff shows formatting fixes

make lint
# Expected: exit 0

# 6. Verify tests
make test-api
# Expected: all tests pass

make test-runner
# Expected: all tests pass

# 7. Verify pre-commit
pre-commit run --all-files
# Expected: all hooks pass

# 8. Verify reset
make reset
# Expected: WARNING printed, 3-second pause, full rebuild, seed data recreated
```

### 11.2 Idempotency test

```bash
make seed-dev
make seed-dev
# Expected: second run prints "Already exists" for all records, exits 0
```

### 11.3 Docker-only test (no host Python)

```bash
# Verify that format and lint work without host Python
which python || echo "no host python"
make format  # must succeed
make lint    # must succeed
# Proves Docker is the source of truth
```

---

## 12. Best Practices / Anti-Patterns

### Best practices enforced by this phase

- **Single source of truth for config**: `pyproject.toml` at repo root holds ruff config for all three Python services. No per-service config drift.
- **Idempotent operations**: `seed_dev` and `bootstrap` can be run any number of times without side effects.
- **Named, documented targets**: Every Makefile target has a `##` comment; `make help` is always current.
- **Dev/prod dependency separation**: Runtime containers install `base.txt`; dev containers install `dev.txt`. Tooling never leaks into production images.
- **Pre-commit as fast gate**: Pre-commit catches formatting issues in <5s per commit. CI is the slow gate; pre-commit is the fast one.

### Anti-patterns this phase eliminates

| Anti-pattern | Fix |
|---|---|
| Remembering raw `docker compose exec api python manage.py ...` | Wrapped in `make` targets |
| Starting with an empty database and manually creating seed data | `seed_dev` command |
| Formatting divergence across contributors | `ruff format` + `prettier` enforced by pre-commit |
| `bootstrap` failing silently when DB not ready | `wait_for_db` command |
| Re-running `bootstrap` creating duplicate seed records | `get_or_create` idempotency |
| Multiple linting tools (black + isort + flake8) | Single `ruff` binary |

### Anti-patterns to avoid introducing

- **Do not** add a `Makefile` target that calls another Makefile target with `$(MAKE)`. Keep targets flat.
- **Do not** install `ruff` globally on the host. Use the Docker container.
- **Do not** wire `seed_dev` to run automatically on every `migrate`. Migrations run in CI; seed data must not.
- **Do not** add `pre-commit` to `requirements/dev.txt`. It is a host-side tool, not a container dependency.
- **Do not** create factory libraries (factory_boy, model_bakery) for seed data at this stage. `get_or_create` with hardcoded values is sufficient and more readable.

---

## 13. Codex/Claude Execution Batching Plan

Steps are grouped by dependency. Batches within a group can run in parallel; batches must run in order.

### Batch A — Foundation (no dependencies, do first)

| Step | Description |
|---|---|
| Step 1 | Create `pyproject.toml` |
| Step 10 | Create `.pre-commit-config.yaml` |

These files have no dependencies on other steps and can be created immediately.

### Batch B — Requirements split (depends on nothing, enables Step 4)

| Step | Description |
|---|---|
| Step 2 | Split AI and runner requirements |
| Step 3 | Update AI and runner Dockerfiles |

### Batch C — Python tooling in containers (depends on B)

| Step | Description |
|---|---|
| Step 4 | Add `ruff` to dev requirements, update Dockerfiles to install `dev.txt` |

### Batch D — Management commands (parallel)

| Step | Description |
|---|---|
| Step 5 | Create management command directory structure |
| Step 6 | Create `wait_for_db` |
| Step 7 | Create `seed_dev` |

Steps 5, 6, 7 can be executed together since they are all file creations with no inter-dependency within the batch (though 5 is a prereq for 6 and 7 to be discoverable by Django).

### Batch E — Makefile + web tooling (depends on C, D)

| Step | Description |
|---|---|
| Step 8 | Replace Makefile |
| Step 9 | Add prettier to web |

### Batch F — Integration verification (depends on all previous)

| Step | Description |
|---|---|
| Step 11 | Update CI |
| Step 12 | Verify `bootstrap` with `wait_for_db` |

---

## 14. Definition of Done

This phase is complete when all of the following are true:

- [ ] `make help` lists all targets with descriptions.
- [ ] `make bootstrap` on a fresh clone (no running containers, no volumes) completes without manual intervention and prints "System is ready."
- [ ] `make seed-dev` run twice prints "Already exists" on the second run for all three records.
- [ ] `make format` runs without error and produces no diff on already-formatted code.
- [ ] `make lint` exits 0 on a clean codebase.
- [ ] `make test-api` exits 0.
- [ ] `make test-runner` exits 0.
- [ ] `make reset` prints a warning, waits 3 seconds, tears down volumes, and bootstraps cleanly.
- [ ] `pre-commit run --all-files` exits 0 on a clean working tree.
- [ ] `docker compose exec api ruff --version` prints a version string (ruff is inside the container).
- [ ] `docker compose exec web npm run format:check` exits 0 after `make format` has been run.
- [ ] CI passes with the new lint gates.
- [ ] No host-side Python, Node, or ruff installation is required to use `make format` or `make lint`.
- [ ] `pyproject.toml` exists at repo root with `[tool.ruff]` section.
- [ ] `apps/web/.prettierrc` and `apps/web/.prettierignore` exist.
- [ ] `apps/api/apps/common/management/commands/seed_dev.py` exists and is importable.
- [ ] `apps/api/apps/common/management/commands/wait_for_db.py` exists and is importable.
