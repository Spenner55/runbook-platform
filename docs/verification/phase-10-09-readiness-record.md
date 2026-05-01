# Phase 10.9 Readiness Verification Record

| Field | Value |
|---|---|
| Date | 2026-05-01 |
| Phase | 10.9 Production Hardening |
| Commit SHA | `a6d888e` |
| Worktree state | Dirty; Phase 10.9 remediation changes are present but not committed. |
| Environment | Local Docker Compose on WSL; API, AI, Postgres, PgBouncer, runner, and web containers running. |
| Result | **Blocked for Phase 10.10** |

## Executive Result

Phase 10.9 M10 load evidence has been remediated, but Phase 10.10 remains
blocked on non-load evidence.

The local code/test/security gates passed, and the required 50 VU / 60 second
load gate now passes after tail-latency remediation. Branch-protection evidence
still could not be verified through the available GitHub API access.

Do not update the implementation status to ready until branch-protection
evidence and the remaining manual drill evidence are recorded.

## Commands Run

```sh
make lint
# passed

make test-api
# 587 passed, 1 warning in 51.00s

make test-runner
# 108 passed in 0.44s

make test-web
# 87 passed in 5.92s

docker compose exec ai pytest tests/
# 61 passed, 1 skipped in 1.11s

make check-prod
# passed; Django deploy check reported no issues

make check-migrations
# passed; no model changes detected and migrate --check exited 0

make security-scan
# passed; pip-audit, npm audit, Gitleaks, and Trivy completed with no blocking findings

make hardening-check
# passed; re-ran production check, migration check, and security scan
```

## Load Test Evidence

The host did not have `k6` installed. The pinned Docker image
`grafana/k6:0.50.0` was pulled and used for local verification.

Smoke check:

```sh
docker run --rm --network host \
  -v /home/dylan/code/runbook-platform/scripts:/scripts \
  -e RUNBOOK_API_BASE_URL=http://127.0.0.1:8000 \
  -e RUNBOOK_LOAD_TEST_EMAIL=<seeded local operator email> \
  -e RUNBOOK_LOAD_TEST_PASSWORD=<seeded local operator password> \
  -e RUNBOOK_ORG_ID=<seeded local organization id> \
  grafana/k6:0.50.0 run --vus 1 --duration 2s /scripts/load-test.js
# passed
```

Full gate:

```sh
docker run --rm --network host \
  -v /home/dylan/code/runbook-platform/scripts:/scripts \
  -e RUNBOOK_API_BASE_URL=http://127.0.0.1:8000 \
  -e RUNBOOK_LOAD_TEST_EMAIL=<seeded local operator email> \
  -e RUNBOOK_LOAD_TEST_PASSWORD=<seeded local operator password> \
  -e RUNBOOK_ORG_ID=<seeded local organization id> \
  grafana/k6:0.50.0 run --vus 50 --duration 60s /scripts/load-test.js
# passed
```

Observed full-run summary:

- Completed iterations: `2961`
- Requests: `2963`
- Checks: `5924 passed`, `0 failed`
- HTTP failures: `0.00%`
- `runbook_http_5xx_rate`: `0.00%`
- `http_req_duration{endpoint:executions_list}`: average `19.12ms`, median
  `9.13ms`, max `233.79ms`, p90 `27.27ms`, p95 `80.85ms`
- Passed threshold: `http_req_duration{endpoint:executions_list} p(99)<200`

PgBouncer evidence sampled during the full run:

```sh
docker compose exec pgbouncer sh -c 'PGPASSWORD="$POSTGRESQL_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$POSTGRESQL_USERNAME" -d pgbouncer -c "SHOW POOLS;"'
```

Observed:

- `runbook_platform` pool mode was `transaction`.
- `cl_waiting` was `0`.
- `sv_active` was `0` at both samples.
- No pool wait was observed in the samples.

## Manual Drill Evidence

| Drill | Status | Evidence |
|---|---|---|
| Runner SIGTERM during execution | Not run in this pass | Covered by runner shutdown tests; manual execution still required before Phase 10.10. |
| Stale heartbeat recovery | Automated tests passed | API suite includes watchdog recovery coverage. |
| Expired approval recovery | Automated tests passed | API suite includes `recover_expired_approvals` and watchdog command coverage. |
| AI outage readiness behavior | Automated tests passed | API health tests cover readiness decoupling from AI health. |
| Postgres/PgBouncer outage behavior | Not run in this pass | Manual outage drill still required before Phase 10.10. |
| Integration delivery failure | Automated tests passed | API suite includes integration delivery failure coverage. Manual drill still recommended. |
| Metrics unauthorized/authorized scrape | Automated tests passed | API metrics tests passed; local metrics guard covered. |
| Request ID trace across Django, AI, and runner | Automated tests passed | API, AI, and runner tests passed; manual log trace still recommended. |
| Missing production env var startup failure | Automated tests passed | `make check-prod` passed with required local env; prod settings tests passed in API suite. |

## Branch Protection Evidence

Attempted:

```sh
gh api repos/Spenner55/runbook-platform/branches/main/protection
```

Result:

- GitHub returned HTTP `403`.
- Message: `Upgrade to GitHub Pro or make this repository public to enable this feature.`

Branch protection must be verified manually in the GitHub UI before Phase 10.10
starts, including required CI checks for lint/tests, migration checks,
dependency audits, secret scan, and container/filesystem scan.

## Seed Data Note

`python manage.py seed_dev` was attempted before the load test. The seeded users
and organization already existed, but the command later failed with
`Execution.MultipleObjectsReturned` while reseeding executions. The load test was
still able to authenticate and list executions with existing local seed data.

Follow-up: make `seed_dev` fully idempotent for executions before relying on it
as the only documented load-test setup path.

## Residual Risks And Required Remediation

- Run the remaining manual drills from
  `docs/runbooks/production-hardening-local-drills.md` and replace the
  "Not run" statuses above with timestamped evidence.
- Verify branch protection manually in GitHub and record the required checks.

## Rollback Notes

The M10 evidence changes are documentation plus the k6 script. The
tail-latency remediation also changes runtime behavior: it adds short-lived
execution-list and JWT-user caches, uses JSON structured logs, and sets local
Compose API logging to `WARNING` by default. Rollback would restore uncached
list/auth reads and more verbose local request logging, which may reintroduce
the failed k6 tail-latency gate.
