# Phase 10 Expansion — Architecture Guardrails

**Status:** Authoritative cross-cutting reference for all Phase 10 implementation work.

This document consolidates decisions that span multiple Phase 10 blueprints. Each guardrail was established through the audit-remediation process on the Phase 10 expansion blueprint set. Implementation prompts and AI agents working on Phase 10 should load this file as context alongside the relevant phase blueprint.

---

## 1. Service boundary invariants (non-negotiable)

These invariants are inherited from the platform foundation and must not be violated by any Phase 10 feature:

| Invariant | Rule |
|---|---|
| INV-1: Django is the control plane | All domain state transitions go through Django. No service reads or writes the database directly except Django. |
| INV-2: Runner → Django internal API only | The runner calls only `/api/v1/internal/...`. It does not call the AI service, Slack, PagerDuty, S3, or any external system. |
| INV-3: Frontend → Django public API only | React never calls the AI service (FastAPI) directly. Parse triggers go through `POST /api/v1/workflows/`. |
| INV-4: AI service is stateless and advisory | The AI service has no database access, no event bus connection, no user state. It receives payloads from Django and returns transformed results. |
| INV-5: API versioning | All domain endpoints are under `/api/v1/...`. Internal runner endpoints are under `/api/v1/internal/...`. Operational endpoints (`/health/...`, `/metrics/`) are outside the API namespace. |

---

## 2. Runner step-start contract (B-03)

**Established:** Phase 10.1 + Phase 10.2 (applies from Phase 10.1 onward)

All steps — whether or not they have `requiresApproval: true` in the workflow definition — are normalized through a step-start endpoint before the runner acts on them. Django returns a `runner_action` value that tells the runner exactly what to do.

**Contract:**

```
POST /api/v1/internal/executions/{id}/steps/{step_id}/start
→ {
    "runner_action": "run" | "wait_for_approval" | "blocked",
    "step_id": "...",
    "step_name": "...",
    "command": "..." | null,
    "approval_request_id": "..." | null,  // present when runner_action == "wait_for_approval"
    "blocked_reason": "..." | null        // present when runner_action == "blocked"
  }
```

| `runner_action` value | Meaning | Runner behavior |
|---|---|---|
| `run` | Execute the step now | Execute `command` and report result |
| `wait_for_approval` | Step requires human approval | Poll until approved or timed out |
| `blocked` | Step blocked by policy | Mark step as blocked, stop execution |

The runner must not special-case `requiresApproval: true` from the workflow schema — Django resolves the action. This contract covers both workflow-flag approvals (Phase 10.1) and policy-driven approvals (Phase 10.2).

---

## 3. Policy conflict resolution (B-01)

**Established:** Phase 10.2 + Roadmap §4.2

When multiple policies match a step, the outcome is determined by **first-match wins** using a deterministic sort key:

```
Sort key: (rule.priority ASC, policy.created_at ASC, policy.id ASC, rule.id ASC)
```

The first matching rule in this sorted order wins. "Stricter outcome wins" is incorrect and must not appear in any blueprint or implementation.

---

## 4. AutoApprove and the `requiresApproval` floor (B-06 / K-B06)

**Established:** Phase 10.2

- `requiresApproval: true` in the workflow schema is an **absolute floor** that policies cannot waive.
- If a policy returns `AutoApprove` for a step that has `requiresApproval: true`, the outcome is silently upgraded to `RequireApproval`. AutoApprove is ignored.
- Policies may only **escalate** the schema's risk/approval requirements, never reduce them.

---

## 5. Audit trail guarantees (H-03)

**Established:** Phase 10.3

Phase 10's audit trail is **application-level append-only**, not database-level immutable. What this provides and does not provide:

| Provided | Not provided |
|---|---|
| No Django service function provides a delete or update path for audit events | Protection against DBA-level direct SQL writes |
| Canonical emit ordering: `transaction.atomic()` + audit write inside + integration/SSE dispatch via `transaction.on_commit()` | Multi-record transaction atomicity guarantee at the application layer |
| Application role must NOT have `UPDATE`/`DELETE` grants on the audit table | Protection against compromised Django credentials |
| PITR backup required in production | Immutability under audit log export |

**Canonical audit emit pattern** (Phase 10.3 §canonical ordering):

```python
with transaction.atomic():
    # 1. State transition (domain object save)
    execution.status = new_status
    execution.save()
    # 2. Audit write IN the same transaction
    AuditEvent.objects.create(event_type=..., actor_label=..., ...)
    # 3. Integration and SSE dispatch AFTER commit
    transaction.on_commit(lambda: IntegrationService.notify(...))
    transaction.on_commit(lambda: execution_event_bus.emit(...))
```

---

## 6. Pre-auth actor labels (K-H08)

**Established:** Phase 10.1

Before Phase 10.7 auth exists, Django cannot verify who the approving actor is — the runner supplies a `actor_display_name` string in the approval decision payload. This is informational only.

- Pre-auth approval decisions must set `decided_by_label_source = "unverified_pre_auth"`.
- Phase 10.7 must replace this with `decided_by_label_source = "verified_auth"` and ignore client-supplied labels entirely.
- Audit consumers must not treat `"unverified_pre_auth"` labels as authoritative identity.

---

## 7. Health endpoint split (H-02)

**Established:** Phase 10.9

Three distinct endpoints. ALB target health check MUST use `/health/ready/` only.

| Endpoint | Checks | ALB use | Docker-compose healthcheck |
|---|---|---|---|
| `GET /health/live` | None (process alive) | No | No |
| `GET /health/ready/` | DB connection + migrations only | **Yes** | **Yes** |
| `GET /health/` | DB + AI service | No | No |

**INVARIANT:** ALB must never use `/health/`. AI service being unreachable must not remove Django API containers from the load balancer rotation.

---

## 8. SSE event bus — process-local constraint (B-04, B-05)

**Established:** Phase 10.8

The SSE event bus is in-process and process-local. Two critical constraints:

**B-04 — ASGI loop capture:** `emit()` (called from sync Django service code) must use a captured ASGI loop reference, NOT `asyncio.get_running_loop()`. Sync workers in uvicorn's threadpool have no running event loop — `get_running_loop()` silently returns no-op.

```python
# Correct: capture loop at startup
def _get_asgi_event_loop() -> asyncio.AbstractEventLoop | None:
    return _CAPTURED_ASGI_LOOP  # set once in ExecutionsConfig.ready()

def emit(self, execution_id: str, event: StreamEvent) -> None:
    loop = _get_asgi_event_loop()
    if loop is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(
        lambda: asyncio.ensure_future(self._async_emit(execution_id, event))
    )
```

**B-05 — Multi-task SSE gate:** Sticky sessions on ALB do NOT solve the multi-task event routing problem. The runner and the browser are different clients. Before enabling API `desired_count ≥ 2` in ECS, make an explicit architectural choice:
- Option A: Pin API task count at 1 (availability tradeoff, staging-only).
- Option B: Externalize bus to Redis pub/sub, Postgres LISTEN/NOTIFY, or AWS EventBridge.

---

## 9. Internal endpoint network isolation (H-01)

**Established:** Phase 10.10

`/api/v1/internal/...` endpoints must not be reachable from the public internet. Django-level runner token authentication is insufficient as sole protection.

Mandatory: ALB listener rule blocks `/api/v1/internal/` from outside private subnet CIDR, OR a second internal ALB serves `/api/v1/internal/` exclusively.

**Gate:** Confirm via `curl` from outside the VPC that `/api/v1/internal/claim-next` returns a network-level rejection before Phase 10.10 is complete.

---

## 10. Metrics endpoint fail-closed (H-08)

**Established:** Phase 10.9

`/metrics/` exposes organization-level operational intelligence. It must fail-closed:

- If `PROMETHEUS_METRICS_ENABLED=True` and `PROMETHEUS_METRICS_TOKEN` is empty/unset, Django startup raises `ImproperlyConfigured`.
- Default: `PROMETHEUS_METRICS_ENABLED=False`.
- The endpoint returns HTTP 403 without a valid `Authorization: Bearer <token>` header.

---

## 11. CSP middleware must be registered (H-07)

**Established:** Phase 10.9

`CSP_*` settings in `prod.py` have no effect unless `csp.middleware.CSPMiddleware` is in `MIDDLEWARE` AND `django-csp>=3.7` is in `requirements/base.txt`. Missing either one silently omits the `Content-Security-Policy` header from all responses.

Required verification test: `test_csp_header_present_in_response`.

---

## 12. Org identity source-of-truth (K-M10)

**Established:** Phase 10.7

After Phase 10.7 auth, `X-Organization-Id` header is the single source of org scope. Body/query `organization_id` fields are redundant.

- When both are present, they must match. Mismatch → HTTP 400 `org_id_mismatch`.
- The header wins. Body fields should be removed in the Phase 10.7 cleanup pass.

**Endpoints exempt from `X-Organization-Id`:** `POST /api/v1/auth/login/`, `POST /api/v1/auth/refresh/`, `GET /api/v1/auth/me/`, `GET /health/...`, `GET /metrics/`, all `/api/v1/internal/...`.

---

## 13. User FK on_delete policy (K-L04)

**Established:** Phase 10.7

All FKs from domain models to `User` that are adjacent to audit/approval records use `on_delete=SET_NULL`:

- `ApprovalDecision.decided_by` — `SET_NULL`
- `AuditEvent.actor_user` — `SET_NULL`
- `Integration.created_by` — `SET_NULL`
- `Policy.created_by` — `SET_NULL`

`PROTECT` blocks user deletion after any audit or approval activity, contradicting Phase 10.3's denormalized-snapshot rationale. Identity is preserved in `actor_label` / `decided_by_label` snapshot fields.

---

## 14. DNS-safe SSRF dispatch (K-H11)

**Established:** Phase 10.5

Integration dispatch must resolve DNS once and pin the resolved IP for the `httpx` call. Do NOT resolve at validation time and then let `httpx` re-resolve independently (DNS TOCTOU attack surface).

Pattern: `_resolve_and_validate(url)` → returns `(resolved_ip, hostname)` → construct pinned URL → set `Host` header to original hostname → call with `verify=True`.

---

## 15. Integration dispatch budget (H-06)

**Established:** Phase 10.5

Integration dispatch is synchronous (on `transaction.on_commit()`). Multiple integrations add latency to runner request paths.

Mandatory settings:
- `INTEGRATION_DISPATCH_BUDGET_SECONDS=6.0` — total wall-clock budget for all integrations on one trigger
- `INTEGRATION_MAX_PER_TRIGGER=5` — max integrations dispatched per event

Integrations run in parallel via `ThreadPoolExecutor`; those that don't complete within the budget are cancelled and recorded as `error_detail="dispatch_budget_exceeded"`.

---

## 16. Summarize execution via on_commit (K-H07)

**Established:** Phase 10.6

`summarize_execution()` must be dispatched via `transaction.on_commit()`, not called inline in `complete_execution()`. Inline calls hold `AI_READ_TIMEOUT_SECONDS` (60s) on the runner's terminal-status HTTP call.

Default: `AI_SUMMARIZE_ENABLED=False`. Enable explicitly in staging when evaluating the feature.

---

## 17. Pre-auth AI safety controls (H-05)

**Established:** Phase 10.6

Phase 10.6 ships AI parsing before Phase 10.7 per-org opt-in. Required controls:

- `AI_PARSE_REQUIRES_PRIVATE_ENV=True` — startup fails in public environments until Phase 10.7 per-org consent exists
- `AI_PARSE_DAILY_BUDGET_USD=10.0` — parse calls return HTTP 429 when daily cost estimate is exceeded
- AI parse cache key must include: model version + prompt version + schema version + org_id (not content hash alone)
- `AI_PARSE_MODEL` default must be a pinned dated alias (e.g., `gpt-4o-2024-11-20`), not a floating alias

---

## 18. Artifact creation canonical ordering (K-M08)

**Established:** Phase 10.4

Canonical sequence: validate quota → write storage → create DB row (in atomic).

Storage write FIRST. A failed storage write leaves no DB row (no cleanup). A failed DB write after storage triggers best-effort storage delete and logs the failure. `upload_status="failed"` rows should not exist in Phase 10.4 steady state.

---

## 19. Artifact quota — both limits are mandatory (C-M01)

**Established:** Phase 10.4

Both per-execution total bytes and per-runner daily bytes limits are **mandatory**, not optional:

- `ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION=262144000` (250 MB)
- `ARTIFACT_DAILY_BYTES_PER_RUNNER=1073741824` (1 GB)

---

## 20. Approval timeout recovery (K-M07)

**Established:** Phase 10.1 (noted), Phase 10.9 (implemented)

If `ApprovalRequest.expires_at` is set and the deadline passes without a decision, the execution remains blocked indefinitely. Phase 10.9's `check_stuck_executions` management command must also sweep for expired approvals via `recover_expired_approvals()`.

Phase 10.1 must add `expires_at` to `ApprovalRequest`; Phase 10.9 consumes it.

---

## 21. AUTH_USER_MODEL migration preflight (H-04)

**Established:** Phase 10.7

Before starting Phase 10.7 Milestone 1, verify:
1. No production user data exists in `auth_user`.
2. No domain migrations reference `auth.User` directly.
3. `make bootstrap` is available as reset mechanism for dev/staging.

If checks fail, create a separate migration plan before proceeding. Do not implement Phase 10.7 on a database with inconsistent auth migration state.
