# Pilot Phase C: Runner Pools and Target Connectivity Blueprint

| Field | Value |
|---|---|
| Blueprint ID | `pilot-phase-c-runner-pools-target-connectivity` |
| Objective | Add first-class runner identity, runner pools, target-aware scheduling, liveness, drain, and operational visibility for narrow pilot execution. |
| Status | Blueprint only |
| Authored | 2026-05-08 |
| Primary gap | No first-class runner pools or target-aware scheduling exists. The current runner supplies a free-form `runner_id`, authenticates with shared bearer tokens, and claims from a single organization-agnostic queued execution set. |
| Depends on | Existing execution runner API, Phase 11.1 change dossier, Phase 11.2 windows/freezes/target locks, Pilot Phase A execution substrate, and Pilot Phase B workflow schema v2. |

## Current State Summary

The current implementation has useful execution and change-control scaffolding, but no scheduling topology:

- `Execution` has `claimed_by_runner_id`, `claim_token`, `claimed_at`, and `last_heartbeat_at`.
- `claim_next_execution(runner_id=...)` atomically claims the oldest queued execution, plus a narrow stale approval-wait reclaim path.
- Runner authentication uses configured shared bearer tokens in `RunnerBearerTokenAuthentication`.
- The runner sends `X-Runner-ID` and a request body `runner_id`, but Django does not persist a runner record or validate that the token belongs to that runner ID.
- `Poller` executes one claimed execution at a time before polling again.
- Change-backed execution already has production targets, immutable target snapshots, dispatch tokens, binding proof, target locks, windows, freezes, breakglass facts, and verification callbacks.
- `ChangeTarget.environment` is currently constrained to `production`, which is acceptable for the pilot but must not be mistaken for a complete environment model.
- Dispatch preflight checks windows, freezes, target locks, approval, policy, actor authorization, and verification plan state, but does not check whether an eligible runner pool can reach the requested targets.

Phase C must preserve the existing boundaries:

- Django remains the control plane and scheduling authority.
- Runner talks only to Django internal APIs.
- React talks only to Django public APIs.
- Runner never evaluates policy, approval, freeze, lock, target eligibility, or tenant authorization locally.
- Database constraints and service transactions remain the final guard for multi-runner races.

## Pilot Scope

This blueprint optimizes for a narrow pilot:

- One organization or a small set of pilot organizations.
- Production-only `ChangeRecord` targets, using the existing `ChangeTarget` model.
- Runner pools inside known trusted networks.
- One execution at a time per runner process by default.
- Pool-level and target-level concurrency limits enforced by Django before claim.
- No external queue service, no broker, and no generalized distributed scheduler.
- Fail-closed behavior when no eligible healthy runner exists.

Future extensibility is required, but broad multi-cloud scheduling, dynamic autoscaling, and arbitrary customer network discovery are non-goals for this phase.

## 1. Runner Identity Model

Introduce a persisted runner identity in Django. The runner ID used in API calls must become a server-issued identity, not a free-form string trusted from the request body.

Proposed model: `Runner`

| Field | Purpose |
|---|---|
| `id` | Server-issued UUID used as the canonical runner identity. |
| `organization` | Tenant boundary. A pilot runner belongs to exactly one organization. |
| `pool` | FK to `RunnerPool`. Required for active runners. |
| `display_name` | Operator-readable name, for example `prod-vpc-runner-01`. |
| `status` | `registered`, `active`, `draining`, `offline`, `disabled`, `revoked`. |
| `runner_version` | Last reported runner package version. |
| `hostname` | Sanitized host/container name reported by runner. |
| `fingerprint_sha256` | Stable install fingerprint hash, not a secret. |
| `token_hash` | Hash of the per-runner bearer token. Clear token is shown once. |
| `registered_at` | Initial registration time. |
| `last_seen_at` | Last successful heartbeat or claim attempt. |
| `last_heartbeat_at` | Last runner-level heartbeat, separate from execution heartbeat. |
| `drain_requested_at` | Set when operators request graceful drain. |
| `disabled_at` | Set when the runner is administratively disabled. |
| `revoked_at` | Set when credentials are invalidated. |
| `metadata` | Sanitized operational facts only. No secrets or raw environment dumps. |

Identity rules:

- Internal endpoints must authenticate a per-runner token and resolve it to exactly one `Runner`.
- Request body `runner_id` and `X-Runner-ID` become compatibility echoes. If supplied, they must match the authenticated runner UUID or stable alias.
- Audit actors should use the canonical `Runner.id` plus `display_name`.
- Existing `Execution.claimed_by_runner_id` can remain a string during the pilot, but it should store the canonical runner UUID as text. A later migration can convert it to an FK after historical compatibility is planned.
- Runner credentials are independent from user JWTs, integration credentials, target credentials, and dispatch tokens.
- A disabled, revoked, or wrong-organization runner must receive `401` or `403`, never an empty queue response that hides the security failure.

## 2. Runner Registration Flow

Registration must be explicit and auditable.

Proposed model: `RunnerRegistrationToken`

| Field | Purpose |
|---|---|
| `organization` | Tenant boundary. |
| `pool` | Pool the token can register into. |
| `token_hash` | Hash of one-time or short-lived bootstrap token. |
| `label_policy` | Optional list of labels the token may assert during registration. |
| `capability_policy` | Optional list of capabilities the token may assert during registration. |
| `expires_at` | Bootstrap token expiry. |
| `max_registrations` | Usually `1` for pilot. |
| `used_count` | Number of successful registrations. |
| `created_by` | Admin/operator who created it. |
| `revoked_at` | Manual revocation time. |

Flow:

1. Admin creates a `RunnerPool`.
2. Admin creates a scoped registration token for that pool.
3. Runner starts with `API_BASE_URL` and `RUNNER_REGISTRATION_TOKEN`.
4. Runner calls `POST /api/v1/internal/runners/register/` with:
   - bootstrap token;
   - requested display name;
   - runner version;
   - install fingerprint;
   - host facts;
   - proposed labels and capabilities.
5. Django validates token scope, expiry, usage count, organization, pool state, and label/capability policy.
6. Django creates or reactivates a `Runner` and returns:
   - canonical `runner_id`;
   - per-runner bearer token;
   - pool key;
   - accepted labels;
   - accepted capabilities;
   - heartbeat and poll interval hints.
7. Runner persists only its canonical ID and per-runner token locally.
8. All later internal calls authenticate with the per-runner token.

Re-registration:

- Same fingerprint plus same pool can re-register idempotently if the prior runner is not revoked.
- A changed pool requires an admin-created token for the new pool.
- Re-registration must rotate the runner token and audit the prior credential as superseded.
- If a runner loses local credentials, an admin must issue a new registration token rather than exposing the old token.

## 3. Runner Pool Model

`RunnerPool` is the scheduling and operator boundary for runners that share reachability and trust assumptions.

Proposed model: `RunnerPool`

| Field | Purpose |
|---|---|
| `id` | UUID primary key. |
| `organization` | Tenant boundary. |
| `key` | Stable slug, unique per organization. |
| `name` | Operator-readable name. |
| `description` | Operational notes. |
| `environment` | Pilot value `production`; future values can include `staging`, `dev`, or custom environments. |
| `network_zone` | Stable name for reachability, for example `prod-vpc-us-east-1`. |
| `status` | `active`, `draining`, `disabled`. |
| `max_concurrent_executions` | Pool-wide cap. |
| `max_concurrent_per_target` | Default target cap for this pool. |
| `labels` | Admin-managed labels. |
| `capabilities` | Admin-managed allowed capabilities. |
| `metadata` | Sanitized non-secret operational metadata. |

Pool rules:

- A runner belongs to one pool in Phase C.
- A pool belongs to one organization.
- A disabled pool is never eligible.
- A draining pool does not accept new execution claims, but existing claims may finish.
- Pool labels and capabilities are admin-managed authoritative facts. Runner-reported facts are observations until accepted.
- For change-backed execution, eligibility must be derived from the change targets, operation profile, workflow/action requirements, and pool route mappings.
- For non-change executions, use a conservative default pool only if the organization has explicitly configured one.

## 4. Capability and Label System

Use labels for placement and capabilities for execution support.

Labels answer "where or what is this runner?"

Examples:

- `region=us-east-1`
- `network=prod-vpc`
- `environment=production`
- `os=linux`
- `customer=pilot-a`

Capabilities answer "what can this runner safely execute?"

Examples:

- `action.shell_command`
- `action.http_request`
- `tool.bash`
- `tool.curl`
- `target.database`
- `target.kubernetes`
- `egress.private-vpc`

Rules:

- Labels and capabilities are normalized lower-case strings.
- Key-value labels use `key=value`.
- Boolean tags use a single token.
- Unknown labels in runner registration are rejected or stored as untrusted observations, not used for scheduling.
- Workflow schema v2 action contracts declare required capabilities.
- Operation profiles may declare required pool labels and allowed pool keys.
- Target connectivity mappings may require labels such as `network=prod-vpc` and `region=us-east-1`.
- Scheduling requires all declared capabilities to be present on the pool and runner.

Avoid label sprawl in the pilot. Start with:

- `environment=production`
- `network=<stable-network-zone>`
- `region=<cloud-region-or-datacenter>`
- `os=linux`
- `action.shell_command`
- `action.http_request`

## 5. Environment and Network Mapping

Target-aware scheduling needs a control-plane mapping from targets to reachable pools. Runners must not self-select targets based on local network claims.

Proposed model: `TargetConnectivityRoute`

| Field | Purpose |
|---|---|
| `organization` | Tenant boundary. |
| `environment` | Pilot value `production`. |
| `target_type` | Matches `ChangeTarget.target_type`, or `*` for a controlled wildcard. |
| `normalized_identifier_pattern` | Exact identifier or constrained pattern. Prefer exact in pilot. |
| `pool` | Eligible `RunnerPool`. |
| `required_labels` | Labels a runner in the pool must have. |
| `required_capabilities` | Capabilities required for this target route. |
| `priority` | Tie-breaker when multiple routes match. |
| `is_active` | Operational enable/disable. |

Mapping rules:

- A change target must match at least one active route before dispatch can become claimable.
- All targets on a change must resolve to the same pool for Phase C. Cross-pool fanout is deferred.
- If targets match multiple pools, scheduling uses deterministic priority and emits route details in dispatch diagnostics.
- If targets do not match any route, dispatch preflight fails with `runner_pool_unavailable`.
- Network zone is a control-plane property of the pool/route, not a probe performed by the runner.
- Target metadata must remain sanitized. Do not store credentials, raw URLs with embedded credentials, request bodies, or secret names in route metadata.

Operation profiles should optionally include:

- `allowed_runner_pool_keys`
- `required_runner_labels`
- `required_runner_capabilities`
- `target_route_required=true` for production profiles

## 6. Scheduling and Eligibility Logic

Scheduling remains pull-based: runners poll Django, and Django returns at most one eligible execution.

Replace global oldest-queued selection with scoped eligibility:

1. Authenticate runner token and load `Runner` with `pool`.
2. Reject disabled/revoked runners.
3. If runner or pool is draining, return no work with drain metadata.
4. Refresh runner liveness.
5. Compute runner eligibility:
   - same organization as execution;
   - pool is active;
   - runner status is active;
   - runner labels/capabilities satisfy execution requirements;
   - pool has available concurrency;
   - runner has available concurrency;
   - target and operation-profile limits allow another claim.
6. Select the oldest queued execution eligible for that runner's pool.
7. Lock the execution row with `select_for_update(skip_locked=True)`.
8. Create or update a scheduling claim record in the same transaction.
9. Set existing execution ownership fields and return the claim payload.

Change-backed execution eligibility:

- The change must still be `dispatchable`.
- The binding dispatch token must not be expired.
- The change request integrity hash must still validate.
- Existing windows/freezes/target locks must already have passed dispatch preflight, but stale dispatchable changes should still be expired conservatively.
- The execution's change targets must map to the polling runner's pool.
- The runner must satisfy required action capabilities from the workflow snapshot.
- The operation profile must allow the selected pool.

Non-change execution eligibility:

- For pilot safety, require an organization-level default pool or explicit workflow/pool binding.
- Do not let arbitrary runners in other organizations claim non-change executions.
- Consider disabling non-change execution claims from production pools unless explicitly enabled.

Selection order:

- Order by execution `created_at` within the runner's eligible pool.
- Do not starve older ineligible work. Expose ineligible queue counts and reasons to operators.
- Limit candidate scan count, but track `scheduler_candidates_skipped_total` by reason.

## 7. Concurrency Limits

Use layered limits. Every limit is enforced in Django inside the claim transaction.

Pilot limits:

| Limit | Default | Reason |
|---|---:|---|
| Runner concurrent executions | `1` | Matches current runner behavior and simplifies recovery. |
| Pool concurrent executions | Explicit per pool, default `1` for production. | Prevents accidental broad production fanout. |
| Organization concurrent executions | Explicit per org, default small number. | Tenant-level safety. |
| Operation profile concurrent executions | Optional, default `1` for critical profiles. | Prevents risky operation bursts. |
| Target concurrent executions | Existing target lock default `1`. | Prevents concurrent writes to the same target. |

Proposed model: `ExecutionLease`

| Field | Purpose |
|---|---|
| `execution` | One-to-one or FK to `Execution`. |
| `organization` | Tenant boundary. |
| `runner` | FK to `Runner`. |
| `pool` | FK to `RunnerPool`. |
| `status` | `active`, `released`, `expired`. |
| `claimed_at` | Claim time. |
| `last_heartbeat_at` | Last execution heartbeat. |
| `released_at` | Completion/cancel/recovery time. |
| `release_reason` | `completed`, `failed`, `cancelled`, `heartbeat_timeout`, `claim_replaced`. |

`ExecutionLease` is optional for the first migration if existing execution fields are extended carefully, but it gives clearer concurrency accounting and avoids overloading `Execution`.

Concurrency counters should be derived from active DB rows, not cached in memory:

- active execution leases by runner;
- active execution leases by pool;
- active target locks by target;
- active executions by organization and operation profile.

## 8. Drain Mode Semantics

Drain is an operator-requested graceful stop for a runner or pool.

Runner drain:

- Status becomes `draining`.
- Runner remains authenticated.
- Runner-level heartbeats continue.
- Existing execution heartbeats and step updates are accepted.
- `claim-next` returns no new work with `runner_action="drain"`.
- Once no active leases remain, status may become `offline` after heartbeat timeout or `drained` if a separate status is added.

Pool drain:

- Pool status becomes `draining`.
- All runners in the pool stop receiving new work.
- Existing execution ownership remains valid.
- Operators can monitor active leases until zero.
- Pool can return to `active` or move to `disabled`.

Forced disable:

- Disabled runners or pools receive no new work.
- Existing active executions should not be killed by default in Phase C.
- Operators may separately cancel executions through existing control-plane cancellation once real cancellation semantics exist.
- If a disabled runner stops heartbeating, watchdog recovery handles the execution according to existing timeout behavior.

Drain audit events:

- `runner.drain_requested`
- `runner.drain_cleared`
- `runner.disabled`
- `runner.revoked`
- `runner_pool.drain_requested`
- `runner_pool.disabled`

## 9. Liveness and Heartbeat Model

Separate runner liveness from execution liveness.

Runner-level heartbeat:

- New endpoint: `POST /api/v1/internal/runners/heartbeat/`
- Authenticated by per-runner token.
- Updates `Runner.last_heartbeat_at`, `last_seen_at`, version, current labels observed, and optional local executor capacity.
- Does not require an active execution.
- Does not extend an execution claim lease.

Execution heartbeat:

- Existing endpoint: `POST /api/v1/internal/executions/{execution_id}/heartbeat/`
- Continues to validate execution ownership and claim token.
- Updates execution lease and existing `Execution.last_heartbeat_at`.
- Used by watchdog recovery for claimed/running executions.

Status derivation:

| Derived state | Rule |
|---|---|
| `online` | Last runner heartbeat within `RUNNER_ONLINE_SECONDS`. |
| `stale` | Last runner heartbeat older than online threshold but younger than offline threshold. |
| `offline` | Last runner heartbeat older than offline threshold. |
| `busy` | Runner has active execution lease count at its limit. |
| `draining` | Explicit status, regardless of heartbeat freshness. |

Pilot settings:

- `RUNNER_ONLINE_SECONDS=30`
- `RUNNER_OFFLINE_SECONDS=120`
- Existing `RUNNER_STALE_HEARTBEAT_SECONDS` continues to govern execution recovery unless replaced with lease-specific settings.

Heartbeat payload should include only safe facts:

- runner version;
- hostname;
- process start time;
- local current execution count;
- observed pool key;
- observed capabilities checksum.

No environment dumps, credentials, command history, raw network routes, or target secrets.

## 10. Dispatch Refusal and Backpressure Behavior

Dispatch should fail before creating stranded execution work when no eligible pool or runner exists.

Add runner-pool checks to dispatch preflight:

- target route exists;
- route maps all targets to one pool for Phase C;
- pool is active;
- pool has at least one non-disabled registered runner;
- at least one runner is recently online unless operator explicitly allows queued offline dispatch;
- required capabilities are available on at least one online runner;
- pool and organization concurrency are not already saturated for immediate dispatch, or dispatch result clearly reports backpressure.

Backpressure outcomes:

| Condition | Public dispatch/preflight result | Runner claim result |
|---|---|---|
| No matching route | `409 runner_pool_unavailable` | Not applicable. |
| Pool disabled | `409 runner_pool_disabled` | Runners in pool receive no work. |
| Pool draining | `409 runner_pool_draining` for new dispatch | Existing work can finish. |
| No online runner | `409 no_online_runner` by default | Empty queue for unrelated runners. |
| Capacity full | `409 runner_pool_capacity_exhausted` or `202 queued` only if explicit queueing is enabled | Busy runners receive no extra work. |
| Missing capability | `409 runner_capability_missing` | Ineligible runners never see the work. |

Pilot default: dispatch refuses when no eligible online runner exists. This is safer than allowing a production change to become dispatchable and wait silently.

If queued dispatch despite no online runner is later allowed, it must be an explicit operation-profile flag with:

- visible stale age;
- dispatch token TTL large enough for the intended wait;
- operator warning;
- metric and audit event;
- clear expiry behavior.

## 11. Failure Recovery Behavior

Recovery remains conservative and Django-owned.

Runner disappears before claim:

- No state change. Work remains queued or dispatch refused by preflight.

Runner disappears after claim, before change bind:

- Existing dispatch token expiry path cancels or expires unbound dispatchable work.
- Execution lease expires after heartbeat timeout.
- Change lifecycle must not move to `running` without successful bind.

Runner disappears after change bind, before first step:

- Execution heartbeat watchdog marks execution failed after timeout.
- Change completion hook closes or moves the change according to current Phase 11 rules.
- Active target locks are released by the execution-finished callback when available. If callback is missing, watchdog completion handling must release locks or call the same release service exactly once.

Runner disappears during a step:

- Watchdog marks execution failed after heartbeat timeout.
- Running step is marked failed with `watchdog_heartbeat_timeout`.
- Lease becomes `expired`.
- Target locks are released.
- Audit includes runner ID, pool ID, last heartbeat age, execution ID, and affected target keys.

API connectivity loss while step continues:

- Runner retries transient internal API failures as today.
- If heartbeat cannot reach Django beyond timeout, Django may fail the execution.
- Later stale runner updates must be rejected by claim token or lease status.
- The runner must stop local execution if it learns the claim is no longer active. Pilot Phase A cancellation support should be used when available.

Runner process restarts:

- Runner authenticates with existing per-runner token.
- It sends runner heartbeat.
- It does not automatically resume an in-progress local step in Phase C.
- If it had an active execution, Django recovery determines final state. Resumable steps are non-goals for this phase.

Pool disabled during active execution:

- Existing execution may finish unless the operator explicitly cancels it.
- No new claim from that pool.
- Audit records the disable event separately from execution outcome.

## 12. Multi-Runner Safety Assumptions

Safety assumptions:

- More than one runner may poll concurrently.
- More than one runner may be in the same pool.
- More than one pool may exist for one organization.
- A runner can crash, retry, or send duplicate requests.
- Network partitions can create stale runners that still have old claim tokens.

Required guards:

- All claim selection uses `select_for_update(skip_locked=True)`.
- Claim token remains required for execution heartbeat, step update, artifacts, completion, change bind, and verification callbacks.
- Per-runner token must match canonical runner identity.
- Change binding remains one-to-one with execution and idempotent only for the same runner/execution/payload.
- Target locks remain database-enforced with the existing active unique constraint.
- Execution lease creation must be atomic with execution ownership update.
- Concurrency checks must be performed in the same transaction that claims the execution.
- Stale runners cannot update after lease expiration or claim replacement.
- Same request retries should be idempotent where possible and conflict clearly where not.

Do not rely on:

- runner process memory;
- frontend state;
- advisory local locks;
- runner-provided labels not accepted by Django;
- clock agreement between runner and Django for authorization decisions.

## 13. Tenant Isolation Expectations

Tenant isolation is mandatory even for pilot.

Rules:

- `RunnerPool`, `Runner`, registration tokens, target routes, execution leases, and scheduling diagnostics are all organization-scoped.
- A runner token authenticates to one organization only.
- A runner can claim executions only from its organization.
- Public APIs require existing organization membership and role checks.
- Internal runner APIs do not accept `X-Organization-Id` as authority; organization comes from the authenticated runner record and the execution/change row.
- Route matching must include `organization_id`.
- Capability and label names are not shared global authorities. Same label text in another organization has no cross-tenant meaning.
- Metrics can aggregate globally only if labels do not expose target identifiers or customer-sensitive names.
- Audit details visible through public APIs must be filtered by organization membership.

Pilot stance:

- Do not support shared cross-tenant runner pools.
- Do not support a central hosted runner reaching multiple tenant production networks.
- Do not allow one bootstrap token to register runners for multiple organizations.

## 14. API Changes Required

Internal runner APIs:

- `POST /api/v1/internal/runners/register/`
  - Authenticates bootstrap registration token.
  - Returns canonical runner ID and per-runner token.
- `POST /api/v1/internal/runners/heartbeat/`
  - Authenticates per-runner token.
  - Updates runner liveness.
- `POST /api/v1/internal/executions/claim-next/`
  - Authenticates per-runner token.
  - No longer trusts body `runner_id`.
  - Accepts compatibility fields but validates them against authenticated runner.
  - Returns no work plus reason hints: `empty`, `draining`, `capacity_full`, `no_eligible_work`.

Existing internal execution endpoints:

- Continue accepting `runner_id` and `claim_token` during compatibility.
- Validate `runner_id` against authenticated runner identity.
- Prefer server-resolved runner ID in service calls.
- Include pool/lease diagnostics in error metadata where safe.

Public operator APIs:

- `GET /api/v1/runner-pools/`
- `POST /api/v1/runner-pools/`
- `GET /api/v1/runner-pools/{id}/`
- `PATCH /api/v1/runner-pools/{id}/`
- `POST /api/v1/runner-pools/{id}/drain/`
- `POST /api/v1/runner-pools/{id}/disable/`
- `POST /api/v1/runner-pools/{id}/registration-tokens/`
- `GET /api/v1/runners/`
- `GET /api/v1/runners/{id}/`
- `POST /api/v1/runners/{id}/drain/`
- `POST /api/v1/runners/{id}/disable/`
- `POST /api/v1/runners/{id}/revoke/`
- `GET /api/v1/target-connectivity-routes/`
- `POST /api/v1/target-connectivity-routes/`
- `PATCH /api/v1/target-connectivity-routes/{id}/`
- `POST /api/v1/changes/{id}/runner-eligibility/`
  - Explains route, pool, runner, capability, and capacity eligibility for an approved or dispatchable change.

Public API authorization:

- Listing and reading runner health: organization member.
- Creating/updating pools, routes, registration tokens, drain/disable/revoke: organization admin or owner.
- Running eligibility diagnostics: operator or admin.

## 15. Schema and Model Changes Required

Recommended new Django app:

- `apps/api/apps/runners/`

Recommended models:

- `RunnerPool`
- `Runner`
- `RunnerCredential` or token fields on `Runner`
- `RunnerRegistrationToken`
- `RunnerCapability`
- `RunnerLabel`
- `TargetConnectivityRoute`
- `ExecutionLease`
- `SchedulingDecision` or `RunnerEligibilitySnapshot`

Minimal model links:

- Add nullable `runner_pool` FK or string snapshot to `Execution` for the selected pool.
- Add nullable `runner` FK or string snapshot to `Execution` only if historical migration risk is acceptable. Otherwise keep `claimed_by_runner_id` and introduce `ExecutionLease.runner`.
- Add `required_runner_capabilities`, `required_runner_labels`, and `allowed_runner_pool_keys` to `OperationProfile`, or store these in profile JSON fields for pilot speed.
- Add runner-pool result fields to `DispatchEligibilityCheck`:
  - `runner_pool_ok`;
  - `runner_pool_key`;
  - `runner_pool_id`;
  - `runner_pool_reason`;
  - optional diagnostics inside existing `checks` and `conflicts` JSON.

Constraints and indexes:

- `RunnerPool`: unique `(organization, key)`.
- `Runner`: unique active fingerprint per organization where useful.
- `Runner`: index `(organization, pool, status, last_heartbeat_at)`.
- `RunnerRegistrationToken`: index `(organization, pool, expires_at)`.
- `TargetConnectivityRoute`: index `(organization, environment, target_type, is_active)`.
- `ExecutionLease`: unique active lease per execution.
- `ExecutionLease`: index `(organization, pool, status)`.
- `ExecutionLease`: index `(runner, status)`.

Migration compatibility:

- Keep existing runner API payloads working while the runner is upgraded.
- Support a temporary legacy runner mode only in non-production or explicitly configured dev environments.
- Do not rewrite historical execution rows.
- Store snapshots of runner/pool identity on execution or lease so audit remains stable after pool rename.

## 16. Frontend and Operator UX Expectations

Add an operator-facing runner area. It should be functional, not decorative.

Runner pools page:

- Pool list with status, environment, network zone, active runners, busy runners, queued eligible executions, and capacity.
- Pool detail with labels, capabilities, target routes, recent scheduling refusals, and active leases.
- Drain and disable actions with confirmation.
- Registration token creation with TTL and one-time token display.

Runner detail page:

- Runner status: online, stale, offline, draining, disabled, revoked.
- Last heartbeat age.
- Version and hostname.
- Pool membership.
- Accepted labels and capabilities.
- Current active execution, if any.
- Recent heartbeat, claim, refusal, and failure events.
- Credential rotation/revoke action.

Change dispatch UX:

- Preflight checklist includes runner-pool eligibility.
- Show selected pool and route summary before dispatch.
- Refuse dispatch with clear actionable reasons:
  - no matching target route;
  - no online runner;
  - pool draining;
  - missing action capability;
  - concurrency limit reached.
- Do not expose internal tokens, dispatch tokens, runner bearer tokens, raw host env, or sensitive target metadata.

Execution detail UX:

- Show claimed runner, pool, claim time, heartbeat age, and drain/offline warnings.
- Show scheduler refusal history when execution remains queued.
- Show whether recovery was watchdog-driven and which pool/runner was involved.

## 17. Metrics and Observability Expectations

Metrics:

- `runner_heartbeat_total{organization,pool,status}`
- `runner_online_count{organization,pool}`
- `runner_stale_count{organization,pool}`
- `runner_claim_attempt_total{organization,pool,result,reason}`
- `runner_claim_latency_ms{organization,pool}`
- `scheduler_candidates_skipped_total{organization,pool,reason}`
- `scheduler_dispatch_refusal_total{organization,reason}`
- `runner_pool_capacity_used{organization,pool}`
- `runner_pool_capacity_limit{organization,pool}`
- `execution_lease_active_count{organization,pool}`
- `execution_lease_expired_total{organization,pool,reason}`
- `target_route_miss_total{organization,target_type}`
- `runner_capability_missing_total{organization,capability}`

Logs:

- Runner logs include canonical runner ID, pool key, runner version, request ID, execution ID when present.
- Django scheduling logs include decision ID, organization ID, runner ID, pool ID, execution ID, and refusal reason.
- No clear runner tokens, registration tokens, dispatch tokens, claim tokens, secrets, raw command output, or sensitive target metadata.

Audit events:

- `runner.registered`
- `runner.heartbeat_stale`
- `runner.disabled`
- `runner.revoked`
- `runner_pool.created`
- `runner_pool.updated`
- `runner_pool.drain_requested`
- `target_connectivity_route.created`
- `target_connectivity_route.updated`
- `execution.scheduler_refused`
- `execution.lease_created`
- `execution.lease_released`
- `execution.lease_expired`

Dashboards:

- Pool health and capacity.
- Claim rate and refusal reasons.
- Offline/stale runner age.
- Queued executions by eligibility reason.
- Watchdog recoveries by pool and runner version.

Alerts:

- No online runner in an active production pool.
- Pool capacity saturated for more than a short threshold.
- Execution heartbeat stale.
- Spike in scheduling refusals.
- Runner version drift below supported minimum.
- Registration token used unexpectedly or too many times.

## 18. Test Strategy

API and service tests:

- Register runner with valid token.
- Reject expired, revoked, overused, wrong-pool, and wrong-organization registration tokens.
- Per-runner token authenticates the runner and rejects mismatched `runner_id`.
- Disabled/revoked runner cannot claim or heartbeat.
- Draining runner heartbeats and updates active execution but receives no new claims.
- Pool drain prevents new claims from all runners in the pool.
- Target route matching selects the expected pool.
- Route miss fails dispatch preflight.
- Missing capability fails dispatch preflight.
- No online runner fails dispatch preflight by default.
- Capacity full refuses dispatch or claim according to configured mode.
- Concurrent runners cannot claim the same execution.
- Concurrent pool claims respect pool limit.
- Concurrent target claims remain protected by target locks.
- Stale lease recovery fails the execution and releases target locks once.
- Stale runner update after lease expiry is rejected.

Runner tests:

- Registration persists returned runner ID and token.
- Claim uses authenticated identity and no longer depends on arbitrary `RUNNER_ID`.
- Runner-level heartbeat continues while idle.
- Drain response causes poller to sleep and not execute work.
- Existing execution heartbeat still sends claim token.
- Mismatched canonical runner ID is treated as fatal configuration error.

Integration tests:

- Change with target route dispatches to eligible pool.
- Change with two targets in same pool dispatches.
- Change with targets in different pools fails in Phase C.
- Pool disabled after dispatch prevents unclaimed execution from being claimed.
- Runner crash during execution triggers watchdog and target lock release.
- Dispatch diagnostics shown through public API do not leak tokens or secrets.

Frontend tests:

- Runner pool list and detail render health states.
- Drain/disable/revoke actions call public APIs only.
- Change preflight shows runner eligibility failures.
- Execution detail shows runner/pool heartbeat state.

Verification commands:

- `make test-api`
- `make test-runner`
- `make test-web`
- targeted concurrency tests for `apps/api/apps/executions` and `apps/api/apps/changes`

## 19. Rollout Plan

Phase 0: design validation

- Review this blueprint against Phase A and Phase B implementation status.
- Decide whether `ExecutionLease` ships in Phase C or whether execution fields are extended first.
- Decide pilot default for dispatch when no online runner exists. Recommended default: refuse.

Phase 1: schema foundation

- Add runner models, migrations, admin registration, and audit object types.
- Add registration token creation and hashing.
- Add pool and route public APIs.
- Add unit tests for model constraints and tenant boundaries.

Phase 2: runner identity and heartbeat

- Add internal registration and runner heartbeat endpoints.
- Update runner settings and client to register and persist credentials.
- Keep legacy shared-token mode behind a dev-only setting if needed.
- Add authentication tests for per-runner token resolution.

Phase 3: pool-aware claim

- Add scheduling service that resolves authenticated runner, pool, capabilities, and capacity.
- Update `claim-next` to call scheduler.
- Preserve claim token ownership and existing step/update/complete flows.
- Add concurrent claim tests.

Phase 4: dispatch preflight integration

- Add target connectivity route matching.
- Add runner-pool checks to `run_dispatch_preflight`.
- Add dispatch refusal errors and public diagnostics.
- Add change dispatch integration tests.

Phase 5: operator UX and observability

- Add runner pool, runner detail, route management, and dispatch diagnostics UI.
- Add metrics, logs, dashboard panels, and alerts.
- Run a pilot drill with one pool, one runner, and one production-like target.

Phase 6: hardening before broader pilot

- Disable legacy shared runner token mode outside local development.
- Rotate pilot runner credentials.
- Load test concurrent pollers.
- Run watchdog recovery drills.
- Document operational runbooks for runner drain, revoke, route miss, and offline pool.

## 20. Explicit Non-Goals

Phase C does not implement:

- A broker, queue service, Celery, Redis scheduler, or external workflow engine.
- Dynamic runner autoscaling.
- Cross-tenant shared runner pools.
- Cross-pool fanout for one execution.
- Multi-step distributed execution across different runners.
- Resuming an in-progress step after runner restart.
- Hostile multi-tenant code isolation. That belongs to deeper sandbox/container hardening.
- Production credential brokerage or secret injection. That is a separate blocker.
- Full service catalog or CMDB ownership model.
- Non-production environment expansion beyond schema fields needed for future compatibility.
- Automatic network reachability probing from the runner.
- Runner-local authorization decisions.
- Runner-side policy, freeze, window, target-lock, or approval evaluation.
- Arbitrary label creation by runners.
- A central hosted runner that reaches customer production networks.
- Historical backfill of runner identities for old executions.

## Completion Criteria

Phase C is complete when:

- Runners register as first-class identities with per-runner credentials.
- Pools and target connectivity routes are organization-scoped and visible to operators.
- Dispatch preflight fails closed when no eligible runner pool can reach the change targets.
- Claim-next only returns executions eligible for the authenticated runner's pool and capabilities.
- Concurrency limits are enforced transactionally.
- Drain mode prevents new claims without breaking active execution updates.
- Runner liveness and execution liveness are separately observable.
- Watchdog recovery releases leases and target locks exactly once.
- Public UI exposes pool health, runner health, route diagnostics, and dispatch refusal reasons without exposing secrets.
- API, runner, web, and concurrency tests cover registration, scheduling, backpressure, drain, liveness, and recovery paths.
