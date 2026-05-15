# Phase 11: Admin DB Statistics Blueprint

| Field | Value |
|---|---|
| Phase number | 11 |
| Phase name | Admin DB Statistics |
| Objective | Add secure, organization-scoped admin and product-value statistics derived from Django-owned control-plane data without creating a second source of truth or exposing sensitive customer content. |
| Status | Blueprint only - do not implement without re-reading current source first |
| Depends on | Phases 01-09 complete and verified; Phase 10.1 approvals complete; Phase 10.2 policies complete; Phase 10.3 audit trail complete; Phase 10.4 artifacts complete; Phase 10.7 authentication and authorization complete; Phase 10.9 production hardening complete |
| Authored | 2026-04-29 |

---

## 1. Purpose and sequencing rationale

Phase 11 adds a small, Django-owned statistics layer for product administration, demos, pilots, and product validation. It answers questions that are already latent in the platform data:

- How many executions has this organization run?
- How often do executions succeed, fail, wait for approval, or get cancelled?
- How much risky activity is flowing through controlled runbooks?
- Which policies are actually blocking risky behavior?
- How many approval gates are triggered and how long do they wait?
- How much evidence, audit history, and artifact coverage exists?
- How often are the public APIs used and how often do they error?
- Which sales-safe value metrics can be shown in a customer demo without exposing operational details?

This phase comes after Phase 10.9 because admin statistics should be built on hardened production primitives:

1. Authentication and authorization must exist before any cross-object admin dashboard is exposed.
2. Audit, artifacts, approvals, policies, and execution state must be complete before their counts are meaningful.
3. Request IDs, structured logging, and production middleware from Phase 10.9 define the safe boundary for API request metrics.
4. The platform must already have organization scoping on every domain API before aggregate endpoints can safely summarize tenant data.

This phase helps demos, pilots, sales, and product validation because it turns platform activity into credible, inspectable value proof:

- "15 high-risk steps controlled this week."
- "4 risky actions blocked by policy."
- "9 approval gates enforced before execution."
- "87 audit events and 12 artifacts captured as evidence."
- "Median execution runtime improved from 6m to 4m."

This phase is not:

- A billing metering system.
- A BI warehouse.
- A customer telemetry product.
- A data warehouse, ClickHouse, Kafka, Celery, or external analytics integration.
- An ML scoring, account-ranking, or customer-success CRM feature.
- A second source of truth for executions, approvals, policies, artifacts, audit, or request logs.

The correct v1 design is a derived aggregate layer in Django/Postgres, refreshed from canonical domain tables and safe request-metric records.

---

## 2. Scope

### 2.1 In scope

- New Django app: `apps/api/apps/admin_stats/`.
- Organization-scoped aggregate statistics for executions, risk, policies, approvals, audit, artifacts, and request metrics.
- Safe request-metric middleware that stores endpoint group, method, status code, duration, organization id when safely available, and timestamp.
- Daily rollup records for efficient dashboard reads.
- Current summary snapshots for low-latency admin/product-value cards.
- Public product API endpoints under `/api/v1/admin-stats/`.
- Django admin read-only inspection for rollups, snapshots, and request metrics.
- React admin dashboard route, expected as `/admin/stats`.
- Management command: `python manage.py refresh_admin_stats`.
- Tests for aggregate correctness, isolation, sanitization, permissions, and frontend dashboard behavior.

### 2.2 Out of scope

- No code implementation in this blueprint.
- No billing, pricing, quota, invoice, usage entitlement, or revenue metering.
- No warehouse, OLAP database, ClickHouse, Snowflake, BigQuery, Kafka, Celery, Redis, or analytics microservice.
- No external analytics vendor, telemetry SDK, Segment, Amplitude, Mixpanel, Datadog product analytics, or CRM push.
- No ML scoring, customer health scoring, target-account ranking, competitive displacement tracking, or founder wedge strategy tracking.
- No raw execution content, command text, log text, artifact bytes, request bodies, response bodies, secrets, webhook URLs, API keys, or customer-sensitive notes in metrics tables.
- No runner access to public admin-stats APIs.
- No AI-service access to metrics.

---

## 3. Architecture invariants and boundaries

| Invariant | Phase 11 consequence |
|---|---|
| Django is the control plane. | All metric collection, rollup refresh, selectors, permissions, and API responses live in Django. |
| Runner talks only to Django internal APIs. | Runner does not read or write metrics directly and cannot call `/api/v1/admin-stats/`. |
| Frontend talks only to Django public APIs. | React dashboard calls `/api/v1/admin-stats/...` only. No direct DB, runner, AI, or analytics service calls. |
| AI service is stateless and advisory. | AI does not emit, query, summarize, or store admin statistics. |
| All product APIs remain under `/api/v1/`. | Admin stats APIs live under `/api/v1/admin-stats/`. Prometheus `/metrics/` from Phase 10.9 remains separate operational telemetry. |
| UUID primary keys remain standard. | All new persisted models inherit the existing UUID `BaseModel`. |
| Business logic belongs in `services.py`. | Rollup refresh and aggregation logic live in `apps/api/apps/admin_stats/services.py`; selectors live in `selectors.py`; views validate and delegate. |
| No premature event infrastructure. | Refresh is synchronous Django work through service functions and a management command. No background worker is introduced. |
| Metrics must not become a second source of truth. | Rollups and snapshots are derived from canonical domain tables. On disagreement, domain tables win and rollups are refreshed. |

Additional boundaries:

1. Metrics are Django-owned derived aggregates.
2. Metrics are organization-scoped unless explicitly platform-admin global.
3. Rollups may duplicate numeric counts for performance, but they must never own lifecycle state.
4. Request metrics are not audit events. Audit remains the state-change accountability record.
5. Prometheus metrics from Phase 10.9 are operational telemetry; admin stats are product-facing derived summaries.
6. Raw execution content, commands, logs, artifacts, secrets, webhook URLs, API keys, request bodies, response bodies, raw query strings, and customer-sensitive text must never be stored in metrics tables or returned by stats APIs.

---

## 4. Metrics taxonomy

All metrics are scoped by `organization_id` unless noted. All time-bounded metrics accept a date range and default to the last 30 days.

### 4.1 Execution volume

| Metric key | Definition | Source of truth |
|---|---|---|
| `executions.total` | Count of executions created in range. | `executions.Execution.created_at` |
| `executions.started` | Count with `started_at` in range. | `Execution.started_at` |
| `executions.completed` | Count with terminal `finished_at` in range. | `Execution.finished_at` |
| `executions.by_workflow` | Top workflows by execution count; include workflow id and title only. | `Execution.workflow` |
| `executions.by_runbook` | Top runbooks by execution count; include runbook id and title only. | `Workflow.runbook` |

### 4.2 Execution status breakdown

| Metric key | Definition |
|---|---|
| `executions.status.queued` | Count where current or terminal status is queued in range. |
| `executions.status.claimed` | Count where status is claimed in range. |
| `executions.status.running` | Count where status is running in range. |
| `executions.status.waiting_for_approval` | Count with at least one step currently or historically waiting for approval in range. |
| `executions.status.succeeded` | Count where execution succeeded in range. |
| `executions.status.failed` | Count where execution failed in range. |
| `executions.status.cancelled` | Count where execution cancelled in range. |
| `executions.success_rate` | `succeeded / terminal_executions`, excluding queued/running. |
| `executions.failure_rate` | `failed / terminal_executions`, excluding queued/running. |

### 4.3 Runtime performance

Runtime uses `finished_at - started_at` for executions with both timestamps. Exclude queued, still-running, cancelled without start, and records with invalid timestamp ordering.

| Metric key | Definition |
|---|---|
| `runtime.avg_seconds` | Mean execution runtime in seconds. |
| `runtime.median_seconds` | Median execution runtime in seconds. |
| `runtime.p95_seconds` | 95th percentile execution runtime in seconds. |
| `runtime.min_seconds` | Minimum valid runtime in seconds. |
| `runtime.max_seconds` | Maximum valid runtime in seconds. |
| `runtime.sample_count` | Number of executions included in runtime calculations. |
| `runtime.by_status` | Runtime buckets grouped by terminal status where useful. |
| `runtime.by_workflow` | Top workflow runtime trends, limited and safe. |

Implementation note: median and p95 can be computed in Python during rollup refresh for v1. Do not add specialized percentile database extensions unless already present.

### 4.4 High-risk activity

High-risk means `risk_level in ("high", "critical")`. If current implementation only uses `low`, `medium`, `high`, preserve compatibility and treat `critical` as future-compatible.

| Metric key | Definition | Source |
|---|---|---|
| `risk.high_risk_runbooks` | Count of runbooks with at least one high-risk/critical workflow step. | Workflow definitions and/or execution step snapshots |
| `risk.high_risk_workflows` | Count of workflows with at least one high-risk/critical step. | `workflows.Workflow` |
| `risk.high_risk_executions` | Count of executions with at least one high-risk/critical step. | `ExecutionStep` |
| `risk.high_risk_steps` | Count of execution steps with high/critical risk. | `ExecutionStep.risk_level` |
| `risk.high_risk_steps_succeeded` | High/critical steps that succeeded. | `ExecutionStep.status` |
| `risk.high_risk_steps_failed` | High/critical steps that failed. | `ExecutionStep.status` |
| `risk.high_risk_steps_gated` | High/critical steps that required approval or hit policy `approval_required`. | Approvals + policy evaluations |
| `risk.high_risk_steps_blocked` | High/critical steps blocked by policy. | `PolicyEvaluation.effective_outcome="block"` |

### 4.5 Policy prevention

Policy prevention covers policy rules that prevented or gated risky behavior. It must be derived from `PolicyEvaluation`, not inferred from current `PolicyRule` state alone.

| Metric key | Definition |
|---|---|
| `policies.evaluations_total` | Count of policy evaluations in range. |
| `policies.rules_matched_total` | Count of evaluations where a rule matched. |
| `policies.blocks_total` | Count where `effective_outcome="block"`. |
| `policies.approval_required_total` | Count where `effective_outcome="approval_required"`. |
| `policies.auto_approved_total` | Count where `effective_outcome="auto_approve"`. |
| `policies.high_risk_blocks` | Blocks on high/critical steps. |
| `policies.high_risk_approval_gates` | Approval-required outcomes on high/critical steps. |
| `policies.top_blocking_rules` | Top policy rules by block count; include policy/rule IDs and names only. |
| `policies.top_gating_rules` | Top policy rules by approval-required count; include policy/rule IDs and names only. |

### 4.6 Approval gates

| Metric key | Definition |
|---|---|
| `approvals.requests_total` | Count of approval requests created in range. |
| `approvals.pending` | Count currently pending. |
| `approvals.approved` | Count approved in range. |
| `approvals.rejected` | Count rejected in range. |
| `approvals.timed_out` | Count timed out in range. |
| `approvals.approval_rate` | Approved / resolved approval requests. |
| `approvals.rejection_rate` | Rejected / resolved approval requests. |
| `approvals.avg_wait_seconds` | Mean `resolved_at - requested_at` for resolved requests. |
| `approvals.median_wait_seconds` | Median wait time for resolved requests. |
| `approvals.p95_wait_seconds` | 95th percentile wait time for resolved requests. |
| `approvals.high_risk_requests` | Approval requests for high/critical steps. |

### 4.7 Audit, evidence, and artifacts

| Metric key | Definition |
|---|---|
| `audit.events_total` | Count of audit events in range. |
| `audit.events_by_type` | Dotted event type counts, capped to known safe event names. |
| `artifacts.total` | Count of artifacts uploaded in range. |
| `artifacts.by_kind` | Artifact counts by safe kind: stdout, stderr, file, report, diagnostic. |
| `artifacts.executions_with_artifacts` | Count of executions with one or more artifacts. |
| `artifacts.evidence_coverage_rate` | Executions with artifacts / terminal executions. |
| `artifacts.total_size_bytes` | Sum of artifact sizes, no filenames or content. |

### 4.8 API request volume and errors

Request metrics use a safe request-metric record, not raw logs.

| Metric key | Definition |
|---|---|
| `api.requests_total` | Count of captured API requests. |
| `api.requests_by_endpoint_group` | Counts grouped by normalized endpoint group. |
| `api.requests_by_method` | Counts grouped by HTTP method. |
| `api.error_count` | Count of status code >= 400. |
| `api.error_rate` | Errors / requests. |
| `api.server_error_count` | Count of status code >= 500. |
| `api.avg_duration_ms` | Mean request duration. |
| `api.p95_duration_ms` | 95th percentile duration. |
| `api.auth_failures` | Count of 401/403 on public APIs, grouped only by endpoint group. |

### 4.9 Product-value and demo-safe metrics

These are safe to show in sales demos, pilot reports, and product-validation decks when scoped to a consenting organization and date range:

| Metric key | Definition |
|---|---|
| `value.risky_actions_controlled` | High/critical steps that were blocked, gated, or required workflow approval. |
| `value.policy_blocks` | Policy block count. |
| `value.approval_gates_triggered` | Approval requests created. |
| `value.executions_with_evidence` | Executions with artifacts. |
| `value.audit_events_recorded` | Audit events recorded. |
| `value.evidence_coverage_rate` | Executions with artifacts / terminal executions. |
| `value.avg_runtime_seconds` | Average valid execution runtime. |
| `value.median_runtime_seconds` | Median valid execution runtime. |
| `value.time_waiting_for_approval_seconds` | Sum of resolved approval wait time. |
| `value.controlled_execution_rate` | Executions with policy block, approval gate, or artifact evidence / total executions. |

Product-value metrics must not claim prevented incidents, saved dollars, headcount savings, compliance certification, customer ROI, or competitive displacement unless those claims are backed by separately approved customer evidence.

---

## 5. Data model proposal

All models live in `apps/api/apps/admin_stats/models.py` and inherit the existing `BaseModel`.

### 5.1 `AdminMetricEvent`

Default recommendation: do not use this model for v1 if the metric can be derived from domain tables. Define it only as a narrow escape hatch for future safe product-value events that do not naturally exist as domain rows.

| Attribute | Specification |
|---|---|
| Purpose | Optional append-only safe metric event for a small set of derived product-value facts that cannot be reconstructed from canonical domain tables. |
| Organization scoping | Required `organization` FK. Null is not allowed. Platform-wide events are out of scope for v1. |
| Fields | `id`, `organization`, `event_type`, `source_object_type`, `source_object_id`, `metric_date`, `numeric_value`, `dimensions`, `occurred_at`. |
| `event_type` | `CharField(128)`, restricted in service to safe names such as `value.risky_action_controlled`. |
| `source_object_type` | `CharField(64, blank=True)`, safe enum string only. |
| `source_object_id` | `UUIDField(null=True, blank=True)`. |
| `metric_date` | `DateField`, derived from `occurred_at` in UTC unless org-local reporting is later added. |
| `numeric_value` | `DecimalField(max_digits=20, decimal_places=4, default=1)`. |
| `dimensions` | `JSONField(default=dict)`, safe small dimensions only. |
| Indexes | `(organization, metric_date, event_type)`, `(organization, occurred_at)`, `(source_object_type, source_object_id)`. |
| Uniqueness | Optional service-level idempotency key if used; do not add broad DB uniqueness until an actual event use case exists. |
| Retention | Same as rollup source data by default; no purge in v1. |
| Sanitization | No raw names, commands, logs, request details, artifact filenames, webhook URLs, API keys, or free-form customer text in `dimensions`. |

Implementation guidance: prefer not to create `AdminMetricEvent` during Phase 11 unless an implementation gap proves it is necessary. Metrics should primarily derive from existing domain tables and `AdminRequestMetric`.

### 5.2 `AdminMetricDailyRollup`

| Attribute | Specification |
|---|---|
| Purpose | Stores one organization's daily aggregate metrics for fast dashboard reads and date-range summaries. |
| Organization scoping | Required `organization` FK. All queries filter by organization unless platform admin explicitly requests cross-org totals. |
| Fields | `id`, `organization`, `date`, `metric_version`, execution counts, runtime fields, risk counts, policy counts, approval counts, audit/artifact counts, request counts, product-value counts, `metrics_json`, `refreshed_at`. |

Required scalar fields:

| Field | Type | Notes |
|---|---|---|
| `organization` | FK -> `organizations.Organization`, `CASCADE` or `PROTECT` following existing org deletion semantics | Required tenant boundary. |
| `date` | `DateField` | UTC reporting date for v1. |
| `metric_version` | `PositiveIntegerField(default=1)` | Allows future recalculation semantics. |
| `executions_total` | `PositiveIntegerField(default=0)` | Created on this date. |
| `executions_succeeded` | `PositiveIntegerField(default=0)` | Terminal status count. |
| `executions_failed` | `PositiveIntegerField(default=0)` | Terminal status count. |
| `executions_cancelled` | `PositiveIntegerField(default=0)` | Terminal status count. |
| `runtime_avg_seconds` | `FloatField(null=True)` | Null when no samples. |
| `runtime_median_seconds` | `FloatField(null=True)` | Null when no samples. |
| `runtime_p95_seconds` | `FloatField(null=True)` | Null when no samples. |
| `runtime_sample_count` | `PositiveIntegerField(default=0)` | Runtime denominator. |
| `high_risk_steps` | `PositiveIntegerField(default=0)` | High/critical execution steps. |
| `high_risk_executions` | `PositiveIntegerField(default=0)` | Executions with high/critical steps. |
| `policy_blocks` | `PositiveIntegerField(default=0)` | Effective block outcomes. |
| `policy_approval_gates` | `PositiveIntegerField(default=0)` | Effective approval-required outcomes. |
| `approval_requests` | `PositiveIntegerField(default=0)` | Requests created. |
| `approval_avg_wait_seconds` | `FloatField(null=True)` | Null when no resolved requests. |
| `approval_median_wait_seconds` | `FloatField(null=True)` | Null when no resolved requests. |
| `approval_p95_wait_seconds` | `FloatField(null=True)` | Null when no resolved requests. |
| `audit_events` | `PositiveIntegerField(default=0)` | Audit event count. |
| `artifacts_total` | `PositiveIntegerField(default=0)` | Artifact count. |
| `executions_with_artifacts` | `PositiveIntegerField(default=0)` | Evidence coverage numerator. |
| `api_requests_total` | `PositiveIntegerField(default=0)` | Captured request count. |
| `api_errors_total` | `PositiveIntegerField(default=0)` | Status >= 400. |
| `api_p95_duration_ms` | `FloatField(null=True)` | Null when no samples. |
| `product_value_json` | `JSONField(default=dict)` | Safe product-value metrics only. |
| `metrics_json` | `JSONField(default=dict)` | Additional safe grouped counts, e.g. status breakdown and endpoint group counts. |
| `refreshed_at` | `DateTimeField` | Set by refresh service. |

Indexes and constraints:

| Kind | Definition |
|---|---|
| unique | `(organization, date, metric_version)` |
| index | `(organization, date)` |
| index | `(date, metric_version)` for platform-admin aggregate refresh checks |

Retention considerations:

- Keep daily rollups indefinitely in v1; they are small and non-sensitive if sanitization is enforced.
- If domain source data is later purged, rollups may remain as non-content aggregates only if legal/privacy policy allows it.
- If an organization is deleted, follow the platform's organization deletion policy. Prefer cascade with org deletion only when domain data is also deleted.

Sanitization rules:

- `metrics_json` and `product_value_json` may contain only numeric values, known enum keys, UUIDs for policy/workflow/runbook IDs where necessary, and safe display names already visible to authorized org admins.
- Do not include command text, logs, artifact filenames, request paths with IDs, query strings, free-form approval notes, policy reasons if they may contain sensitive text, or audit metadata blobs.

### 5.3 `AdminMetricSnapshot`

| Attribute | Specification |
|---|---|
| Purpose | Stores a current cached summary for an organization and date range to keep dashboard cards fast. |
| Organization scoping | Required `organization` FK for organization snapshots. Optional `organization=null` only for platform-admin global snapshot if explicitly implemented. |
| Fields | `id`, `organization`, `snapshot_type`, `period_start`, `period_end`, `metric_version`, `summary`, `generated_at`, `source_rollup_refreshed_through`. |
| `snapshot_type` | `CharField(32)`: `last_7_days`, `last_30_days`, `month_to_date`, `custom`, `all_time`. |
| `summary` | `JSONField(default=dict)`, safe response-shaped aggregate payload. |
| Indexes | `(organization, snapshot_type, period_end)`, `(organization, generated_at)`. |
| Uniqueness | `(organization, snapshot_type, period_start, period_end, metric_version)`. |
| Retention | Keep only latest snapshot per fixed range where possible; custom snapshots may be overwritten. |
| Sanitization | Same as daily rollups. Snapshot payload must be suitable to return directly from public APIs after permission checks. |

Snapshot is optional for initial implementation if daily rollups are fast enough. If implemented, snapshots are a cache. Refreshing or deleting snapshots must not affect canonical domain state.

### 5.4 `AdminRequestMetric`

| Attribute | Specification |
|---|---|
| Purpose | Safe per-request metric record used for admin API volume and error-rate reporting. |
| Organization scoping | Nullable `organization` FK. Set only when safely available from authenticated organization context or validated request scope. |
| Fields | `id`, `organization`, `endpoint_group`, `method`, `status_code`, `duration_ms`, `request_date`, `occurred_at`, `actor_type`, `is_internal`, `is_admin_stats_endpoint`. |
| `endpoint_group` | `CharField(64)`, normalized allowlisted group such as `runbooks`, `workflows`, `executions`, `approvals`, `policies`, `artifacts`, `integrations`, `audit`, `admin_stats`, `auth`, `organizations`, `health`, `unknown`. |
| `method` | `CharField(8)`, normalized uppercase method. |
| `status_code` | `PositiveSmallIntegerField`. |
| `duration_ms` | `PositiveIntegerField`. Cap or clamp absurd values to a documented max if needed. |
| `request_date` | `DateField`, UTC date. |
| `occurred_at` | `DateTimeField`. |
| `actor_type` | `CharField(32)`: `user`, `runner`, `anonymous`, `system`, `unknown`. Do not store actor IDs in v1 request metrics. |
| `is_internal` | `BooleanField(default=False)`, true for `/api/v1/internal/...`. |
| `is_admin_stats_endpoint` | `BooleanField(default=False)`, true for `/api/v1/admin-stats/...`. |

Indexes and constraints:

| Kind | Definition |
|---|---|
| index | `(organization, request_date, endpoint_group)` |
| index | `(organization, occurred_at)` |
| index | `(endpoint_group, status_code, request_date)` |
| index | `(is_internal, request_date)` |
| check/service | `endpoint_group` must be allowlisted |
| check/service | `method` must be one of `GET`, `POST`, `PATCH`, `PUT`, `DELETE`, `OPTIONS`, `HEAD`, `OTHER` |

Retention considerations:

- Keep per-request rows for 90 days by default once production load grows; daily rollups keep long-term counts.
- Do not add automated purge in Phase 11 unless already needed. Document the retention setting, e.g. `ADMIN_REQUEST_METRIC_RETENTION_DAYS=90`, for future cleanup.

Sanitization rules:

- Store no headers, cookies, Authorization values, request bodies, response bodies, raw paths with object UUIDs, raw query strings, IP addresses, user agents, referrers, or request IDs in this table.
- Store only normalized endpoint groups, method, status, duration, organization, actor type, internal flag, and timestamp.

---

## 6. Service and selector design

Create `apps/api/apps/admin_stats/`.

### 6.1 Files

| File | Purpose |
|---|---|
| `apps.py` | App config. |
| `models.py` | Metric event, daily rollup, snapshot, request metric models. |
| `services.py` | Refresh, aggregation, and request metric recording functions. |
| `selectors.py` | Read-only query functions used by APIs and admin UI. |
| `serializers.py` | DRF serializers for response shaping and refresh input validation. |
| `views.py` | API views under `/api/v1/admin-stats/`. |
| `urls.py` | Admin stats route inventory. |
| `middleware.py` | Safe request metrics middleware. |
| `admin.py` | Read-only Django admin registration. |
| `management/commands/refresh_admin_stats.py` | Rollup refresh command. |
| `tests/` | Model, service, API, middleware, command, and permission tests. |

### 6.2 Service functions

All write behavior goes through `services.py`.

```python
def refresh_daily_rollup(*, organization, date, metric_version=1, actor=None) -> AdminMetricDailyRollup:
    ...
```

Requirements:

- Idempotent for `(organization, date, metric_version)`.
- Recomputes from canonical tables and overwrites the derived rollup in one transaction.
- Does not increment existing counts.
- Does not read existing rollup values as source data.
- Can be safely re-run after bug fixes.

```python
def refresh_all_rollups(*, date=None, from_date=None, to_date=None, organization=None, metric_version=1) -> RefreshResult:
    ...
```

Requirements:

- Accept exactly one of `date` or `from_date/to_date`.
- If `organization` is omitted, refresh all organizations visible to the management context.
- Return counts: organizations processed, dates processed, rollups refreshed, failures.
- Continue or fail-fast based on a command option; default fail-fast for local correctness.

```python
def record_request_metric(*, request, response, duration_ms) -> None:
    ...
```

Requirements:

- Best-effort but non-blocking from a user perspective.
- Must swallow and log sanitized metric-write errors so request success is not coupled to metrics persistence.
- Must not run for static assets, admin assets, or metrics endpoints if configured to exclude them.
- Must normalize endpoint group and never store raw path/query.

### 6.3 Selector functions

Read-only functions live in `selectors.py` and never mutate rollups.

```python
def get_admin_stats_summary(*, organization, period_start, period_end) -> dict:
    ...
```

Returns top-level cards and trends for the dashboard.

```python
def get_execution_metrics(*, organization, period_start, period_end) -> dict:
    ...
```

Returns execution volume, status breakdown, runtime metrics, and trend series.

```python
def get_risk_metrics(*, organization, period_start, period_end) -> dict:
    ...
```

Returns high-risk runbook/workflow/execution/step counts and risk trend series.

```python
def get_policy_prevention_metrics(*, organization, period_start, period_end) -> dict:
    ...
```

Returns blocks, approval-required outcomes, top blocking rules, and top gating rules.

```python
def get_approval_metrics(*, organization, period_start, period_end) -> dict:
    ...
```

Returns approval request counts, resolution counts, approval wait-time metrics, and pending count.

```python
def get_request_metrics(*, organization, period_start, period_end) -> dict:
    ...
```

Returns request counts, grouped endpoint volume, error rates, and duration metrics.

```python
def get_product_value_metrics(*, organization, period_start, period_end) -> dict:
    ...
```

Returns sales-safe metrics only. No raw operational details.

Selector rules:

- Selectors may query daily rollups for speed.
- If a date range includes today and today's rollup is missing, selectors may compute today's partial metrics directly from domain tables or return a `freshness` warning. Prefer direct computation only when simple and bounded.
- Selectors must return `generated_at`, `period_start`, `period_end`, and `data_freshness`.

---

## 7. API design

All endpoints live under `/api/v1/admin-stats/`.

### 7.1 Common query parameters

| Param | Required | Notes |
|---|---|---|
| `from_date` | No | ISO date. Defaults to 30 days before today. |
| `to_date` | No | ISO date. Defaults to today. Inclusive. |
| `organization_id` | No for normal org users | Existing authenticated org context remains source of truth. If supplied, must match `X-Organization-Id` unless platform admin. |
| `include_trends` | No | Boolean, default true. |

### 7.2 Endpoint inventory

| Method | Path | Purpose | Permission |
|---|---|---|---|
| `GET` | `/api/v1/admin-stats/summary/` | Dashboard summary cards and headline trends. | Org admin or platform admin. |
| `GET` | `/api/v1/admin-stats/executions/` | Execution volume, status, runtime metrics. | Org admin or platform admin. |
| `GET` | `/api/v1/admin-stats/risk/` | High-risk activity metrics. | Org admin or platform admin. |
| `GET` | `/api/v1/admin-stats/policies/` | Policy block and approval-gate metrics. | Org admin or platform admin. |
| `GET` | `/api/v1/admin-stats/approvals/` | Approval counts and wait-time metrics. | Org admin or platform admin. |
| `GET` | `/api/v1/admin-stats/api-requests/` | Safe API volume, error, and duration metrics. | Org admin or platform admin. |
| `GET` | `/api/v1/admin-stats/product-value/` | Demo-safe value metrics. | Org admin or platform admin. |
| `POST` | `/api/v1/admin-stats/refresh/` | Refresh rollups for current organization/date range. | Org admin in local/dev; platform admin in production unless explicitly enabled. |

Refresh endpoint guidance:

- Include the endpoint for local dev and admin repair workflows only if the implementation needs it.
- In production, prefer management command or staff-only access.
- Never expose refresh to operators, viewers, runners, anonymous users, or AI service callers.

### 7.3 Example: summary response

```json
{
  "organization_id": "5a97048a-52c8-4d7a-bf2c-2264993b7ec0",
  "period": {
    "from_date": "2026-04-01",
    "to_date": "2026-04-29"
  },
  "generated_at": "2026-04-29T18:30:00Z",
  "data_freshness": {
    "rollups_refreshed_through": "2026-04-28",
    "includes_partial_today": true
  },
  "cards": {
    "executions_total": 184,
    "success_rate": 0.91,
    "high_risk_steps_controlled": 37,
    "policy_blocks": 6,
    "approval_gates_triggered": 22,
    "executions_with_evidence": 119,
    "audit_events_recorded": 942,
    "api_error_rate": 0.018
  },
  "runtime": {
    "avg_seconds": 312.4,
    "median_seconds": 241.0,
    "p95_seconds": 812.0,
    "sample_count": 171
  },
  "trends": [
    {
      "date": "2026-04-28",
      "executions_total": 12,
      "policy_blocks": 1,
      "approval_gates_triggered": 3,
      "high_risk_steps_controlled": 5
    }
  ]
}
```

### 7.4 Example: product-value response

```json
{
  "organization_id": "5a97048a-52c8-4d7a-bf2c-2264993b7ec0",
  "period": {
    "from_date": "2026-04-01",
    "to_date": "2026-04-29"
  },
  "metrics": {
    "risky_actions_controlled": 37,
    "policy_blocks": 6,
    "approval_gates_triggered": 22,
    "executions_with_evidence": 119,
    "audit_events_recorded": 942,
    "evidence_coverage_rate": 0.65,
    "average_runtime_seconds": 312.4,
    "median_runtime_seconds": 241.0
  },
  "safe_for_external_demo": true,
  "redaction_notice": "Metrics are aggregate counts only. No commands, logs, artifacts, request bodies, or customer-sensitive text are included."
}
```

### 7.5 Example: policies response

```json
{
  "organization_id": "5a97048a-52c8-4d7a-bf2c-2264993b7ec0",
  "period": {
    "from_date": "2026-04-01",
    "to_date": "2026-04-29"
  },
  "totals": {
    "evaluations": 420,
    "rules_matched": 156,
    "blocks": 6,
    "approval_required": 22,
    "auto_approved": 392,
    "high_risk_blocks": 5,
    "high_risk_approval_gates": 18
  },
  "top_blocking_rules": [
    {
      "policy_id": "f1fcdf76-4f38-44d1-91e9-68d9f72831a0",
      "policy_name": "Production safety policy",
      "rule_id": "c92eb2f5-a59b-4f11-aac2-368599a39f9d",
      "rule_name": "Block critical operations outside window",
      "block_count": 4
    }
  ]
}
```

No endpoint response may include raw workflow definitions, step commands, approval notes, audit metadata blobs, artifact names, webhook URLs, API keys, headers, cookies, or request bodies.

---

## 8. Django admin and React UI plan

### 8.1 Django admin

Register these models read-only:

- `AdminMetricDailyRollup`
- `AdminMetricSnapshot`
- `AdminRequestMetric`
- `AdminMetricEvent` if implemented

Admin behavior:

- `has_add_permission()` returns `False`.
- `has_change_permission()` allows viewing but fields are read-only.
- `has_delete_permission()` returns `False` except for platform-superuser maintenance if explicitly approved.
- List filters: organization, date/request_date, endpoint group, status code family, snapshot type.
- Search fields: organization name/slug and safe IDs only.
- Do not display `metrics_json` raw by default if it becomes large; provide collapsed read-only display.

### 8.2 React route

Add route:

- `/admin/stats`

Expected frontend files later:

- `apps/web/src/features/adminStats/types.ts`
- `apps/web/src/features/adminStats/api/adminStatsApi.ts`
- `apps/web/src/features/adminStats/hooks/useAdminStatsSummary.ts`
- `apps/web/src/features/adminStats/hooks/useExecutionMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useRiskMetrics.ts`
- `apps/web/src/features/adminStats/hooks/usePolicyMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useApprovalMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useRequestMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useProductValueMetrics.ts`
- `apps/web/src/routes/admin/AdminStatsPage.tsx`
- `apps/web/src/routes/admin/AdminStatsPage.test.tsx`

### 8.3 Dashboard layout

Dashboard cards:

- Total executions
- Success rate
- High-risk steps controlled
- Policy blocks
- Approval gates triggered
- Median runtime
- Executions with evidence
- Audit events recorded
- API error rate

Charts:

- Execution count by day.
- Execution status breakdown.
- Runtime trend with average/median/p95.
- High-risk activity trend.
- Policy blocks and approval-required outcomes by day.
- Approval wait-time trend.
- API requests and error rate by day.

Tables:

- Top blocking policy rules.
- Top approval-gating policy rules.
- Top workflows by execution volume.
- Safe endpoint group request counts.

Empty states:

- No executions in range: show zero cards and a short empty state.
- No policies: show "No policy prevention data yet."
- No approvals: show "No approval gates triggered in this period."
- No request metrics: show "Request metrics are not available for this period."

Permission denied states:

- Viewer/operator without explicit admin permission: show a 403 panel, not partial data.
- Runner token: never reaches React route; API returns 403/401.
- Unauthenticated: route protection redirects to login.

Export restrictions:

- V1 should not add CSV export.
- If JSON export is needed for pilots, export only the same sanitized API payloads and require org admin/platform admin.
- No raw row export of `AdminRequestMetric`, audit metadata, approval decisions, artifacts, or execution steps.

---

## 9. Request metrics middleware

Create `apps/api/apps/admin_stats/middleware.py`.

### 9.1 Captured fields

The middleware captures:

- Normalized `endpoint_group`.
- HTTP `method`.
- Integer `status_code`.
- Integer `duration_ms`.
- `organization_id` only when safely available.
- `actor_type` only as a broad class.
- `is_internal`.
- `is_admin_stats_endpoint`.
- `occurred_at`.

Safe organization resolution order:

1. Use authenticated request organization context already validated by Phase 10.7 auth middleware.
2. Use `X-Organization-Id` only after membership validation has succeeded.
3. For internal runner endpoints, use the organization associated with the resolved execution if the view attaches it safely; otherwise leave null.
4. Never parse raw request body to discover organization id in middleware.

### 9.2 Endpoint grouping

Normalize paths to allowlisted groups:

| Path prefix | Endpoint group |
|---|---|
| `/api/v1/auth/` | `auth` |
| `/api/v1/organizations/` | `organizations` |
| `/api/v1/runbooks/` | `runbooks` |
| `/api/v1/workflows/` | `workflows` |
| `/api/v1/executions/` | `executions` |
| `/api/v1/approvals/` | `approvals` |
| `/api/v1/policies/` | `policies` |
| `/api/v1/artifacts/` | `artifacts` |
| `/api/v1/audit/` | `audit` |
| `/api/v1/integrations/` | `integrations` |
| `/api/v1/admin-stats/` | `admin_stats` |
| `/api/v1/internal/` | `internal` |
| `/health` | `health` |
| Anything else | `unknown` |

Do not store raw path segments or object UUIDs.

### 9.3 Explicitly forbidden

The middleware must never store:

- Headers.
- Cookies.
- Authorization values.
- Refresh tokens or access tokens.
- Request bodies.
- Response bodies.
- Raw query strings.
- Raw URL paths with UUIDs or slugs.
- IP addresses.
- User agents.
- Referrers.
- Webhook URLs.
- API keys.
- Request IDs, unless a later security review explicitly approves them.

### 9.4 Failure behavior

- Request metric persistence is best-effort.
- Metric write failure must never turn a successful product request into a failed product request.
- Log only sanitized failure information: exception type, endpoint group, status code, and method.

---

## 10. Security and permission model

### 10.1 Organization admin access

Organization admins and owners can read admin stats for their active organization.

Allowed:

- `GET /api/v1/admin-stats/...` for their organization.
- Local/dev refresh endpoint if enabled.

Denied:

- Cross-organization stats.
- Platform-wide stats.
- Raw request metrics export.

### 10.2 Platform admin access

Platform admins can:

- Read organization-scoped stats for support/demo prep.
- Optionally read global aggregate snapshots if implemented.
- Run refresh across organizations via management command.

Platform admin responses must still be sanitized. Platform admin is not permission to expose raw commands, logs, artifacts, webhook URLs, request bodies, or customer-sensitive text.

### 10.3 Operators and viewers

Regular operators and viewers are denied by default.

Exception:

- A future explicit permission such as `can_view_admin_stats` may allow operator read access, but it is out of scope for v1 unless required.

### 10.4 Runner tokens

Runner token authentication is denied for all `/api/v1/admin-stats/` endpoints.

Rationale: runner credentials are machine credentials for internal execution APIs, not product analytics credentials.

### 10.5 Cross-organization isolation

Every selector filters by organization before aggregation.

Tests must prove:

- Org A cannot see Org B counts.
- Org A cannot infer Org B activity from global totals.
- `organization_id` query/body mismatches return an error under the auth rules from Phase 10.7.

### 10.6 No AI-service access

The AI service has no auth path to admin stats and no need to call these endpoints. Do not add AI client credentials for stats.

### 10.7 No public or unauthenticated access

All `/api/v1/admin-stats/` endpoints require authentication. No stats endpoint is public, anonymous, or CORS-exposed beyond the authenticated web app.

---

## 11. Sales-safe and wedge-safe rules

### 11.1 Safe to show externally with customer consent

These are sales-safe because they are aggregate counts or rates and do not reveal operational content:

- Policy blocks.
- High-risk steps controlled.
- Approval gates triggered.
- Executions with evidence.
- Audit events recorded.
- Artifact coverage rate.
- Average, median, and p95 runtime trends.
- Success/failure rates.
- API request counts and error rates by endpoint group.

### 11.2 Private to organization admins

These should remain inside the authenticated product unless explicitly approved for a demo:

- Top workflow/runbook names by execution count.
- Top policy and rule names by block/gate count.
- Endpoint group error rates for a specific organization.
- Artifact count and size trends.
- Approval wait-time trends.

### 11.3 Forbidden in metrics tables and APIs

Never store or return:

- Customer conversion scoring.
- Pricing strategy.
- Competitive displacement notes.
- Target account rankings.
- Founder wedge planning.
- Raw customer operational details.
- Raw commands.
- Workflow raw content.
- Execution logs.
- Artifact filenames or bytes.
- Approval notes.
- Audit metadata blobs.
- Request bodies or response bodies.
- Headers, cookies, tokens, webhook URLs, API keys.
- Any free-form customer-sensitive text.

### 11.4 Claims discipline

The UI may say:

- "Policy blocks"
- "Approval gates triggered"
- "High-risk steps controlled"
- "Executions with evidence"

The UI must not say:

- "Incidents prevented"
- "Dollars saved"
- "Compliance guaranteed"
- "Headcount saved"
- "Customer retained"

unless a later approved evidence workflow supports those claims.

---

## 12. Testing and verification plan

### 12.1 Backend service tests

- `test_refresh_daily_rollup_counts_executions_by_status`
- `test_refresh_daily_rollup_is_idempotent`
- `test_refresh_daily_rollup_overwrites_stale_counts`
- `test_runtime_average_median_p95_ignore_invalid_samples`
- `test_high_risk_metrics_count_runbooks_workflows_executions_and_steps`
- `test_policy_block_metrics_count_effective_block_outcomes`
- `test_policy_approval_gate_metrics_count_effective_approval_required_outcomes`
- `test_approval_wait_time_average_median_p95`
- `test_artifact_and_audit_counts_are_derived_from_canonical_tables`
- `test_product_value_metrics_are_sales_safe`

### 12.2 Request middleware tests

- `test_request_metric_records_endpoint_group_method_status_duration`
- `test_request_metric_does_not_store_headers_or_bodies`
- `test_request_metric_does_not_store_raw_query_string`
- `test_request_metric_normalizes_uuid_paths_to_endpoint_group`
- `test_request_metric_uses_validated_organization_context`
- `test_request_metric_write_failure_does_not_fail_request`
- `test_internal_runner_request_marked_internal_but_not_granted_stats_access`

### 12.3 API permission tests

- `test_org_admin_can_read_own_summary`
- `test_operator_denied_by_default`
- `test_viewer_denied_by_default`
- `test_runner_token_denied`
- `test_anonymous_denied`
- `test_cross_org_summary_denied`
- `test_platform_admin_can_read_org_summary`
- `test_refresh_endpoint_denied_to_non_platform_admin_in_production`

### 12.4 Aggregate correctness tests

Fixtures should include:

- Two organizations with overlapping dates.
- Succeeded, failed, cancelled, queued, running executions.
- High-risk and low-risk steps.
- Policy evaluations with block, approval_required, auto_approve, and workflow_default decisions.
- Approval requests approved, rejected, timed_out, pending.
- Audit events of multiple types.
- Artifacts of multiple kinds.
- Request metrics with 2xx, 4xx, and 5xx statuses.

Assertions:

- Counts match exact expected values.
- Org A excludes Org B.
- Empty ranges return zero/null values consistently.
- Re-running refresh produces identical rollup rows.

### 12.5 Management command tests

- `test_refresh_admin_stats_accepts_date`
- `test_refresh_admin_stats_accepts_from_date_to_date`
- `test_refresh_admin_stats_accepts_organization`
- `test_refresh_admin_stats_rejects_invalid_date_range`
- `test_refresh_admin_stats_outputs_counts`
- `test_refresh_admin_stats_is_idempotent`
- `test_refresh_admin_stats_reports_failure_without_partial_silence`

### 12.6 Frontend tests

- Dashboard smoke test renders cards from summary endpoint.
- Empty state renders with zero metrics.
- Permission denied state renders on 403.
- Date range selector calls API with `from_date` and `to_date`.
- Product-value panel does not render forbidden fields.
- Error state renders safe API error message.

### 12.7 Verification commands

Expected implementation verification:

```bash
make test-api
make test-web
make lint
```

If management command implementation touches migrations:

```bash
docker compose exec api python manage.py makemigrations --check --dry-run
docker compose exec api python manage.py check
```

---

## 13. Management command plan

Command:

```bash
python manage.py refresh_admin_stats
```

Arguments:

| Argument | Required | Description |
|---|---|---|
| `--date YYYY-MM-DD` | No | Refresh exactly one UTC date. Mutually exclusive with `--from-date/--to-date`. |
| `--from-date YYYY-MM-DD` | No | Inclusive start date. Must be paired with `--to-date`. |
| `--to-date YYYY-MM-DD` | No | Inclusive end date. Must be paired with `--from-date`. |
| `--organization UUID_OR_SLUG` | No | Refresh one organization. If omitted, refresh all organizations. |
| `--metric-version INT` | No | Defaults to `1`. |
| `--fail-fast` | No | Default true. Stop on first organization/date failure. |
| `--continue-on-error` | No | Process remaining org/date pairs and report failures. |

Default behavior:

- If no date arguments are supplied, refresh yesterday and today.
- In local dev, this makes seeded data visible immediately.
- In production, scheduled execution can pass explicit date ranges.

Idempotency:

- Re-running the command for the same organization/date/version must produce the same rollup values for unchanged source data.
- Existing rollup rows are updated from recomputed values, not incremented.

Expected output:

```text
Refreshing admin stats
  metric_version: 1
  organizations: 1
  dates: 2026-04-28..2026-04-29

  [OK] Acme Platform Engineering 2026-04-28 executions=12 policy_blocks=1 approvals=3
  [OK] Acme Platform Engineering 2026-04-29 executions=4 policy_blocks=0 approvals=1

Refresh complete: organizations=1 dates=2 rollups_refreshed=2 failures=0
```

Failure handling:

- Invalid date range returns non-zero exit code.
- Unknown organization returns non-zero exit code.
- Aggregation exception logs sanitized org/date context and returns non-zero exit code.
- With `--continue-on-error`, command exits non-zero if any date failed but still reports all processed failures.

---

## 14. File-by-file implementation plan

Do not implement in this blueprint. Future implementation likely touches:

### Backend new files

- `apps/api/apps/admin_stats/__init__.py`
- `apps/api/apps/admin_stats/apps.py`
- `apps/api/apps/admin_stats/models.py`
- `apps/api/apps/admin_stats/services.py`
- `apps/api/apps/admin_stats/selectors.py`
- `apps/api/apps/admin_stats/serializers.py`
- `apps/api/apps/admin_stats/views.py`
- `apps/api/apps/admin_stats/urls.py`
- `apps/api/apps/admin_stats/middleware.py`
- `apps/api/apps/admin_stats/admin.py`
- `apps/api/apps/admin_stats/management/__init__.py`
- `apps/api/apps/admin_stats/management/commands/__init__.py`
- `apps/api/apps/admin_stats/management/commands/refresh_admin_stats.py`
- `apps/api/apps/admin_stats/tests/test_models.py`
- `apps/api/apps/admin_stats/tests/test_services.py`
- `apps/api/apps/admin_stats/tests/test_selectors.py`
- `apps/api/apps/admin_stats/tests/test_api.py`
- `apps/api/apps/admin_stats/tests/test_middleware.py`
- `apps/api/apps/admin_stats/tests/test_management_command.py`
- `apps/api/apps/admin_stats/migrations/0001_initial.py`

### Backend existing files likely updated later

- `apps/api/config/settings/base.py` - register app and request metrics middleware.
- `apps/api/config/api_v1_urls.py` - include `/api/v1/admin-stats/`.
- `apps/api/apps/common/permissions.py` - add or reuse org-admin/platform-admin permission helpers.
- `apps/api/apps/organizations/models.py` - only if permission helpers need role constants.

### Frontend new files

- `apps/web/src/features/adminStats/types.ts`
- `apps/web/src/features/adminStats/api/adminStatsApi.ts`
- `apps/web/src/features/adminStats/hooks/useAdminStatsSummary.ts`
- `apps/web/src/features/adminStats/hooks/useExecutionMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useRiskMetrics.ts`
- `apps/web/src/features/adminStats/hooks/usePolicyMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useApprovalMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useRequestMetrics.ts`
- `apps/web/src/features/adminStats/hooks/useProductValueMetrics.ts`
- `apps/web/src/routes/admin/AdminStatsPage.tsx`
- `apps/web/src/routes/admin/AdminStatsPage.test.tsx`

### Frontend existing files likely updated later

- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`

### Documentation likely updated later

- `docs/runbooks/local-development.md` - mention `refresh_admin_stats` after implementation.
- `docs/architecture/data-model.md` - add admin stats models after implementation.
- `docs/api/rest-api-v1.md` - document admin-stats endpoints after implementation.

---

## 15. Implementation milestones

### Milestone 1: Backend app scaffold and models

- Create `admin_stats` app.
- Add models and migration.
- Register read-only admin.
- Add model tests for constraints, defaults, and sanitization assumptions.

### Milestone 2: Request metrics middleware

- Add endpoint group normalization.
- Add safe organization resolution.
- Add request metric persistence.
- Add middleware tests proving forbidden data is not stored.

### Milestone 3: Daily rollup services

- Implement `refresh_daily_rollup`.
- Implement exact aggregate calculations.
- Add service tests for correctness and idempotency.

### Milestone 4: Selectors and API endpoints

- Implement selectors for summary, executions, risk, policies, approvals, requests, product value.
- Add DRF views and serializers.
- Add permission tests and cross-org isolation tests.

### Milestone 5: Management command

- Implement `refresh_admin_stats`.
- Add command tests for arguments, idempotency, output, and failure handling.
- Add local dev notes only after command behavior is stable.

### Milestone 6: React dashboard

- Add adminStats feature APIs/hooks/types.
- Add `/admin/stats` route.
- Render cards, charts, tables, empty states, and permission denied states.
- Add frontend tests.

### Milestone 7: Final verification and audit

- Run full API and web tests.
- Verify no source metrics table contains forbidden content.
- Verify all endpoints are under `/api/v1/admin-stats/`.
- Verify no runner or AI code path was added.
- Review output payloads for sales-safe language.

---

## 16. Definition of done

Phase 11 is complete when all of the following are true:

- `apps/api/apps/admin_stats/` exists with models, services, selectors, APIs, middleware, admin, management command, migrations, and tests.
- `/api/v1/admin-stats/summary/`, `/executions/`, `/risk/`, `/policies/`, `/approvals/`, `/api-requests/`, and `/product-value/` return organization-scoped sanitized aggregates.
- Any refresh endpoint is appropriately restricted or disabled in production.
- `python manage.py refresh_admin_stats` supports `--date`, `--from-date`, `--to-date`, and `--organization`.
- Daily rollup refresh is idempotent and recomputes from canonical domain tables.
- Request metrics store only endpoint group, method, status code, duration, organization when safe, actor type, internal flag, and timestamp.
- No metrics table stores headers, cookies, Authorization values, request bodies, response bodies, raw query strings, raw commands, logs, artifact content, webhook URLs, API keys, or customer-sensitive text.
- Org admins can read only their organization stats.
- Platform admins can read authorized organization stats.
- Operators/viewers are denied unless an explicit permission is added.
- Runner tokens are denied.
- AI service has no metrics access.
- Cross-org isolation tests pass.
- Aggregate correctness tests pass for executions, statuses, risk, policy blocks, policy approval gates, approval wait times, audit counts, artifact counts, request counts, and product-value metrics.
- Frontend `/admin/stats` renders dashboard cards, charts, tables, empty states, and permission denied states.
- `make test-api`, `make test-web`, and `make lint` pass.
- The implementation does not add queues, warehouse infrastructure, external analytics vendors, billing metering, ML scoring, customer-success CRM features, or any new service boundary.
