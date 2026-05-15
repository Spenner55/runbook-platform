# Phase 10.5: Integrations Expansion Blueprint

| Field | Value |
|---|---|
| Phase number | 10.5 |
| Phase name | Integrations |
| Objective | Add Django-controlled outbound notification support so execution events reach external systems (Slack-like webhooks, generic webhooks) without affecting execution state or introducing queue infrastructure. |
| Status | Blueprint only |
| Depends on | Phases 01–09 complete and verified; Phase 10.1 approvals complete and verified; Phase 10.2 policies complete and verified; Phase 10.3 audit trail complete and verified; Phase 10.4 artifacts complete and verified |
| Authored | 2026-04-24 |

---

## 1. Purpose and sequencing rationale

Integrations connect the platform to the organizations and tools that surround it. When an execution fails, Slack should know. When an approval is requested, a webhook can notify an on-call system. When a high-risk execution completes successfully, a ticket-tracking tool can log the evidence. Without integrations, every operator must manually refresh the platform UI to find out what happened — integrations make the platform ambient rather than polling.

Phase 10.5 comes after artifacts for three reasons that are not arbitrary.

**The event payload is now rich enough to be useful.** After Phase 10.1–10.4, a completed execution carries: approval decisions, policy evaluations, audit records, and artifact references. A Slack notification that says "execution 4c1a failed at step 3 (approve-database-change); stderr artifact available" is actionable. A notification from a Phase 01–09 system that says "execution failed" is noise. Integrations built before approvals, audit, and artifacts would need to be rebuilt once those events became stable.

**External secrets require the audit trail to be active.** Storing a Slack webhook URL or PagerDuty API key is a credential rotation event. That rotation must be auditable. Phase 10.3 audit makes that possible. Adding integration credential storage before audit exists means the rotation history is unrecoverable.

**The organization model is stable.** Integrations are scoped to organizations. The organization model has been exercised through executions (Phase 01–09) and artifact uploads (Phase 10.4). It is stable enough that the integration records can reference it without structural churn.

Phase 10.5 comes before richer AI parsing (Phase 10.6) because integrations are the mechanism that will eventually carry AI-generated summaries of completed executions. Implementing integrations first means that when AI enrichment is added (Phase 10.6), the delivery channel already exists and can simply receive a new event type or a richer payload.

**What Phase 10.5 does not do:**

- It does not implement PagerDuty Events API v2 integration. That integration type is extensible here but deferred until a real organization requests it.
- It does not implement Jira ticket creation or issue linking. Same deferral.
- It does not add queue infrastructure. Dispatch is synchronous with a 3-second timeout per call.
- It does not allow integrations to affect execution state. A failed Slack call cannot fail an execution.
- It does not allow the runner to call external systems. The runner's only dependency remains the Django internal API.

At blueprint authoring time, the checked-out source tree shows:

- `apps/api/apps/integrations/` contains only `__init__.py`.
- `apps/api/apps/approvals/`, `apps/api/apps/audit/`, and `apps/api/apps/artifacts/` also contain only `__init__.py` stubs. This confirms all Phase 10.1–10.4 features are not yet implemented in the current working tree.
- `apps/api/apps/executions/` is fully implemented with models, services, serializers, views, and tests covering the execution state machine.
- `apps/api/apps/common/` provides `BaseModel` (UUID PK, `created_at`, `updated_at`), a domain exception hierarchy, and a custom DRF error envelope.
- `apps/api/config/settings/base.py` registers only five apps: `common`, `organizations`, `runbooks`, `workflows`, `executions`. No phase 10 apps are registered yet.
- `apps/api/config/api_v1_urls.py` registers public ViewSets and four internal runner endpoints, all under `/api/v1/`.
- `.env.example` does not yet have integration-related settings.
- `docker-compose.yml` has no artifact media volume or Fernet key setting.

This blueprint assumes the requested baseline: Phases 01–09, approvals, policies, audit, and artifacts are complete and verified. All references to those systems in this blueprint assume they have been fully implemented.

---

## 2. Current-state inspection checklist

Before implementation begins, re-read the source files in this order. Do not implement from memory.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` section 4.5 and confirm integrations still precede AI parsing and auth.
- [ ] Read `docs/blueprints/phase-10-04-artifacts-blueprint.md` and confirm Phase 10.4 artifact events are stable.
- [ ] Inspect `apps/api/apps/integrations/` for any partial implementation.
- [ ] Inspect `apps/api/apps/audit/` for the current `AuditService.emit(...)` signature and event type taxonomy.
- [ ] Inspect `apps/api/apps/approvals/` for `ApprovalService` methods that will become integration trigger points.
- [ ] Inspect `apps/api/apps/artifacts/` for the upload service method that will become a trigger point.
- [ ] Inspect `apps/api/apps/executions/services.py` to confirm which service functions trigger state transitions that need integration hooks.
- [ ] Inspect `apps/api/apps/executions/models.py` to confirm `Execution.Status` and `ExecutionStep.Status` enum values.
- [ ] Inspect `apps/api/apps/common/models.py` to confirm `BaseModel` fields.
- [ ] Inspect `apps/api/apps/common/exceptions.py` to confirm the domain exception hierarchy.
- [ ] Inspect `apps/api/apps/common/api_errors.py` to confirm the error envelope structure: `{"errors": [{"code": ..., "detail": ..., "attr": ...}]}`.
- [ ] Inspect `apps/api/apps/organizations/models.py` to confirm the `Organization` model.
- [ ] Inspect `apps/api/config/settings/base.py`, `dev.py`, `prod.py`, and `test.py` to understand the settings pattern before adding integration settings.
- [ ] Inspect `apps/api/config/api_v1_urls.py` to understand registration conventions before adding integration URLs.
- [ ] Inspect `apps/web/src/shared/api/client.ts` and `apps/web/src/shared/lib/queryKeys.ts` to confirm frontend API patterns.
- [ ] Inspect `apps/web/src/features/executions/` to understand the execution feature structure before adding integrations feature.
- [ ] Inspect `apps/web/src/app/router.tsx` to confirm routing conventions before adding integration settings route.
- [ ] Confirm `cryptography` is available in `apps/api/requirements/` or plan to add it for Fernet encryption.
- [ ] Confirm `httpx` is available in `apps/api/requirements/` for outbound calls (it may already be present for the AI service).
- [ ] Run current tests before starting: `docker compose exec api pytest`, runner tests, web tests.

---

## 3. Architecture invariants and boundaries

These invariants are non-negotiable for Phase 10.5. Any implementation approach that requires violating one of them is wrong.

| Invariant | Phase 10.5 consequence |
|---|---|
| Django is the control plane. | All integration dispatch, credential storage, event formatting, URL validation, delivery logging, and audit emission live in Django services. |
| Runner talks only to Django internal APIs. | The runner never calls Slack, PagerDuty, webhooks, or any external system. Runner-triggered events reach integrations only because Django dispatch is called from execution service hooks. |
| Frontend talks only to Django public APIs. | The React app creates, updates, lists, and deactivates integrations through `/api/v1/integrations/`. It never calls external webhook endpoints directly, and it never receives or stores credentials. |
| AI service is stateless and advisory. | The AI service is not involved in integration dispatch in this phase. |
| All APIs remain under `/api/v1/`. | Public integration management APIs live under `/api/v1/integrations/`. |
| Internal runner APIs remain under `/api/v1/internal/`. | No integration API is on the internal router. Integrations are not a runner concern. |
| UUID primary keys remain standard. | `IntegrationConnection` and `IntegrationDeliveryAttempt` both inherit from `BaseModel`. |
| Business logic belongs in `services.py`. | Dispatch logic, credential encryption/decryption, SSRF validation, retry handling, and audit emission all live in `apps/api/apps/integrations/services.py`. Views handle request parsing only. |
| No premature queue infrastructure. | Dispatch is synchronous within the Django request/response cycle. No Celery, Kafka, RabbitMQ, SQS, EventBridge, background workers, or outboxes. |
| Integrations must not control execution state. | Dispatch failures are caught, logged to `IntegrationDeliveryAttempt`, and discarded. A failed webhook call cannot transition an execution to any status. The dispatch call is always wrapped in try/except before returning. |

Additional boundaries specific to Phase 10.5:

- Store encrypted credentials in the database; never in plaintext.
- Never return credential values in any API response. Return only a `credentials_configured: boolean` field.
- Never log credential values. Redact them from all log output and audit metadata.
- Enforce SSRF protection on all outbound URLs before dispatching.
- Do not allow integrations to inject commands, modify step behavior, or influence policy evaluation.
- Defer PagerDuty Events API v2 integration and Jira integration unless explicitly scoped.
- Do not add retries in Phase 10.5. Log failures and move on.

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.5 |
|---|---|
| `apps/api/apps/integrations/` | Implement app config, `IntegrationConnection` model, `IntegrationDeliveryAttempt` model, Fernet encryption utility, SSRF validator, notification service, serializers, public management views, URLs, admin, and tests. |
| `apps/api/apps/executions/` | Add `IntegrationService.notify(...)` calls at five state transition points in `services.py`. Do not change any execution state machine logic. |
| `apps/api/apps/approvals/` | Add `IntegrationService.notify(...)` call at approval request creation and approval decision points. |
| `apps/api/apps/artifacts/` | Add `IntegrationService.notify(...)` call at artifact upload completion if deemed useful for notifications (optional in Phase 10.5; see section 7). |
| `apps/api/apps/audit/` | Emit audit events when an integration connection is created, updated, deactivated, or deleted. Do not audit individual delivery attempts by default — delivery attempts have their own record. |
| `apps/api/apps/common/` | Add integration-specific exceptions only if the existing hierarchy is insufficient. Prefer reusing `DomainValidationError`, `DomainConflictError`, and `ExternalDependencyError`. |
| `apps/api/config/` | Register `apps.integrations`, add integration URLs under `/api/v1/integrations/`, add Fernet key and integration dispatch settings, add per-integration call timeout setting. |
| `apps/web/src/features/integrations/` | Add TypeScript types, API client functions, hooks, and feature-level tests. |
| `apps/web/src/routes/integrations/` | Add integrations settings page (list, create, deactivate) and integration detail page with delivery attempt history. |
| `apps/web/src/app/router.tsx` | Register integration settings routes. |
| `.env.example` | Add `INTEGRATION_FERNET_KEY` and `INTEGRATION_DISPATCH_TIMEOUT_SECONDS`. |

Likely backend files touched:

- `apps/api/apps/integrations/apps.py`
- `apps/api/apps/integrations/models.py`
- `apps/api/apps/integrations/admin.py`
- `apps/api/apps/integrations/crypto.py`
- `apps/api/apps/integrations/ssrf.py`
- `apps/api/apps/integrations/services.py`
- `apps/api/apps/integrations/serializers.py`
- `apps/api/apps/integrations/views.py`
- `apps/api/apps/integrations/urls.py`
- `apps/api/apps/integrations/migrations/0001_initial.py`
- `apps/api/apps/integrations/tests/test_models.py`
- `apps/api/apps/integrations/tests/test_crypto.py`
- `apps/api/apps/integrations/tests/test_ssrf.py`
- `apps/api/apps/integrations/tests/test_services.py`
- `apps/api/apps/integrations/tests/test_api.py`
- `apps/api/apps/executions/services.py` (add notify calls at transition points)
- `apps/api/apps/executions/tests/test_services.py` (add integration dispatch assertions)
- `apps/api/apps/approvals/services.py` (add notify calls)
- `apps/api/apps/approvals/tests/` (add dispatch assertions)
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/dev.py`
- `apps/api/config/settings/test.py`
- `apps/api/config/api_v1_urls.py`
- `.env.example`

Likely frontend files touched:

- `apps/web/src/features/integrations/types.ts`
- `apps/web/src/features/integrations/api/integrationsApi.ts`
- `apps/web/src/features/integrations/hooks/useIntegrations.ts`
- `apps/web/src/features/integrations/hooks/useCreateIntegration.ts`
- `apps/web/src/features/integrations/hooks/useDeactivateIntegration.ts`
- `apps/web/src/features/integrations/hooks/useIntegrationDelivery.ts`
- `apps/web/src/routes/integrations/IntegrationsPage.tsx`
- `apps/web/src/routes/integrations/IntegrationsPage.test.tsx`
- `apps/web/src/routes/integrations/IntegrationDetailPage.tsx`
- `apps/web/src/routes/integrations/IntegrationDetailPage.test.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/app/router.tsx`

Out of scope unless explicitly approved:

- PagerDuty Events API v2.
- Jira REST API integration.
- Retry infrastructure (exponential backoff, dead-letter queuing).
- Async dispatch (Celery, background tasks, async views).
- Inbound webhooks (receiving events from external systems).
- Integration marketplace or plugin registry.
- Auth changes (permissions remain `AllowAny` until Phase 10.7).
- Runner-side integration calls.
- AI service integration payload enrichment.

---

## 5. Data model: fields, constraints, indexes, secret handling

### 5.1 `IntegrationConnection`

`IntegrationConnection` represents one configured outbound channel for one organization. An organization may have multiple active connections of different types, or multiple connections of the same type with different targets.

Required fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits from `BaseModel`. |
| `organization` | FK to `organizations.Organization`, `PROTECT` | Required tenant boundary. |
| `type` | enum string | Required. Phase 10.5 values: `slack_webhook`, `generic_webhook`. Reserved but unimplemented: `pagerduty`. |
| `name` | `CharField(128)` | Human-readable label. Must be non-empty. Not unique globally, but unique per organization is strongly recommended. |
| `config` | `JSONField(default=dict)` | Non-secret, type-specific configuration. For `slack_webhook` and `generic_webhook`: `{"url": "https://..."}`. For `pagerduty` (future): `{"routing_key": "..."}` would go in `encrypted_credentials`, not config. |
| `encrypted_credentials` | `BinaryField(blank=True, null=True)` | Fernet-encrypted blob. For Phase 10.5, optional for webhook types because the webhook URL in `config` may be the only sensitive field. Include for future API-key-based types. |
| `event_types` | `JSONField(default=list)` | Allowlist of event type strings this connection should receive. Empty list means receive all. Allows organizations to configure a connection for only failure events, for example. |
| `is_active` | `BooleanField(default=True)` | Soft-disable without deleting delivery history. |
| `last_delivery_at` | `DateTimeField(null=True, blank=True)` | Denormalized convenience field. Updated on every delivery attempt. |
| `last_delivery_status` | `CharField(32, blank=True)` | `success` or `failed`. Denormalized for quick status display without a delivery query. |

`created_at` and `updated_at` come from `BaseModel`.

**`config` field sensitivity note:** For `slack_webhook` and `generic_webhook`, the `config.url` field is itself a sensitive credential (anyone with the URL can post to the webhook). This creates a dilemma: it is type-specific configuration, not a secret, but it must not be returned verbatim in API responses. Two acceptable approaches:

1. Store the URL encrypted in `encrypted_credentials` and use `config` only for non-sensitive metadata like `channel_name` or `description`.
2. Store the URL in `config` but ensure the serializer redacts it in responses, returning only a masked representation such as `https://hooks.slack.com/services/T.../B.../***`.

**Recommended for Phase 10.5:** Store the webhook URL in `encrypted_credentials` alongside other type-specific secrets. Use `config` only for non-sensitive metadata. This eliminates ambiguity about what gets redacted. See credential handling rules in section 9.

### 5.2 `IntegrationDeliveryAttempt`

`IntegrationDeliveryAttempt` records every outbound call made for any integration. It is the primary debugging and visibility record for delivery failures.

Required fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits from `BaseModel`. |
| `integration` | FK to `IntegrationConnection`, `CASCADE` | Deleting the integration deletes its delivery history. This is acceptable; delivery history has no legal retention requirement in Phase 10.5. |
| `organization` | FK to `organizations.Organization`, `PROTECT` | Denormalized for efficient tenant-scoped queries. |
| `event_type` | `CharField(64)` | The event that triggered this delivery, e.g. `execution.completed`, `approval.requested`. |
| `payload_preview` | `JSONField(default=dict)` | A safe subset of the payload sent, with no secrets, credentials, or claim tokens. Used for debugging without requiring log access. |
| `http_status` | `IntegerField(null=True, blank=True)` | HTTP status returned by the external endpoint. Null if network error prevented the call from completing. |
| `success` | `BooleanField` | True if the call returned 2xx. |
| `error_detail` | `TextField(blank=True)` | Short human-readable description of the failure reason. Never include stack traces, credentials, or raw exception messages that might expose secrets. |
| `latency_ms` | `PositiveIntegerField(null=True, blank=True)` | Round-trip latency in milliseconds. |
| `attempted_at` | `DateTimeField` | Set by service. Not `auto_now_add` — set explicitly to stay inside the dispatch transaction or as close to dispatch time as possible. |

`created_at` and `updated_at` come from `BaseModel`.

### 5.3 Relationships and multi-tenancy

- Every `IntegrationConnection` belongs to exactly one organization.
- Every `IntegrationDeliveryAttempt` belongs to exactly one `IntegrationConnection` and exactly one organization.
- When dispatching notifications, the service queries only connections for the execution's organization.
- No cross-organization event delivery is ever intentional.

### 5.4 Indexes

Recommended indexes:

| Index | Purpose |
|---|---|
| `(organization, is_active, type)` | Efficient dispatch query: all active connections for this org. |
| `(organization, created_at)` | Organization-scoped management listing. |
| `(integration, attempted_at)` | Integration detail delivery history. |
| `(organization, attempted_at)` | Organization-wide delivery history browsing. |
| `(event_type, attempted_at)` | Future debugging: find all deliveries for a specific event type. |

### 5.5 Constraints

- `type` must be one of the declared enum values.
- `name` must be non-empty and no longer than 128 characters.
- `config` must be a JSON object and must not exceed a practical size (e.g., 4 KB).
- `event_types` must be a JSON array of known event type strings or empty.
- `encrypted_credentials` must be a Fernet-encrypted blob when present, or null.

Cross-field constraint: if `type` is `slack_webhook` or `generic_webhook` and no credentials are set, the service must reject creation.

### 5.6 Secret handling

Secrets in `encrypted_credentials`:

- The `INTEGRATION_FERNET_KEY` environment variable holds a 32-byte base64-encoded Fernet key.
- Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `apps/api/apps/integrations/crypto.py` wraps `cryptography.fernet.Fernet` with two functions: `encrypt_credentials(plaintext: dict) -> bytes` and `decrypt_credentials(ciphertext: bytes) -> dict`.
- The service calls `encrypt_credentials` before saving and `decrypt_credentials` before dispatching.
- The encryption key must never appear in logs, API responses, audit metadata, or error messages.
- If `INTEGRATION_FERNET_KEY` is missing at startup, Django startup should fail with a clear configuration error, not silently proceed.
- For tests, generate a per-test Fernet key in the test fixture. Do not use a hardcoded test key that ships in the repository.
- Key rotation: not in scope for Phase 10.5. Document that rotation requires re-encrypting all `encrypted_credentials` rows and is a future operational task.

What `encrypted_credentials` stores (Phase 10.5):

```python
# For slack_webhook and generic_webhook
{
    "url": "https://hooks.slack.com/services/T.../B.../<token>"
}

# For pagerduty (future)
{
    "routing_key": "<pagerduty-events-api-v2-routing-key>"
}
```

Redaction rules (see also section 9):

- The `encrypted_credentials` column is never returned by any serializer.
- The API response for a connection includes `credentials_configured: boolean` derived from `encrypted_credentials is not None`.
- The `config` field is returned in responses but must not contain secrets. If the implementation stores any secret in `config`, the serializer must redact it.
- `payload_preview` in `IntegrationDeliveryAttempt` must never include the webhook URL, the encryption key, or any credential value.

### 5.7 Deletion semantics

- No public delete endpoint in Phase 10.5. Use deactivation (`is_active=False`) instead.
- Admin deletion is allowed for support use but should emit an audit event.
- If explicit deletion is required in a later phase, it must cascade to delivery attempts and emit an audit event.

---

## 6. API contracts for integration CRUD and event delivery visibility

### 6.1 Integration management endpoints

```http
GET    /api/v1/integrations/
POST   /api/v1/integrations/
GET    /api/v1/integrations/{id}/
PATCH  /api/v1/integrations/{id}/
POST   /api/v1/integrations/{id}/deactivate/
```

No DELETE endpoint. No PUT (use PATCH for partial updates).

### 6.2 `GET /api/v1/integrations/`

Response:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "organization_id": "uuid",
      "type": "slack_webhook",
      "name": "Ops Slack",
      "config": {},
      "credentials_configured": true,
      "event_types": [],
      "is_active": true,
      "last_delivery_at": "2026-04-24T18:00:00Z",
      "last_delivery_status": "success",
      "created_at": "2026-04-20T10:00:00Z",
      "updated_at": "2026-04-24T18:00:00Z"
    }
  ]
}
```

Rules:
- Never return `encrypted_credentials`.
- `credentials_configured` is `true` if `encrypted_credentials` is not null.
- Filter by `organization_id` derived from request context (pre-auth placeholder; add queryset filter by organization when auth is active in Phase 10.7).

### 6.3 `POST /api/v1/integrations/`

Request:

```json
{
  "type": "slack_webhook",
  "name": "Ops Slack",
  "organization_id": "uuid",
  "credentials": {
    "url": "https://hooks.slack.com/services/..."
  },
  "config": {},
  "event_types": ["execution.failed", "approval.requested"]
}
```

Rules:
- `credentials` is write-only. Never echoed back. Encrypted and stored in `encrypted_credentials`.
- `config` is stored as-is. Validate that it is a JSON object, not an array or scalar.
- The service validates the URL in `credentials.url` against the SSRF blocklist before saving.
- Response is the same shape as GET, omitting `encrypted_credentials` and `credentials`.
- Emits `integration.created` audit event synchronously.

Recommended error codes:

| Code | Status | Condition |
|---|---|---|
| `integration_credentials_required` | 400 | `credentials` missing or empty. |
| `integration_invalid_url` | 400 | URL in credentials fails SSRF validation or is not a valid HTTPS URL. |
| `integration_invalid_type` | 400 | Unrecognized `type` value. |
| `integration_invalid_event_types` | 400 | `event_types` contains an unrecognized event type string. |
| `integration_name_required` | 400 | `name` is empty or missing. |

### 6.4 `PATCH /api/v1/integrations/{id}/`

Partial update. Fields that can be patched:
- `name`
- `config`
- `event_types`
- `credentials` (write-only; triggers re-encryption and re-validation)
- `is_active` (prefer the explicit `deactivate/` action, but PATCH is also acceptable)

Fields that cannot be patched: `type`, `organization_id`, `id`.

Emits `integration.updated` audit event.

### 6.5 `POST /api/v1/integrations/{id}/deactivate/`

Sets `is_active=False`. Idempotent. Returns the updated integration. Emits `integration.deactivated` audit event.

No request body required. Use this endpoint instead of PATCH for explicit deactivation to produce an auditable named action.

### 6.6 `GET /api/v1/integrations/{id}/`

Returns single integration with the same shape as list results.

### 6.7 Delivery attempt endpoints

```http
GET /api/v1/integrations/{id}/deliveries/
GET /api/v1/integrations/{id}/deliveries/{delivery_id}/
```

`GET /api/v1/integrations/{id}/deliveries/` response:

```json
{
  "count": 10,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "integration_id": "uuid",
      "event_type": "execution.failed",
      "payload_preview": {
        "execution_id": "uuid",
        "execution_status": "failed",
        "organization_id": "uuid"
      },
      "http_status": 200,
      "success": true,
      "error_detail": "",
      "latency_ms": 143,
      "attempted_at": "2026-04-24T18:00:00Z"
    }
  ]
}
```

Rules:
- Never return the actual payload sent (only `payload_preview`).
- Never return the webhook URL.
- Sort newest-first by default.
- Paginate: default 50 results, max 200.

---

## 7. Service contracts and notification trigger points

### 7.1 `IntegrationService` responsibilities

`apps/api/apps/integrations/services.py` owns:

1. `create_connection(*, organization, type, name, config, credentials, event_types)` — validates, encrypts, creates record, emits audit event.
2. `update_connection(*, connection, **fields)` — validates changed fields, re-encrypts if credentials changed, saves, emits audit event.
3. `deactivate_connection(*, connection)` — sets `is_active=False`, saves, emits audit event.
4. `notify(*, event_type: str, context: dict, organization_id: str)` — main dispatch entry point. Queries active connections for the organization, filters by `event_types` if set, formats payload per connection type, dispatches, records `IntegrationDeliveryAttempt`. Never raises. Always wrapped in try/except at the outermost level.
5. `_build_payload(*, connection, event_type, context)` — returns a JSON-serializable dict for the given connection type. Internal to services.
6. `_dispatch_webhook(*, url: str, payload: dict, timeout_seconds: float)` — performs the outbound `httpx` POST with timeout. Returns `(http_status, latency_ms, error_detail)`. Never raises network exceptions to the caller.
7. `_validate_outbound_url(url: str)` — SSRF check. Raises `DomainValidationError` if the URL targets private IPs, localhost, link-local addresses, or known metadata endpoints.

### 7.2 `notify()` contract

```python
def notify(
    *,
    event_type: str,
    context: dict,
    organization_id: str,
) -> None:
    """
    Dispatch notifications to all active integrations for the organization.

    This function never raises. Delivery failures are logged to
    IntegrationDeliveryAttempt and discarded. The caller's execution
    state is not affected by dispatch outcomes.
    """
```

Internal flow:

1. Query `IntegrationConnection.objects.filter(organization_id=organization_id, is_active=True)`.
2. For each connection, check if `event_type` is in `connection.event_types` (or if `event_types` is empty, which means "all events").
3. Decrypt credentials with `decrypt_credentials(connection.encrypted_credentials)`.
4. Build payload with `_build_payload(connection=connection, event_type=event_type, context=context)`.
5. Call `_dispatch_webhook(url=credentials["url"], payload=payload, timeout_seconds=settings.INTEGRATION_DISPATCH_TIMEOUT_SECONDS)`.
6. Record `IntegrationDeliveryAttempt` with outcome.
7. Update `connection.last_delivery_at` and `connection.last_delivery_status` outside the delivery attempt record if practical.
8. Continue to the next connection regardless of outcome.
9. Wrap the entire per-connection block in try/except to ensure one connection's failure does not prevent others from being attempted.

### 7.3 Payload format

**`slack_webhook` payload:**

```json
{
  "text": "Execution {id} {status} in workflow {workflow_name}",
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Execution {id}* — Status: `{status}`\nWorkflow: {workflow_name}\nOrganization: {org_name}"
      }
    }
  ]
}
```

For failed executions, include:
- Step where failure occurred (name and position).
- Whether artifacts are available (from context).
- Whether an approval decision was involved (from context).

**`generic_webhook` payload:**

```json
{
  "event_type": "execution.failed",
  "occurred_at": "2026-04-24T18:00:00Z",
  "organization_id": "uuid",
  "execution_id": "uuid",
  "execution_status": "failed",
  "workflow_name": "Deploy API",
  "failed_step_name": "Approve Database Migration",
  "failed_step_position": 3,
  "has_artifacts": true
}
```

Rules that apply to all payload formats:
- Never include `claim_token`.
- Never include `encrypted_credentials`.
- Never include step commands.
- Never include artifact storage keys.
- Never include raw error output (include only a brief `error_summary` string if present).
- `payload_preview` stored in `IntegrationDeliveryAttempt` is a safe subset of this — omit any field that could be large or sensitive.

### 7.4 Trigger points

Five trigger points in Phase 10.5:

| Call site | Event type | Context fields |
|---|---|---|
| `ExecutionService.complete_execution(...)` when `outcome == "succeeded"` | `execution.completed` | `execution_id`, `organization_id`, `workflow_name`, `execution_status`, `started_at`, `finished_at` |
| `ExecutionService.complete_execution(...)` when `outcome == "failed"` | `execution.failed` | `execution_id`, `organization_id`, `workflow_name`, `execution_status`, `started_at`, `finished_at`, `failed_step_name`, `failed_step_position` |
| `ExecutionService.create_execution(...)` after the execution record is created | `execution.started` | `execution_id`, `organization_id`, `workflow_name`, `execution_status` |
| `ApprovalService.create_approval_request(...)` after the request is created | `approval.requested` | `execution_id`, `organization_id`, `step_name`, `step_position`, `approval_request_id` |
| `ApprovalService.decide_approval(...)` after the decision is recorded | `approval.decided` | `execution_id`, `organization_id`, `step_name`, `approval_request_id`, `decision` (approved/rejected) |

**Optional Phase 10.5 trigger:**

| Call site | Event type | Notes |
|---|---|---|
| `ArtifactService.create_from_runner_upload(...)` | `artifact.uploaded` | Only include if there is a product use case for real-time artifact notifications. Defer if not requested. |

**Ordering rule:** The `notify()` call must always occur *after* the state change is committed to the database. Use `transaction.on_commit()` so dispatch is guaranteed to run after the `atomic()` block exits, without holding the transaction open:

```python
# Correct ordering — via on_commit so dispatch cannot hold the transaction
def complete_execution(...):
    with transaction.atomic():
        execution.status = outcome
        execution.save(...)
        # Capture values before on_commit runs (execution may change)
        execution_id = str(execution.id)
        organization_id = str(execution.organization_id)
        transaction.on_commit(lambda: IntegrationService.notify(
            event_type="execution.failed",
            context={"execution_id": execution_id, ...},
            organization_id=organization_id,
        ))
    return execution
```

> **ARCHITECTURE DECISION (H-06): Synchronous integration dispatch must have a per-trigger budget to bound the latency added to runner request paths.**
>
> Even with `transaction.on_commit()`, `notify()` is still called synchronously in the same HTTP request/response cycle (on_commit runs when the outer transaction commits, which is before the response returns to the runner). Multiple enabled integrations running sequentially can add `N × INTEGRATION_DISPATCH_TIMEOUT_SECONDS` latency to the runner's terminal-status call. A runner reporting a step complete should not wait 3 × N seconds for integration webhooks.

Add to `base.py`:
```python
INTEGRATION_DISPATCH_BUDGET_SECONDS = env.float("INTEGRATION_DISPATCH_BUDGET_SECONDS", default=6.0)
INTEGRATION_MAX_PER_TRIGGER = env.int("INTEGRATION_MAX_PER_TRIGGER", default=5)
```

In `IntegrationService.notify()`:
1. Limit to `INTEGRATION_MAX_PER_TRIGGER` active integrations per trigger event. If more than this number are enabled, log a warning and skip the excess (choose deterministically by `integration.created_at` ascending).
2. Dispatch integrations in parallel using `concurrent.futures.ThreadPoolExecutor(max_workers=INTEGRATION_MAX_PER_TRIGGER)` with `as_completed(futures, timeout=INTEGRATION_DISPATCH_BUDGET_SECONDS)`. Any integration that does not return within the budget is cancelled and recorded as `success=False, error_detail="dispatch_budget_exceeded"`.

This keeps integration dispatch predictably bounded regardless of how many integrations an organization enables.

### 7.5 Timeout and error handling

- `INTEGRATION_DISPATCH_TIMEOUT_SECONDS` setting, default 3.0.
- Apply as both connect and read timeout on the `httpx` call.
- If the external endpoint does not respond within 3 seconds, the attempt is recorded as `success=False`, `http_status=None`, `error_detail="timeout"`.
- If the external endpoint returns a non-2xx response, `success=False`, `http_status=<status>`.
- No retries in Phase 10.5. Document this as a known limitation.
- Use `httpx.Client` (synchronous) rather than `httpx.AsyncClient` because Django views are synchronous in Phase 10.5. The 3-second timeout makes the synchronous call acceptable.

---

## 8. Frontend data contracts and settings UI

### 8.1 TypeScript contracts

```typescript
export type IntegrationType = 'slack_webhook' | 'generic_webhook'

export type IntegrationEventType =
  | 'execution.started'
  | 'execution.completed'
  | 'execution.failed'
  | 'approval.requested'
  | 'approval.decided'

export interface IntegrationConnection {
  id: string
  organization_id: string
  type: IntegrationType
  name: string
  config: Record<string, unknown>
  credentials_configured: boolean
  event_types: IntegrationEventType[]
  is_active: boolean
  last_delivery_at: string | null
  last_delivery_status: 'success' | 'failed' | null
  created_at: string
  updated_at: string
}

export interface IntegrationConnectionCreate {
  type: IntegrationType
  name: string
  organization_id: string
  credentials: { url: string }
  config?: Record<string, unknown>
  event_types?: IntegrationEventType[]
}

export interface IntegrationDeliveryAttempt {
  id: string
  integration_id: string
  event_type: string
  payload_preview: Record<string, unknown>
  http_status: number | null
  success: boolean
  error_detail: string
  latency_ms: number | null
  attempted_at: string
}

export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
```

### 8.2 Query keys

Add to `apps/web/src/shared/lib/queryKeys.ts`:

```typescript
integrations: (organizationId?: string) => ['integrations', organizationId ?? 'all'] as const,
integration: (integrationId: string) => ['integration', integrationId] as const,
integrationDeliveries: (integrationId: string) => ['integration-deliveries', integrationId] as const,
```

### 8.3 API client functions

```typescript
// apps/web/src/features/integrations/api/integrationsApi.ts

export async function listIntegrations(organizationId?: string): Promise<PaginatedResponse<IntegrationConnection>>
export async function getIntegration(id: string): Promise<IntegrationConnection>
export async function createIntegration(data: IntegrationConnectionCreate): Promise<IntegrationConnection>
export async function patchIntegration(id: string, data: Partial<IntegrationConnectionCreate>): Promise<IntegrationConnection>
export async function deactivateIntegration(id: string): Promise<IntegrationConnection>
export async function listIntegrationDeliveries(integrationId: string): Promise<PaginatedResponse<IntegrationDeliveryAttempt>>
```

### 8.4 Hooks

```typescript
useIntegrations(organizationId?: string)       // list integrations
useIntegration(id: string)                     // single integration detail
useCreateIntegration()                         // mutation
useDeactivateIntegration()                     // mutation
useIntegrationDeliveries(integrationId: string) // delivery history
```

### 8.5 Integrations settings page

`apps/web/src/routes/integrations/IntegrationsPage.tsx`:

- List all configured integrations for the current organization.
- Show name, type badge, active/inactive status, last delivery status, last delivery timestamp.
- "Add integration" button opens a create form (inline or modal).

Create form fields:
- Integration type (dropdown: `Slack Webhook`, `Generic Webhook`).
- Name (text input).
- Webhook URL (password-type input — masked, not shown after save).
- Event types (checkbox group: one per known event type).
- Organization (hidden if single-org context; dropdown if multi-org).

After save:
- Show `credentials_configured: true` indicator.
- Show "URL configured (not displayed)" rather than the URL value.
- Do not show the webhook URL again. If the operator needs to change it, they must re-enter it.

Deactivate action:
- "Deactivate" button per row. Confirmation prompt before calling `POST /api/v1/integrations/{id}/deactivate/`.
- Deactivated integrations remain visible but are grayed out.

### 8.6 Integration detail page

`apps/web/src/routes/integrations/IntegrationDetailPage.tsx`:

- Show integration metadata (name, type, event types, status).
- Show delivery history table: event type, timestamp, status (success/fail), HTTP status, latency.
- Provide a "Retry config" or "Edit" link back to update form (or inline edit for name and event types).
- Do not show webhook URL on this page.

### 8.7 UI states

Required states for integrations list:
- Empty state (no integrations configured).
- Loading state.
- Load error.
- Mix of active and inactive integrations.

Required states for create form:
- Submitting.
- URL validation error (shown field-level).
- Generic API error.
- Success (form closes, new integration appears in list).

Required states for delivery history:
- Empty (no deliveries yet).
- Loading.
- Load error.
- Mix of successes and failures.

---

## 9. Security requirements: credentials, SSRF, redaction, multi-tenancy

### 9.1 Credential storage

- Webhook URLs and API keys are stored Fernet-encrypted in `IntegrationConnection.encrypted_credentials`.
- `INTEGRATION_FERNET_KEY` is read from the environment. If absent, Django startup fails with a clear error.
- The encryption key is never logged, never returned by any endpoint, never included in audit metadata.
- A helper `apps/api/apps/integrations/crypto.py` wraps Fernet operations and raises `DomainValidationError(code="integration_crypto_error")` on decryption failure (which indicates key mismatch or data corruption).
- `IntegrationDeliveryAttempt.payload_preview` must never contain the decrypted URL or credentials.

### 9.2 SSRF protection

`apps/api/apps/integrations/ssrf.py` implements `validate_outbound_url(url: str) -> None` which raises `DomainValidationError(code="integration_invalid_url")` for any of the following:

- Non-HTTPS scheme (`http://`, `ftp://`, `file://`, etc.).
- Hostname resolves to a private IPv4 range: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`.
- Hostname resolves to loopback: `127.0.0.0/8`, `::1`.
- Hostname resolves to link-local: `169.254.0.0/16`, `fe80::/10`.
- Hostname is `localhost` or any `.local` domain.
- Hostname resolves to AWS EC2 instance metadata endpoint: `169.254.169.254`.
- Hostname resolves to GCP metadata endpoint: `169.254.169.254` or `metadata.google.internal`.
- URL contains userinfo (e.g., `https://user:pass@host/`).
- Port is a well-known internal service port (22, 25, 53, 6379, 5432, etc.) unless explicitly allowlisted.

Validation must occur at two points:

1. **Creation time**: when `POST /api/v1/integrations/` is called, validate the URL before encrypting and saving.
2. **Dispatch time**: validate again before each outbound call. This prevents a bypass where a valid URL was submitted but the DNS entry was later changed to point to an internal host (DNS rebinding attack).

> **ARCHITECTURE DECISION (K-H11): Resolve DNS once and pin the IP for the httpx call. Do not resolve at validation time and then let httpx re-resolve.**
>
> The naive approach calls `socket.getaddrinfo()` to validate the IP, then passes the original URL string to `httpx`. httpx calls `socket.getaddrinfo()` again internally — the DNS entry may have changed between the two calls (DNS TOCTOU / DNS rebinding). This is a known SSRF bypass technique.

DNS-TOCTOU-safe dispatch pattern:
```python
import socket
import ipaddress
from urllib.parse import urlparse

def _resolve_and_validate(url: str) -> tuple[str, str]:
    """Resolve hostname once; validate resolved IP; return (resolved_ip, original_host).
    Raises DomainValidationError if IP is private or disallowed."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    results = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    if not results:
        raise DomainValidationError(code="integration_invalid_url", message="DNS resolution returned no results.")
    resolved_ip = results[0][4][0]
    _validate_ip_not_private(resolved_ip)  # raises DomainValidationError if private
    return resolved_ip, hostname

def _dispatch_to(url: str, payload: dict, timeout: float) -> requests.Response:
    resolved_ip, hostname = _resolve_and_validate(url)
    # Replace hostname with resolved IP; pass original hostname in Host header.
    # This prevents httpx from re-resolving DNS.
    parsed = urlparse(url)
    pinned_url = parsed._replace(netloc=f"{resolved_ip}:{parsed.port or 443}").geturl()
    with httpx.Client(verify=True) as client:
        return client.post(
            pinned_url,
            json=payload,
            headers={"Host": hostname},
            timeout=timeout,
        )
```
Note: this approach pins the resolved IP in the URL and adds the original hostname as the `Host` header. TLS verification still uses the certificate's `CN`/`SAN` fields, which must match the original hostname — `httpx` with `verify=True` handles this correctly when the `Host` header is set.

Test the SSRF validator against: `http://127.0.0.1`, `https://169.254.169.254/latest/meta-data/`, `https://192.168.1.1`, `https://[::1]`, `https://localhost`, `http://example.com` (valid scheme fails), `https://hooks.slack.com/services/...` (should pass).

### 9.3 Response redaction

Serializer rules that must be enforced by code review at the approval gate:

- `IntegrationConnectionSerializer` must not include `encrypted_credentials` in any output field.
- `IntegrationConnectionSerializer` must include `credentials_configured: bool` derived from `encrypted_credentials is not None`.
- `config` may be returned as-is only if it provably contains no secrets. If implementation stores the URL in `config`, add a `_redact_config()` helper to the serializer.
- `IntegrationDeliveryAttemptSerializer.payload_preview` must pass through as-is only if the service-layer `_build_payload()` already excludes secrets. Add a test that directly asserts no credential values appear in stored `payload_preview` rows.

### 9.4 Multi-tenancy

- `IntegrationService.notify(...)` queries connections filtered by `organization_id`. An execution in org A cannot trigger notifications to org B's connections.
- `IntegrationConnection` queryset in public views must filter by organization. Pre-auth (Phase 10.5), use `organization_id` from the request body or URL parameter. Post-auth (Phase 10.7), derive it from the authenticated user's membership.
- `IntegrationDeliveryAttempt.organization` is denormalized and must be set from the connection's organization at creation time. Never derive it from request data.
- Integration management endpoints must reject requests that try to assign an integration to an organization the requesting user does not belong to. Pre-auth: accept any organization (consistent with other endpoints). Post-auth: enforce membership.

### 9.5 Audit events for integration management

Emit these audit events synchronously using `AuditService.emit(...)`:

| Action | Event type | Actor type | Notes |
|---|---|---|---|
| Connection created | `integration.created` | `user` or `system` | Metadata: `integration_id`, `type`, `name`, `organization_id`. No credentials. |
| Connection updated | `integration.updated` | `user` | Metadata: changed fields (omit `encrypted_credentials`). |
| Connection deactivated | `integration.deactivated` | `user` | Metadata: `integration_id`, `name`. |

Do not emit audit events for individual delivery attempts. Delivery attempts have their own `IntegrationDeliveryAttempt` record, which is the appropriate place to query dispatch history.

---

## 10. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### Milestone 0: Preflight and approval gate

Purpose: confirm the Phase 10.4 baseline is complete and prevent implementation against stale assumptions.

Files touched: none.

Commands:

```bash
git status --short
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec runner pytest
cd apps/web && npm test -- --run
```

Verify:
- Phase 10.4 artifact tests pass.
- `apps/api/apps/approvals/`, `apps/api/apps/audit/`, `apps/api/apps/artifacts/` are fully implemented (not stubs).
- `AuditService.emit(...)` exists and accepts `event_type`, `actor_type`, `actor_id`, `actor_label`, `object_type`, `object_id`, `organization_id`, `metadata`.
- Human confirms Phase 10.4 is verified before implementation starts.

Rollback: none; no files changed.

**Human approval gate: required.**

---

### Milestone 1: App scaffold and settings

Purpose: register the integrations app and define settings without any model or endpoint behavior.

Likely files touched:

- `apps/api/apps/integrations/apps.py`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/dev.py`
- `apps/api/config/settings/test.py`
- `apps/api/config/settings/prod.py`
- `.env.example`

Small steps:

1. Create `apps.py` with `IntegrationsConfig(AppConfig)`.
2. Add `apps.integrations.apps.IntegrationsConfig` to `INSTALLED_APPS` in `base.py`.
3. Add `INTEGRATION_FERNET_KEY = env("INTEGRATION_FERNET_KEY", default="")` in `base.py`. In `prod.py`, remove the default and require it explicitly.
4. Add `INTEGRATION_DISPATCH_TIMEOUT_SECONDS = env.float("INTEGRATION_DISPATCH_TIMEOUT_SECONDS", default=3.0)` in `base.py`.
5. Add `INTEGRATION_MAX_CONNECTIONS_PER_ORG = env.int("INTEGRATION_MAX_CONNECTIONS_PER_ORG", default=20)` as a guard against unlimited connection creation.
6. Add `INTEGRATION_FERNET_KEY=` and `INTEGRATION_DISPATCH_TIMEOUT_SECONDS=3.0` to `.env.example`.
7. In `test.py`, set `INTEGRATION_FERNET_KEY` to a valid generated key so tests can run without an external secret.

Commands:

```bash
docker compose exec api python manage.py check
```

Verify: Django starts with the new app registered. No model migration yet.

Rollback: remove app registration and settings additions.

Human approval gate: not required if Milestone 0 gate was passed.

---

### Milestone 2: Crypto utility and SSRF validator

Purpose: implement the two security utilities before any model or endpoint depends on them.

Likely files touched:

- `apps/api/apps/integrations/crypto.py`
- `apps/api/apps/integrations/ssrf.py`
- `apps/api/apps/integrations/tests/test_crypto.py`
- `apps/api/apps/integrations/tests/test_ssrf.py`

Small steps:

1. Implement `crypto.py`:
   - `encrypt_credentials(plaintext_dict: dict) -> bytes` — JSON-encodes then Fernet-encrypts.
   - `decrypt_credentials(ciphertext: bytes) -> dict` — Fernet-decrypts then JSON-decodes. Raises `DomainValidationError(code="integration_crypto_error")` on failure.
   - Read key from `settings.INTEGRATION_FERNET_KEY`. Raise `ImproperlyConfigured` if the key is empty.

2. Implement `ssrf.py`:
   - `validate_outbound_url(url: str) -> None` — raises `DomainValidationError(code="integration_invalid_url", detail=<reason>)` for blocked URLs.
   - Implement the full blocklist from section 9.2.
   - Resolve the hostname with `socket.getaddrinfo` and validate the resolved IPs.

3. Add tests:
   - `test_crypto.py`: encrypt then decrypt round-trip; decryption with wrong key raises; missing key at import time raises `ImproperlyConfigured`.
   - `test_ssrf.py`: localhost blocked; 127.x.x.x blocked; 169.254.x.x blocked; 10.x.x.x blocked; 192.168.x.x blocked; `http://` blocked; `https://hooks.slack.com/...` passes; userinfo in URL blocked.

Commands:

```bash
docker compose exec api pytest apps/integrations/tests/test_crypto.py apps/integrations/tests/test_ssrf.py
```

Verify: all crypto and SSRF tests pass.

Rollback: delete `crypto.py` and `ssrf.py`.

Human approval gate: not required unless SSRF blocklist differs from this blueprint.

---

### Milestone 3: Models and migration

Purpose: create `IntegrationConnection` and `IntegrationDeliveryAttempt` in the database.

Likely files touched:

- `apps/api/apps/integrations/models.py`
- `apps/api/apps/integrations/admin.py`
- `apps/api/apps/integrations/migrations/0001_initial.py`
- `apps/api/apps/integrations/tests/test_models.py`

Small steps:

1. Define `IntegrationConnection` with all fields from section 5.1. Inherit from `BaseModel`.
2. Define `IntegrationDeliveryAttempt` with all fields from section 5.2. Inherit from `BaseModel`.
3. Add indexes from section 5.4.
4. Register both in admin as read-only (`has_change_permission=False`, `has_delete_permission=False` for `IntegrationDeliveryAttempt`; `IntegrationConnection` admin may allow editing `is_active` and `name`).
5. Generate migration: `docker compose exec api python manage.py makemigrations integrations`.
6. Add model tests: UUID PK behavior, `is_active` defaults to `True`, `encrypted_credentials` can store a blob, string representations.

Commands:

```bash
docker compose exec api python manage.py makemigrations integrations
docker compose exec api python manage.py migrate
docker compose exec api pytest apps/integrations/tests/test_models.py
```

Verify: migration applies cleanly; model creates and retrieves without error.

Rollback: reverse migration while in development. Delete model file if milestone is abandoned before merge.

Human approval gate: required if FK `on_delete` behavior differs from this blueprint.

---

### Milestone 4: Integration service layer

Purpose: implement all service functions for connection management and notification dispatch.

Likely files touched:

- `apps/api/apps/integrations/services.py`
- `apps/api/apps/integrations/tests/test_services.py`

Small steps:

1. Implement `create_connection(...)`: validate URL, encrypt credentials, create record, emit `integration.created` audit event.
2. Implement `update_connection(...)`: re-validate and re-encrypt if credentials changed, save changed fields, emit `integration.updated` audit event.
3. Implement `deactivate_connection(...)`: set `is_active=False`, emit `integration.deactivated` audit event.
4. Implement `_build_payload(...)`: format Slack Block Kit payload for `slack_webhook`; format generic JSON payload for `generic_webhook`. Add a registry pattern (dict of type → formatter function) so future types can be added without modifying the dispatch loop.
5. Implement `_dispatch_webhook(...)`: `httpx.Client` POST with `timeout=settings.INTEGRATION_DISPATCH_TIMEOUT_SECONDS`; return `(http_status, latency_ms, error_detail)` tuple; catch `httpx.TimeoutException`, `httpx.NetworkError`, `httpx.HTTPError`.
6. Implement `notify(...)`: the full dispatch loop from section 7.2.
7. Add service tests:
   - `create_connection(...)` stores encrypted credentials and emits audit.
   - `notify(...)` with mocked `httpx.Client`: delivery attempt created on success; delivery attempt created on failure; execution state not changed on failure; `DomainConflictError` inside dispatch loop is caught.
   - `notify(...)` with SSRF-blocked URL is caught and recorded as failure (not propagated).
   - `notify(...)` with `event_types` filter: connection filtered to specific events receives only matching events.
   - Credentials never appear in `IntegrationDeliveryAttempt.payload_preview`.

Commands:

```bash
docker compose exec api pytest apps/integrations/tests/test_services.py
```

Verify: all service tests pass including dispatch failure isolation.

Rollback: delete `services.py`. Models remain unused.

Human approval gate: required before wiring trigger points in other services (Milestone 5).

---

### Milestone 5: Trigger points in execution and approval services

Purpose: wire `IntegrationService.notify(...)` into the execution and approval service transition points.

Likely files touched:

- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/tests/test_services.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_services.py`

Small steps:

1. In `executions/services.py`, add `notify()` calls:
   - After `Execution.objects.create(...)` in `create_execution(...)`: event type `execution.started`.
   - After `execution.save(...)` in `complete_execution(...)` for `outcome == "succeeded"`: event type `execution.completed`.
   - After `execution.save(...)` in `complete_execution(...)` for `outcome == "failed"`: event type `execution.failed`, including the failed step context if derivable.
2. In `approvals/services.py`, add `notify()` calls:
   - After `ApprovalRequest` is saved in `create_approval_request(...)`: event type `approval.requested`.
   - After `ApprovalDecision` is saved in `decide_approval(...)`: event type `approval.decided`.
3. Add or update tests:
   - Execution service test: `complete_execution(outcome="failed")` calls `IntegrationService.notify` with `event_type="execution.failed"`.
   - Execution service test: notify failure does not propagate; execution is still marked failed.
   - Approval service test: `create_approval_request(...)` calls notify with `event_type="approval.requested"`.

**Critical:** Use `unittest.mock.patch` on `IntegrationService.notify` in service tests. Do not make real outbound calls in service tests.

Commands:

```bash
docker compose exec api pytest apps/executions/tests/test_services.py apps/approvals/tests/test_services.py
docker compose exec api pytest apps/integrations/
```

Verify: trigger points are covered; existing tests still pass.

Rollback: remove the `notify()` calls from both service files.

Human approval gate: required if notify call placement differs from section 7.4 ordering rule.

---

### Milestone 6: Public integration management API

Purpose: expose CRUD endpoints for integrations to the frontend.

Likely files touched:

- `apps/api/apps/integrations/serializers.py`
- `apps/api/apps/integrations/views.py`
- `apps/api/apps/integrations/urls.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/integrations/tests/test_api.py`

Small steps:

1. Add `IntegrationConnectionSerializer` with:
   - `credentials` as a write-only field (`write_only=True`).
   - `credentials_configured` as a read-only `SerializerMethodField`.
   - No `encrypted_credentials` output field.
2. Add `IntegrationDeliveryAttemptSerializer` using fields from section 6.7.
3. Add views:
   - `IntegrationConnectionViewSet` or individual `APIView` subclasses for list/create/retrieve/partial-update.
   - `DeactivateIntegrationView` for the explicit deactivate action.
   - `IntegrationDeliveryListView` for delivery history.
4. Register URLs: `integration-list-create`, `integration-detail`, `integration-deactivate`, `integration-delivery-list`.
5. Wire into `api_v1_urls.py`.
6. Add API tests:
   - `POST /api/v1/integrations/` with valid Slack webhook URL returns 201; `credentials_configured=true`.
   - `POST /api/v1/integrations/` with `http://localhost` URL returns 400 with `integration_invalid_url`.
   - `GET /api/v1/integrations/{id}/` response does not contain `encrypted_credentials` or the webhook URL.
   - `POST /api/v1/integrations/{id}/deactivate/` returns 200 with `is_active=false`.
   - `GET /api/v1/integrations/{id}/deliveries/` returns paginated delivery history.

Commands:

```bash
docker compose exec api pytest apps/integrations/tests/test_api.py
docker compose exec api python manage.py check
```

Verify: SSRF protection tested at API layer; credentials never appear in response body; delivery history readable.

Rollback: remove URL registration and view files. Service layer remains testable.

Human approval gate: required if public response shape differs from section 6.

---

### Milestone 7: Frontend integrations feature

Purpose: build the integrations settings page and delivery history view.

Likely files touched:

- `apps/web/src/features/integrations/types.ts`
- `apps/web/src/features/integrations/api/integrationsApi.ts`
- `apps/web/src/features/integrations/hooks/useIntegrations.ts`
- `apps/web/src/features/integrations/hooks/useCreateIntegration.ts`
- `apps/web/src/features/integrations/hooks/useDeactivateIntegration.ts`
- `apps/web/src/features/integrations/hooks/useIntegrationDeliveries.ts`
- `apps/web/src/routes/integrations/IntegrationsPage.tsx`
- `apps/web/src/routes/integrations/IntegrationsPage.test.tsx`
- `apps/web/src/routes/integrations/IntegrationDetailPage.tsx`
- `apps/web/src/routes/integrations/IntegrationDetailPage.test.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/app/router.tsx`

Small steps:

1. Add types from section 8.1.
2. Add query keys from section 8.2.
3. Add API functions from section 8.3.
4. Add hooks from section 8.4.
5. Build `IntegrationsPage` from section 8.5.
6. Build `IntegrationDetailPage` from section 8.6.
7. Register routes in `router.tsx`.
8. Add tests for list page, empty state, create form, deactivate action, delivery history display.

Commands:

```bash
cd apps/web && npm run lint
cd apps/web && npm test -- --run
cd apps/web && npm run build
```

Verify: lint passes; tests pass; build completes without type errors; URL field shown as masked.

Rollback: remove integration route files; backend remains functional.

Human approval gate: product/design review before merge if UI layout introduces significant new patterns.

---

### Milestone 8: Local end-to-end manual gate

Purpose: verify the full Phase 10.5 workflow in Docker.

Files touched: none unless fixing defects found during manual testing.

Commands:

```bash
docker compose up --build
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec runner pytest
cd apps/web && npm test -- --run
cd apps/web && npm run build
```

Manual verification steps:

1. Create an organization and a published workflow with at least two steps, one with `requiresApproval: true`.
2. Open the integrations settings page. Create a `generic_webhook` integration pointing to a real or mock HTTP listener (e.g., `https://webhook.site/...`).
3. Start an execution of the workflow. Verify that a `generic_webhook` POST is received by the listener with `event_type: execution.started`.
4. Let the execution reach the approval step. Verify the listener receives `event_type: approval.requested`.
5. Approve the step from the approval UI. Verify the listener receives `event_type: approval.decided` with `decision: approved`.
6. Allow the execution to complete. Verify the listener receives `event_type: execution.completed`.
7. Deactivate the integration from the UI. Start another execution. Verify no webhook call is made.
8. Reactivate the integration. Create an integration with `event_types: ["execution.failed"]`. Trigger a failing execution. Verify only `execution.failed` is dispatched, not `execution.started`.
9. Open the integration detail page. Verify delivery history shows each attempt with status, HTTP status, and latency.
10. Create an integration with `url: https://169.254.169.254/latest/meta-data/`. Verify the API returns 400 with `integration_invalid_url`.
11. In the database, confirm `encrypted_credentials` is not the plaintext URL.
12. Confirm no webhook URL appears in audit trail or delivery attempt `payload_preview`.

Rollback plan if defects are found:

- If dispatch causes execution failures: revert the `notify()` calls from Milestone 5 first (safest rollback).
- If API response leaks credentials: roll back serializer to remove the offending field; services and models unaffected.
- If SSRF validation has gaps: patch `ssrf.py` and re-run Milestone 2 tests before proceeding.

**Human approval gate: required before declaring Phase 10.5 complete.**

---

## 11. Testing strategy

### 11.1 Service tests

Cover:

- `create_connection(...)` encrypts credentials (assert stored value is not equal to plaintext URL).
- `create_connection(...)` rejects SSRF-blocked URL with `DomainValidationError`.
- `create_connection(...)` emits `integration.created` audit event.
- `update_connection(...)` re-encrypts credentials when `credentials` changes.
- `deactivate_connection(...)` sets `is_active=False` and emits `integration.deactivated` audit event.
- `notify(...)` with a mocked `httpx.Client`: creates `IntegrationDeliveryAttempt` with `success=True` on 200.
- `notify(...)` when external endpoint returns 500: creates `IntegrationDeliveryAttempt` with `success=False`; does not raise.
- `notify(...)` when external endpoint times out: creates `IntegrationDeliveryAttempt` with `success=False`, `error_detail="timeout"`.
- `notify(...)` with `event_types=["execution.failed"]`: connection receives `execution.failed`; connection does not receive `execution.completed`.
- `notify(...)` with no active connections: completes without creating any `IntegrationDeliveryAttempt` records.
- `notify(...)` with multiple active connections: each connection gets its own `IntegrationDeliveryAttempt`; one connection's failure does not prevent others from being dispatched.
- `IntegrationDeliveryAttempt.payload_preview` does not contain the webhook URL.

### 11.2 API tests

Cover:

- `POST /api/v1/integrations/` with valid URL: 201, `credentials_configured=true`.
- `POST /api/v1/integrations/` with SSRF URL: 400, `integration_invalid_url`.
- `POST /api/v1/integrations/` with `http://` URL: 400, `integration_invalid_url`.
- `GET /api/v1/integrations/{id}/`: response body does not contain `encrypted_credentials`.
- `GET /api/v1/integrations/{id}/`: response body does not contain the plaintext webhook URL.
- `PATCH /api/v1/integrations/{id}/` with new credentials: re-encrypts; response does not expose new URL.
- `POST /api/v1/integrations/{id}/deactivate/`: 200, `is_active=false`.
- `POST /api/v1/integrations/{id}/deactivate/` when already inactive: 200, idempotent.
- `GET /api/v1/integrations/{id}/deliveries/`: returns paginated list; `payload_preview` field does not contain URL.

### 11.3 Delivery failure tests

Cover:

- `notify()` continues to the next connection after one connection fails.
- Network error (mocked `httpx.NetworkError`) produces `success=False` and does not propagate.
- A second `notify()` call after a previous failure creates a new `IntegrationDeliveryAttempt` (no state bleed from prior attempt).

### 11.4 SSRF tests

Cover (in `test_ssrf.py`, not requiring live network calls):

- `https://127.0.0.1/path` → blocked.
- `https://localhost/path` → blocked.
- `https://169.254.169.254/latest/meta-data/` → blocked.
- `https://10.0.0.1` → blocked.
- `https://192.168.1.100` → blocked.
- `https://172.16.0.1` → blocked.
- `http://hooks.slack.com/services/...` → blocked (non-HTTPS).
- `https://hooks.slack.com/services/T.../B.../valid-token` → passes.
- `https://example.com/webhook` → passes.
- URL with userinfo (`https://user:pass@example.com`) → blocked.

For DNS rebinding: mock `socket.getaddrinfo` to return a private IP for a public hostname; assert dispatch is blocked.

### 11.5 Redaction tests

Cover:

- `IntegrationConnectionSerializer` output does not include `encrypted_credentials` field.
- `IntegrationConnectionSerializer` output does not include the plaintext credential value.
- `IntegrationDeliveryAttemptSerializer` output `payload_preview` does not include the webhook URL.
- Create an integration, trigger a `notify()`, query the delivery attempt; assert `payload_preview` does not contain the URL substring.

### 11.6 Multi-tenancy tests

Cover:

- `notify()` for org A's execution does not dispatch to org B's connections.
- `GET /api/v1/integrations/` does not return integrations belonging to a different organization (enforced by queryset filter).

### 11.7 Frontend tests

Cover:

- `IntegrationsPage` renders list of integrations.
- Empty state displayed when no integrations exist.
- Create form submits and new integration appears in list.
- Webhook URL input is masked; URL value does not appear in rendered DOM after submit.
- Deactivate button triggers confirmation; after confirmation, integration shows inactive.
- `IntegrationDetailPage` renders delivery history with correct fields.
- Delivery failure row is visually distinguished from success row.

### 11.8 Manual webhook gate

The manual gate in Milestone 8 is required before declaring Phase 10.5 complete. It proves:

- A real outbound POST reaches a real HTTP endpoint.
- The payload contains expected fields.
- The URL is not visible anywhere in the frontend.
- A deactivated integration does not dispatch.
- SSRF protection blocks metadata endpoint at creation time.
- Audit trail and delivery history are both populated correctly.

---

## 12. Failure modes and risks

### Dispatch adds latency to state transitions

Risk: If `notify()` is called synchronously after a state transition and the external endpoint is slow, the Django request that triggered the state change is held open for up to `INTEGRATION_DISPATCH_TIMEOUT_SECONDS` × (number of active connections).

Mitigation:
- 3-second timeout per call keeps worst-case latency bounded.
- An organization with 5 active connections adds up to 15 seconds of latency in the worst case (all 5 connections time out sequentially).
- If this becomes a user-visible problem, move dispatch to a background task (Celery worker). Do not build that infrastructure now; measure first.
- At current expected scale (small teams, 2–3 integrations), this is acceptable.

### Duplicate delivery

Risk: If Django retries a failed request (e.g., load balancer retry), `notify()` may be called twice for the same event, resulting in duplicate Slack messages.

Mitigation:
- Phase 10.5 has no retry infrastructure; Django does not retry failed views.
- Include `execution_id` and `event_type` in the webhook payload so the receiving system can deduplicate.
- Do not design idempotency infrastructure for webhooks in Phase 10.5.

### External outage

Risk: If Slack's webhook endpoint is down, all outbound calls time out, and Django state transitions for affected executions take up to `timeout × connections` seconds.

Mitigation:
- Keep timeout short (3 seconds default).
- Connection is marked `last_delivery_status=failed`. The UI shows the failure. No execution state is affected.
- Operators can inspect delivery history to confirm the external system is unreachable.

### Secret leakage via API response

Risk: A new serializer field or a misconfigured `fields = "__all__"` accidentally includes `encrypted_credentials` in an API response.

Mitigation:
- The redaction tests in section 11.5 explicitly assert that no API response contains the credential value.
- Code review at the approval gate should verify `IntegrationConnectionSerializer` explicitly names its output fields.
- Use `fields = [explicit, field, list]` rather than `fields = "__all__"` in every serializer.

### Secret leakage via logs

Risk: Django logs the request body of a `POST /api/v1/integrations/` call, which contains the plaintext `credentials` field.

Mitigation:
- Django does not log request bodies by default.
- If structured logging (Phase 10.9) is added before auth, ensure the log middleware explicitly excludes request bodies from integration endpoints.
- Do not print or `logger.debug(request.data)` anywhere in integration views.

### Cross-tenant notification

Risk: An execution in org A triggers `notify(organization_id=org_A_id)`, but a bug in the queryset filter delivers to org B's connections.

Mitigation:
- Service test explicitly asserts that org B's connections receive zero `IntegrationDeliveryAttempt` records when org A's execution completes.
- Multi-tenancy test in section 11.6 covers this case.

### Fernet key misconfiguration

Risk: `INTEGRATION_FERNET_KEY` is rotated without re-encrypting existing rows, causing all decryptions to fail and all dispatch calls to fail silently.

Mitigation:
- `decrypt_credentials()` raises `DomainValidationError(code="integration_crypto_error")` on failure.
- The dispatch loop catches this per-connection and records the failure in `IntegrationDeliveryAttempt`.
- Operators see `error_detail="credential_decryption_error"` in delivery history, which is a clear signal to rotate back or re-encrypt.
- Document the key rotation procedure in `infra/aws/README.md` or equivalent when Phase 10.10 infrastructure work begins.

### DNS rebinding attack

Risk: An attacker creates a DNS entry that initially resolves to a public IP (passing validation at creation time) and later re-resolves to `169.254.169.254` (AWS metadata) at dispatch time.

Mitigation:
- The dispatch-time SSRF check in `_dispatch_webhook()` re-resolves the hostname and validates the resolved IP before calling `httpx`.
- DNS TTL in the Docker/AWS environment typically prevents immediate rebinding, but the dispatch-time check is the defense-in-depth layer.

---

## 13. What NOT to do

- Do not allow the runner to call external systems. The runner's only dependency is the Django internal API. Any runner-triggered event that needs to reach Slack must flow: runner → Django internal API → Django service → integration service → external endpoint.
- Do not allow the frontend to POST to webhook URLs directly. The frontend submits credentials once to Django; Django stores them encrypted; Django makes all outbound calls.
- Do not let integration dispatch affect execution state. A Slack timeout must never set an execution to `failed`. Wrap every `notify()` call in try/except at the outermost level.
- Do not add retry infrastructure in Phase 10.5. No Celery workers, no task queues, no exponential backoff queues, no SQS, no Redis-backed retry. Log failures and move on.
- Do not implement PagerDuty Events API v2 or Jira integration unless explicitly scoped. Reserve their `type` enum values but leave their logic unimplemented.
- Do not build a general-purpose integration plugin system or allow operators to upload custom handler code.
- Do not store webhook URLs in `config` (the unencrypted JSON field). Store them in `encrypted_credentials`.
- Do not return `encrypted_credentials` in any API response under any circumstances.
- Do not emit delivery attempt records into the audit trail. Delivery attempts have their own model; mixing them with the audit trail creates noise.
- Do not add async dispatch (async Django views, Django Channels, asyncio). Use synchronous `httpx.Client` with a bounded timeout.
- Do not skip DNS rebinding mitigation. Validate the resolved IP at dispatch time, not just at creation time.
- Do not use `fields = "__all__"` on `IntegrationConnectionSerializer`.
- Do not add inbound webhooks (receiving events from external systems). Phase 10.5 is outbound notification only.

---

## 14. Definition of done

Phase 10.5 is done when:

- [ ] `IntegrationConnection` model exists with UUID PK, organization FK, type enum, name, config, `encrypted_credentials`, `event_types`, `is_active`, `last_delivery_at`, `last_delivery_status`.
- [ ] `IntegrationDeliveryAttempt` model exists with UUID PK, integration FK, organization FK, `event_type`, `payload_preview`, `http_status`, `success`, `error_detail`, `latency_ms`, `attempted_at`.
- [ ] Fernet encryption utility (`crypto.py`) encrypts and decrypts credentials; raises on key misconfiguration.
- [ ] SSRF validator (`ssrf.py`) blocks all private IP ranges, loopback, link-local, metadata endpoints, non-HTTPS URLs, and userinfo; re-validates resolved IP at dispatch time.
- [ ] `IntegrationService.notify(...)` dispatches to all active connections for the organization, records each attempt, and never propagates failures to callers.
- [ ] `notify()` is called at five trigger points: execution started, execution completed, execution failed, approval requested, approval decided.
- [ ] Delivery failure does not change execution state. Covered by tests.
- [ ] Public CRUD API under `/api/v1/integrations/`: create (with write-only credentials), retrieve, partial-update, deactivate, list deliveries.
- [ ] No API response returns `encrypted_credentials` or the plaintext webhook URL. Covered by redaction tests.
- [ ] Audit events emitted on integration created, updated, deactivated.
- [ ] Integration settings UI: list, create form, deactivate action. Webhook URL is masked after save.
- [ ] Integration detail UI: delivery history table with status, HTTP status, latency, timestamp.
- [ ] Service tests, API tests, delivery failure tests, SSRF tests, redaction tests, multi-tenancy tests, frontend tests all pass.
- [ ] Manual webhook gate (Milestone 8) verified by a human.
- [ ] No code implements deferred features: PagerDuty, Jira, retry queues, async dispatch, inbound webhooks, plugin system.

---

## Summary

**File created:** `docs/blueprints/phase-10-05-integrations-blueprint.md`

**Major sections included:**
1. Purpose and sequencing rationale — why integrations come fifth (after artifacts, after audit is active, once event payload is rich enough)
2. Current-state inspection checklist — what to re-read before writing code
3. Architecture invariants — runner never calls external systems; integrations never affect execution state
4. Implementation scope — 12 Django backend files, 5 runner files (no changes), 10+ frontend files
5. Data model — `IntegrationConnection` (encrypted creds, type enum, event filter) and `IntegrationDeliveryAttempt` (delivery record)
6. API contracts — CRUD under `/api/v1/integrations/`, explicit deactivate endpoint, delivery history endpoints
7. Service contracts — `notify()` fire-and-forget with 3-second timeout; five trigger points in execution and approval services; post-commit dispatch ordering rule
8. Frontend contracts — TypeScript types, masked URL display, delivery history table
9. Security requirements — Fernet encryption, SSRF blocklist with DNS rebinding mitigation, response redaction, multi-tenancy isolation
10. Ordered milestones — 8 milestones with files, commands, verification, rollback notes, and approval gates
11. Testing strategy — service, API, delivery failure, SSRF, redaction, multi-tenancy, frontend, manual webhook gate
12. Failure modes — dispatch latency, duplicate delivery, external outage, secret leakage, cross-tenant notification, DNS rebinding, key misconfiguration
13. What NOT to do — runner-to-Slack prohibited, frontend-to-webhook prohibited, retry infrastructure deferred, PagerDuty/Jira deferred, plugin system prohibited
14. Definition of done — 15 checklist items

**Key assumptions:**
- Phases 10.1–10.4 (approvals, policies, audit, artifacts) are complete and verified before Phase 10.5 implementation begins.
- `AuditService.emit(...)` from Phase 10.3 accepts `event_type`, `actor_type`, `actor_id`, `actor_label`, `object_type`, `object_id`, `organization_id`, and `metadata` arguments.
- `ApprovalService` from Phase 10.1 has `create_approval_request(...)` and `decide_approval(...)` functions suitable for adding `notify()` calls.
- `httpx` is already available in `apps/api/requirements/` (used by Django for AI service calls).
- `cryptography` is either already installed or can be added as a direct dependency alongside Fernet for artifact storage encryption from Phase 10.4.
- Django views remain synchronous; `httpx.Client` (not `AsyncClient`) is appropriate for dispatch.
- PagerDuty and Jira integration types are reserved in the enum but intentionally unimplemented until a real organization requests them.
