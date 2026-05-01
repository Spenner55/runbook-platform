# AI Service Outage

Use this runbook when the AI service is unavailable, degraded, or returning
errors to Django.

## Symptoms

- `GET /health/` from Django returns `503` with an AI check failure.
- `GET /health/ready/` still returns `200` while the database is healthy.
- Runbook parse, enrich, or summarize requests fail with a user-visible error.
- AI service logs show OpenAI configuration, network, timeout, or application
  errors.

## Immediate Checks

```sh
docker compose ps ai api
docker compose logs --tail=200 ai
docker compose exec api python - <<'PY'
import httpx
for path in ("/health/ready/", "/health/"):
    response = httpx.get(f"http://localhost:8000{path}", timeout=5)
    print(path, response.status_code, response.text[:500])
PY
```

Expected during an AI-only outage:

- `/health/ready/` returns `200`.
- `/health/` returns `503` and shows AI dependency failure.

## Safe Mitigations

- Keep API tasks in rotation when `/health/ready/` is healthy.
- Pause AI-dependent user workflows if parse/enrich/summarize failures are
  causing noisy retries.
- Do not point the frontend or runner directly at the AI service.
- Do not change ALB or Compose health checks from `/health/ready/` to
  `/health/`.

## Recovery Steps

1. Capture API dependency health output and AI logs.
2. Restart the AI service:

```sh
docker compose up -d ai
```

3. Confirm the AI process health endpoint:

```sh
docker compose exec ai python - <<'PY'
import httpx
response = httpx.get("http://localhost:8001/health", timeout=5)
print(response.status_code)
print(response.text)
PY
```

4. Confirm Django dependency health after AI is ready:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

5. Retry one AI-dependent operation from the UI or API.

## Verification

- `/health/ready/` remains `200`.
- `/health/` returns `200` after AI recovery.
- AI-dependent operations return controlled validation or success responses, not
  unhandled `500` errors.
- API logs include the request ID used for the recovered operation.

## Rollback Or Escalation

- Roll back the AI image if the outage started after an AI deploy.
- Escalate OpenAI or network failures if the service is healthy but provider
  reachability remains degraded.
- Leave Phase 10.10 ALB health checks pointed at `/health/ready/`; changing the
  readiness path is not an acceptable mitigation.

## Evidence To Capture

- `/health/ready/` and `/health/` outputs during the outage.
- AI service logs and image tag.
- Request ID for a failed and recovered AI-dependent request.
- Any provider status or credential-rotation notes.
