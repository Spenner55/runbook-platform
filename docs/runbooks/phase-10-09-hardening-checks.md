# Phase 10.9 Hardening Checks

These checks validate the production-hardening gates added in Phase 10.9 Step 8.
They do not require AWS credentials, do not deploy anything, and use only local
Docker Compose services plus public, free security scanners.

## Local Prerequisites

- Docker and Docker Compose
- `make`
- Running local stack for Compose-backed checks:

```sh
make up-d
```

If the database is new, apply migrations first:

```sh
make migrate
```

## Main Local Targets

| Command | What it checks |
| --- | --- |
| `make check-prod` | Runs `python manage.py check --deploy --settings=config.settings.prod` inside the API container with local-only production-like environment values. |
| `make check-migrations` | Runs `makemigrations --check --dry-run` and `migrate --check` to catch model drift and unapplied migrations. |
| `make security-scan` | Runs `pip-audit`, `npm audit --audit-level=high`, Gitleaks secret scanning, and Trivy filesystem vulnerability scanning. |
| `make hardening-check` | Runs all three targets above. |

`make security-scan` may pull public scanner images and install `pip-audit` into
running containers. It does not modify repository files.

## Explicit Verification Commands

The Step 8 verification commands are:

```sh
docker compose exec api python manage.py check --deploy --settings=config.settings.prod
docker compose exec api python manage.py makemigrations --check --dry-run
docker compose exec api pytest
cd apps/web && npm run build
```

For the production settings check, use `make check-prod` unless your shell already
exports all production-required environment variables. The target supplies local
placeholder values for `DJANGO_SECRET_KEY`, `DATABASE_URL`, allowed hosts, CORS,
runner token, and integration encryption key.

## CI Gates

GitHub Actions preserves the existing build and test jobs:

- web build, lint, format check, and Vitest
- Python lint and format checks
- API tests
- runner tests
- AI tests

The hardening gates add:

- production Django deploy check in `api-tests`
- migration drift and unapplied migration check in `migration-check`
- Python dependency audit with `pip-audit`
- blocking `npm audit --audit-level=high`
- blocking Gitleaks secret scan
- blocking Trivy filesystem scan for high and critical vulnerabilities

The scans use free tooling and do not require AWS credentials or paid services.
