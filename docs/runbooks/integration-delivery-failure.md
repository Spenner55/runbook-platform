# Integration Delivery Failure

Use this runbook when Slack, generic webhook, or PagerDuty delivery attempts are
failing.

## Symptoms

- `IntegrationDeliveryAttempt` rows show `success=false`.
- An `IntegrationConnection` has `last_delivery_status=failed`.
- Logs include `Integration notification failed for one connection.`
- Metrics show integration dispatch failures or elevated dispatch latency.

## Immediate Checks

Inspect recent failed attempts from Django:

```sh
docker compose exec api python manage.py shell -c '
from apps.integrations.models import IntegrationDeliveryAttempt
for attempt in IntegrationDeliveryAttempt.objects.filter(success=False).order_by("-attempted_at")[:10]:
    print(attempt.attempted_at, attempt.organization_id, attempt.integration_id, attempt.event_type, attempt.http_status, attempt.error_detail[:200])
'
```

Check API logs and metrics:

```sh
docker compose logs --tail=200 api
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/metrics/", timeout=5)
print(response.status_code)
print("\n".join(line for line in response.text.splitlines() if "integration" in line.lower())[:1000])
PY
```

## Safe Mitigations

- Deactivate a broken integration connection if it is causing repeated failures
  or slow dispatch.
- Do not expose webhook URLs, tokens, or response bodies in logs or incident
  notes.
- Do not manually mark failed attempts as successful.
- Do not add broad retries during an incident; Phase 10.9 dispatch is bounded
  and records failures for operator action.

## Recovery Steps

1. Identify the failing integration connection and event type from attempts.
2. Confirm the destination URL is still allowed by SSRF validation and is
   reachable from the API runtime.
3. Rotate or correct integration credentials if the provider returns
   authentication errors.
4. Deactivate the connection while fixing it if failures are noisy:

```sh
docker compose exec api python manage.py shell -c '
from apps.integrations.models import IntegrationConnection
connection = IntegrationConnection.objects.get(id="<integration-id>")
connection.is_active = False
connection.save(update_fields=["is_active", "updated_at"])
print("deactivated", connection.id)
'
```

5. Re-enable the connection after updating configuration through the supported
   API/UI path.
6. Trigger a low-risk event that should notify integrations and inspect the new
   delivery attempt.

## Verification

- New delivery attempts for the connection show `success=true`.
- `last_delivery_status` returns to `success`.
- API logs have no repeated integration dispatch exceptions.
- Metrics no longer show increasing failure counts for the recovered connection
  path.

## Rollback Or Escalation

- Keep the connection deactivated if the destination provider is down.
- Escalate if all integrations fail, because that suggests API networking,
  DNS, SSRF validation, or credential encryption issues rather than one bad
  provider configuration.
- Escalate before replaying business events; replay can duplicate external
  notifications.

## Evidence To Capture

- Failed attempt IDs, integration ID, event type, HTTP status, and redacted
  error detail.
- API log request IDs around dispatch.
- Provider status or credential rotation notes.
- Successful recovery attempt ID.
