# Local Development

This repo is Docker-first. The root `docker-compose.yml` and `Makefile` are the source of truth for routine local work.

## Prerequisites

- Docker and Docker Compose.
- `make`.
- Git.

Host installs of Python, Node, PostgreSQL, or npm packages are not required for normal development.

## First-Time Setup

```sh
cp .env.example .env
make bootstrap
```

`make bootstrap` builds images, starts containers, waits for PostgreSQL, applies migrations, and runs the development seed command.

Services:

- Web: `http://localhost:5173`
- Django API: `http://localhost:8000`
- AI service: `http://localhost:8001`
- PostgreSQL: `localhost:5432`

## Environment Variables

Start from `.env.example`.

Important variables:

| Variable | Used by | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Django | Points to Compose PostgreSQL. |
| `DJANGO_SECRET_KEY` | Django | Local value may be non-production. |
| `DJANGO_DEBUG` | Django | `1` for local development. |
| `DJANGO_ALLOWED_HOSTS` | Django | Include `localhost`, `127.0.0.1`, and `api`. |
| `AI_BASE_URL` | Django | Usually `http://ai:8001` inside Compose. |
| `API_BASE_URL` | Runner | Usually `http://api:8000` inside Compose. |
| `RUNNER_REGISTRATION_TOKEN` | Runner | Present but not enforced until future auth hardening. |
| `VITE_API_BASE_URL` | Web | Usually `http://localhost:8000` for browser calls. |

## Docker Compose Workflow

Start in foreground:

```sh
make up
```

Start in background:

```sh
make up-d
```

Stop without deleting data:

```sh
make down
```

Restart without rebuilding:

```sh
make restart
```

View service status:

```sh
make ps
```

Tail logs:

```sh
make logs
make logs-api
make logs-web
make logs-runner
make logs-ai
```

## Makefile Workflow

Use `make help` to list commands.

Common targets:

| Target | Purpose |
| --- | --- |
| `bootstrap` | First-time setup. |
| `up`, `up-d` | Build and start services. |
| `down` | Stop containers and preserve volumes. |
| `restart` | Restart containers without rebuilding. |
| `migrate` | Apply Django migrations. |
| `makemigrations` | Generate Django migrations. |
| `makemigrations-app APP=name` | Generate migrations for one app. |
| `seed-dev` | Seed local development data. |
| `test-api` | Run Django pytest. |
| `test-runner` | Run runner pytest. |
| `test-web` | Run Vitest once. |
| `lint` | Run Python and web lint checks. |
| `format` | Format Python and TypeScript code. |

`make reset` is destructive: it removes volumes and local database data.

## Running Migrations

Apply migrations:

```sh
make migrate
```

Create migrations:

```sh
make makemigrations
make makemigrations-app APP=runbooks
```

Do not run migrations as part of documentation-only tasks.

## Seeding Data

Seed local data:

```sh
make seed-dev
```

The seed command is intended to be idempotent for local development.

## Running Tests

```sh
make test-api
make test-runner
make test-web
```

Direct equivalents:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest
docker compose exec runner pytest
docker compose exec web npm test -- --run
```

## Linting And Formatting

```sh
make lint
make format
```

CI also runs web build/lint/format/tests, Python compile/lint/format, API tests, runner tests, and AI tests.

## Shells

```sh
make api-shell
make ai-shell
make runner-shell
make web-shell
make db-shell
```

## Troubleshooting

### Containers Start But API Cannot Reach Database

Run:

```sh
make ps
make logs-api
make logs
```

Confirm PostgreSQL is healthy and `.env` has `DATABASE_URL=postgresql://postgres:postgres@postgres:5432/runbook_platform`.

### Frontend Cannot Reach API

Confirm `.env` has:

```sh
VITE_API_BASE_URL=http://localhost:8000
```

Restart the web container after changing Vite env vars.

### AI Workflow Creation Fails

Check:

```sh
make logs-api
make logs-ai
```

Confirm Django has `AI_BASE_URL=http://ai:8001`.

### Changes Do Not Show Up

For Python services, mounted source should update immediately, but process reload behavior depends on the service entrypoint. Restart the target service:

```sh
make restart
```

For web dependency changes, rebuild:

```sh
make up-d
```

### Need A Clean Local Database

Use only when you are ready to lose local data:

```sh
make reset
```

## Stop/Start Without Rebuilds

Use targeted starts and stops:

```sh
make stop-api
make start-api
make stop-web
make start-web
make stop-runner
make start-runner
make stop-ai
make start-ai
make stop-db
make start-db
```

Use these when images and dependencies have not changed.
