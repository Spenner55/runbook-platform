# Stuck Execution Recovery

This runbook handles executions left in `claimed` or `running` after runner
shutdown, network loss, or a stale heartbeat. The recovery path is Django-owned:
the runner never edits the database directly.

## What The Watchdog Does

`check_stuck_executions` calls `recover_stuck_executions(...)` in
`apps/api/apps/executions/services.py`.

For each execution whose `last_heartbeat_at` is older than the configured
threshold and whose status is `claimed` or `running`, the service:

- locks the execution row with `select_for_update(skip_locked=True)`;
- marks the execution `failed`;
- marks currently running steps `failed`;
- records watchdog metadata in the audit trail;
- emits execution and step metrics.

The command is idempotent. Running it repeatedly after recovery should report no
additional stuck executions.

## Standard Recovery

Run with the default 300 second threshold:

```sh
docker compose exec api python manage.py check_stuck_executions
```

Run with an explicit threshold:

```sh
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 300
```

Expected outputs:

- `Recovered N stuck execution(s): ...` when stale executions were recovered.
- `No stuck executions found.` when no rows require action.

## Local Drill Recovery

For local manual drills only, use a short threshold after intentionally stopping
the runner:

```sh
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 1
```

Then verify idempotence:

```sh
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 1
```

## Triage Checks

Check runner logs:

```sh
docker compose logs --tail=200 runner
```

Check API logs for watchdog activity:

```sh
docker compose logs --tail=200 api
```

Open a Django shell for targeted inspection:

```sh
docker compose exec api python manage.py shell
```

Example inspection query:

```py
from apps.executions.models import Execution

Execution.objects.filter(status__in=["claimed", "running"]).values(
    "id",
    "status",
    "claimed_by_runner_id",
    "last_heartbeat_at",
)
```

## Escalation Criteria

Escalate before manual database edits if:

- the watchdog command fails with an exception;
- recovered executions immediately become stuck again;
- `last_heartbeat_at` is updating but the execution is not progressing;
- audit records are missing for watchdog recovery;
- multiple runners appear to process the same execution.

Manual database updates should be a last resort. Prefer fixing the service path
or rerunning the management command so audit and metrics stay consistent.

## Phase 10.10 Scheduling Note

Before AWS deployment, schedule this command through the chosen production
scheduler, such as ECS scheduled tasks. The scheduled task should use the same
threshold as `WATCHDOG_STUCK_THRESHOLD_SECONDS` unless a deployment-specific
runbook documents a different value.
