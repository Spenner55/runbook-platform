# Runner Crash Recovery

Use this runbook when a runner container exits, restarts repeatedly, or stops
claiming execution work.

## Symptoms

- `docker compose ps runner` shows the runner stopped, restarting, or unhealthy.
- ECS or Compose logs show repeated runner process exits.
- Executions remain `claimed` or `running` with stale `last_heartbeat_at`.
- `runbook_stuck_executions_recovered_total` increases after the watchdog runs.

## Immediate Checks

```sh
docker compose ps runner
docker compose logs --tail=200 runner
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 300
```

Check whether the runner received `SIGTERM`, lost API connectivity, failed on a
step command, or exited after repeated internal API failures.

## Safe Mitigations

- Do not manually mark executions successful.
- Restart the runner only after capturing the last logs.
- If a deployment caused the crash loop, roll back the runner image before
  increasing runner count.
- Let the watchdog fail stale executions rather than editing execution rows.

## Recovery Steps

1. Capture runner logs and the affected execution IDs.
2. Restart the runner:

```sh
docker compose up -d runner
```

3. Run the watchdog to recover stale `claimed` or `running` executions:

```sh
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 300
```

4. If the runner still crashes, stop it and inspect the most recent stack trace:

```sh
docker compose stop runner
docker compose logs --tail=300 runner
```

5. Fix the runner configuration or roll back the image before starting it again.

## Verification

```sh
docker compose ps runner
docker compose logs --tail=100 runner
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 300
```

Expected:

- Runner is running.
- Logs show polling without repeated exceptions.
- Watchdog reports no newly stuck executions after recovery.

## Rollback Or Escalation

- Roll back the runner image if the crash started after a deploy.
- Escalate if executions repeatedly become stale after the runner is healthy;
  that indicates API, database, or claim-token behavior needs investigation.
- Keep API and database state authoritative. Do not replay runner internal calls
  with copied claim tokens unless a maintainer has approved the exact request.

## Evidence To Capture

- Runner logs before and after restart.
- Affected execution IDs and statuses.
- Watchdog command output.
- Image tag or commit SHA for the runner.
- Any rollback command and result.
