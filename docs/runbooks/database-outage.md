# Database Outage

Use this runbook when Postgres or PgBouncer is unavailable, migrations are not
current, or the API readiness endpoint reports `not_ready`.

## Symptoms

- `GET /health/ready/` returns `503`.
- `GET /health/` returns `503` with a database check failure.
- API requests fail with database connection, transaction, or migration errors.
- PgBouncer health is unhealthy or `SHOW POOLS;` cannot connect.

## Immediate Checks

```sh
docker compose ps postgres pgbouncer api
docker compose logs --tail=200 postgres
docker compose logs --tail=200 pgbouncer
docker compose exec api python manage.py migrate --check
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/ready/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

If PgBouncer is running, inspect pool state:

```sh
docker compose exec pgbouncer sh -c 'PGPASSWORD="$POSTGRESQL_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$POSTGRESQL_USERNAME" -d pgbouncer -c "SHOW POOLS;"'
```

## Safe Mitigations

- Stop creating new executions if writes are failing.
- Do not run migrations while database availability is unstable.
- Do not bypass PgBouncer in production-like validation unless the goal is to
  isolate PgBouncer as the failing component.
- Keep `/health/ready/` failing until database and migration checks pass.

## Recovery Steps

1. Capture API readiness output and Postgres/PgBouncer logs.
2. Restore the failed local service:

```sh
docker compose up -d postgres pgbouncer
```

3. Wait for Compose health to report healthy:

```sh
docker compose ps postgres pgbouncer api
```

4. Confirm migrations are current:

```sh
docker compose exec api python manage.py migrate --check
```

5. Re-check readiness:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/ready/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

6. Run a low-risk read endpoint before allowing normal traffic.

## Verification

- Postgres, PgBouncer, and API are healthy.
- `/health/ready/` returns `200` with database and migration checks healthy.
- `python manage.py migrate --check` passes.
- New API reads and writes succeed through the normal `DATABASE_URL`.

## Rollback Or Escalation

- Roll back the API image if new migrations or settings caused readiness to
  fail.
- Escalate to database restore procedures if Postgres data files are corrupt or
  RDS/PITR is required in AWS.
- Escalate immediately if PgBouncer pool exhaustion recurs after traffic is
  reduced; Phase 10.10 sizing may need adjustment before production deploy.

## Evidence To Capture

- Readiness JSON before and after recovery.
- Postgres and PgBouncer logs.
- `migrate --check` output.
- PgBouncer `SHOW POOLS;` output if available.
- Rollback or restore command output.
