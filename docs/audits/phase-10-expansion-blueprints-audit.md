# Phase 10 Expansion Blueprints Architecture Audit

## 1. Executive Summary

This is a read-only senior staff-level architecture audit of the Phase 10 expansion blueprint set. Phase 10 is positioned correctly as a strategic expansion roadmap after Phases 01-09, and most documents preserve the core lightweight architecture: Django remains the control plane, the runner and frontend use Django APIs only, FastAPI AI remains advisory/stateless, APIs remain under `/api/v1/`, internal runner APIs remain under `/api/v1/internal/`, and premature Kafka/Celery/WebSocket infrastructure is mostly avoided.

The blueprint set is not ready for implementation as a chain. The largest issues are not source-code defects; they are blueprint contract conflicts that would cause incorrect implementation if followed literally. The most important blockers are:

- The roadmap and Phase 10.2 disagree on policy conflict resolution.
- The roadmap requires approval audit events before the audit system exists.
- Phase 10.2 policy-required approvals can require runner behavior that Phase 10.1 does not define.
- Phase 10.8 live streaming uses a process-local in-memory bus with a sync emit path that can no-op under Django ASGI execution.
- Phase 10.8 and Phase 10.10 conflict on API scaling: process-local streaming does not work correctly with the proposed multi-task ECS API service.

Finding counts:

| Severity | Count |
| --- | ---: |
| BLOCKER | 5 |
| HIGH | 8 |
| MEDIUM | 6 |
| LOW | 2 |
| Total | 21 |

Final verdict: Phase 10-xx implementation should not proceed until the BLOCKER findings are corrected in the blueprints. Most fixes are blueprint-only clarifications, sequencing adjustments, or verification gate additions. No large re-architecture is required except that Phase 10.8/10.10 must either justify an external event bus for multi-task production streaming or explicitly constrain deployment to a single API task with accepted availability tradeoffs.

## 2. Documents Reviewed

Primary Phase 10 documents reviewed:

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-blueprint.md`
- `docs/blueprints/phase-10-02-policies-blueprint.md`
- `docs/blueprints/phase-10-03-audit-trail-blueprint.md`
- `docs/blueprints/phase-10-04-artifacts-blueprint.md`
- `docs/blueprints/phase-10-05-integrations-blueprint.md`
- `docs/blueprints/phase-10-06-richer-ai-parsing-blueprint.md`
- `docs/blueprints/phase-10-07-authentication-authorization-blueprint.md`
- `docs/blueprints/phase-10-08-live-event-streaming-blueprint.md`
- `docs/blueprints/phase-10-09-production-hardening-blueprint.md`
- `docs/blueprints/phase-10-10-aws-deployment-workflows-blueprint.md`

Related architecture and lower-phase documents checked for drift:

- `docs/blueprints/phase-01-locked-decisions-summary.md`
- `docs/blueprints/phase-04-runner-loop-blueprint.md`
- `docs/blueprints/phase-07-ai-draft-and-promotion-blueprint.md`
- `docs/api/internal-runner-api.md`
- `docs/api/rest-api-v1.md`
- `docs/architecture/execution-flow.md`
- `docs/runner/execution-loop.md`

## 3. Audit Methodology

The audit used repository-local document review only. No source files were changed, no migrations were run, no package files were touched, and no destructive commands were used.

Review steps:

1. Enumerated every `docs/blueprints/phase-10-*.md` document plus the Phase 10 roadmap.
2. Read each Phase 10 document for contracts, dependency gates, implementation notes, security constraints, testing scope, and rollback posture.
3. Cross-checked Phase 10 claims against the Phase 01 locked architecture and the Phase 04/07 runner and AI boundaries.
4. Searched for architecture-sensitive terms including internal APIs, versioning, UUIDs, audit, webhooks, SSRF, auth, tokens, queueing, Redis, Celery, Kafka, WebSockets, S3, ALB, ECS, health checks, and rollback.
5. Classified concrete issues by severity, affected phase, operational impact, and blueprint-only remediation.

The audit assumes Phase 10 remains a lightweight v1 expansion path. Recommendations avoid introducing event infrastructure, queues, or larger platform abstractions unless the blueprints already create a production requirement that cannot be met safely without them.

## 4. Severity Legend

| Severity | Meaning |
| --- | --- |
| BLOCKER | Must be fixed before Phase 10-xx implementation starts or before the implementation chain passes the affected gate. |
| HIGH | Should be fixed before implementing the affected expansion phase. |
| MEDIUM | Should be fixed during blueprint cleanup or before coding that area. |
| LOW | Useful polish or clarity improvement. |

## 5. Findings Table

| ID | Severity | Affected Phase(s) | Affected Document(s) | Issue |
| --- | --- | --- | --- | --- |
| B-01 | BLOCKER | 10.2, roadmap | Roadmap, 10.2 | Policy conflict-resolution contract conflicts: roadmap says stricter outcome wins, 10.2 requires first-match. |
| B-02 | BLOCKER | 10.1, 10.3, roadmap | Roadmap, 10.1, 10.3 | Roadmap release gate requires approval audit events before audit exists. |
| B-03 | BLOCKER | 10.1, 10.2 | 10.1, 10.2 | Policy-required approvals can require runner behavior not defined by the approval phase. |
| B-04 | BLOCKER | 10.8 | 10.8 | Live event bus sync emit path can silently no-op under Django ASGI/threadpool execution. |
| B-05 | BLOCKER | 10.8, 10.10 | 10.8, 10.10 | Process-local SSE bus conflicts with multi-task ECS API deployment. |
| H-01 | HIGH | 10.10 | 10.10, Phase 04 internal API docs | Internal runner endpoints are not required to be private at the AWS boundary. |
| H-02 | HIGH | 10.9, 10.10 | 10.9, 10.10 | ALB health check can fail the API service during AI dependency outages. |
| H-03 | HIGH | 10.3 | 10.3 | Audit immutability guarantee is overstated for an app-level append-only design. |
| H-04 | HIGH | 10.7 | 10.7 | Custom user migration risk is under-specified after prior Django migrations. |
| H-05 | HIGH | 10.6, 10.7 | 10.6, 10.7 | External AI parsing is introduced before auth without enough cost, tenant, or data-governance controls. |
| H-06 | HIGH | 10.5 | 10.5 | Synchronous integration dispatch can add request latency and failure coupling despite "fire-and-forget" wording. |
| H-07 | HIGH | 10.9 | 10.9 | CSP headers are specified without a package or middleware that would actually emit them. |
| H-08 | HIGH | 10.9, 10.10 | 10.9, 10.10 | Metrics endpoint can fail open if the metrics token is unset. |
| M-01 | MEDIUM | 10.4 | 10.4 | Artifact total quota is optional and lacks tenant-level abuse controls. |
| M-02 | MEDIUM | 10.6, 10.7 | 10.6, 10.7 | AI parse cache key is too broad for future tenant/model/schema isolation and has no bounded size. |
| M-03 | MEDIUM | 10.7 | 10.7 | Internal endpoint JWT versus runner-token error contract is ambiguous. |
| M-04 | MEDIUM | 10.5, 10.9 | 10.5, 10.9 | Integration HTTP client contract drifts between sync and async clients. |
| M-05 | MEDIUM | All 10.x | Roadmap, all 10.x | Verification evidence is repeatedly required but not standardized as a durable artifact. |
| M-06 | MEDIUM | 10.1 | 10.1 | Long approval waits can tie up runner capacity without a production sizing gate. |
| L-01 | LOW | All 10.x | Multiple Phase 10 docs | "File created" summary sections make living blueprints harder to audit later. |
| L-02 | LOW | Roadmap | Roadmap | Numbering/naming drift between 4.x expansion labels and 10.x phase filenames can confuse implementation prompts. |

## 6. Detailed Findings Grouped By Phase/Document

### Roadmap

#### B-01: Policy Conflict-Resolution Contract Conflicts

- Severity: BLOCKER
- Affected documents: `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-02-policies-blueprint.md`
- Affected phases: 10.2, roadmap
- Issue: The roadmap says the policy decision model should resolve conflicts by "stricter outcome wins." Phase 10.2 explicitly requires deterministic first-match behavior and says not to add stricter-outcome logic.
- Why it matters: The policy engine is a control-plane decision point. Implementing the roadmap literally produces different execution outcomes than implementing Phase 10.2 literally. That can change whether a step is blocked, allowed, warned, or requires approval.
- Recommended blueprint-only fix: Pick one policy conflict contract and update both documents plus the release gates. The lower-risk v1 fix is to keep Phase 10.2 first-match semantics, because the detailed policy blueprint already defines ordering, UI explanation, and deterministic tests around that contract. Update the roadmap language and gates to say "ordered first matching policy wins."
- Implementation risk if ignored: Engineers may implement two different policy semantics across backend services, UI previews, and tests. This would make policy decisions non-auditable and create production drift between displayed and enforced behavior.

#### B-02: Approval Audit Gate Requires Audit Before Audit Exists

- Severity: BLOCKER
- Affected documents: `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-01-approvals-blueprint.md`, `phase-10-03-audit-trail-blueprint.md`
- Affected phases: 10.1, 10.3, roadmap
- Issue: The roadmap release gate from approvals to policies requires an "approval audit event written in same transaction." Phase 10.1 explicitly avoids an audit-app dependency and persists approval decisions in approval tables only. Phase 10.3 introduces audit later.
- Why it matters: The roadmap gate is impossible to satisfy without either pulling audit into Phase 10.1 or violating the Phase 10.1 dependency boundary. It also creates a false readiness signal for Phase 10.2.
- Recommended blueprint-only fix: Change the 10.1-to-10.2 gate to require durable approval decision persistence and transaction-safe approval state transitions. Move audit-event requirements into Phase 10.3 as forward-only audit coverage for future decisions. If historical approval reconstruction is desired, document it as an explicit Phase 10.3 reporting/backfill limitation, not as a real audit event.
- Implementation risk if ignored: Phase 10.1 may grow an ad hoc audit mechanism before the audit model exists, or Phase 10.2 may be blocked by a gate no implementation can satisfy cleanly.

#### L-02: Phase Numbering And Naming Drift Can Confuse Implementation Prompts

- Severity: LOW
- Affected documents: `phase-10-platform-expansion-roadmap-blueprint.md`
- Affected phases: roadmap
- Issue: The roadmap uses expansion labels such as 4.1 through 4.10 while the actual documents are Phase 10.01 through 10.10.
- Why it matters: The distinction is understandable historically, but future implementation prompts can accidentally refer to "4.7 Auth" or "10.7 Auth" as if they were separate scopes.
- Recommended blueprint-only fix: Add a small canonical mapping table in the roadmap that maps each roadmap expansion label to its Phase 10 document filename.
- Implementation risk if ignored: Low operational risk, but higher coordination friction and possible work on the wrong blueprint scope.

### Phase 10.1 Approvals

#### B-03: Policy-Required Approvals Need A Runner Contract Change

- Severity: BLOCKER
- Affected documents: `phase-10-01-approvals-blueprint.md`, `phase-10-02-policies-blueprint.md`
- Affected phases: 10.1, 10.2
- Issue: Phase 10.1 describes the runner branching into an approval wait only when a protected step has `requires_approval=true`. Phase 10.2 allows policy evaluation to require approval even when the workflow step itself has `requiresApproval=false`, while also saying runner code is out of scope.
- Why it matters: Django can create a policy-driven approval request, but the runner will not necessarily enter the approval loop unless it calls a Django evaluation/start endpoint for every step and obeys the returned action/state. This is a control-plane contract, not a UI detail.
- Recommended blueprint-only fix: Make Phase 10.2 explicitly update the runner contract. The runner should attempt every step through Django, receive a normalized response such as `run`, `wait_for_approval`, `blocked`, or `skip`, and never infer policy behavior from local workflow JSON alone. Add contract tests for `requiresApproval=false` plus policy outcome `ApprovalRequired`.
- Implementation risk if ignored: Policy-driven approvals will appear configured but steps may still execute without approval. That is an audit-sensitive control failure.

#### M-06: Approval Waits Can Tie Up Runner Capacity

- Severity: MEDIUM
- Affected documents: `phase-10-01-approvals-blueprint.md`
- Affected phases: 10.1
- Issue: The approval design has the runner wait or poll while a claimed execution remains blocked on human approval.
- Why it matters: Long human waits can consume runner slots and reduce throughput. This is acceptable for a lightweight v1, but it needs to be visible before production sizing.
- Recommended blueprint-only fix: Add a capacity note and release gate requiring measurement of runner behavior during long approval waits. Define whether waiting executions hold worker concurrency, and document the expected runner fleet sizing or pause/resume behavior before production rollout.
- Implementation risk if ignored: A small number of pending approvals can starve unrelated executions or make runner capacity planning misleading.

### Phase 10.2 Policies

See B-01 and B-03. The policy blueprint is otherwise aligned with the core architecture by keeping policy evaluation in Django services and avoiding runner-local policy logic.

### Phase 10.3 Audit Trail

#### H-03: Audit Immutability Guarantee Is Overstated

- Severity: HIGH
- Affected documents: `phase-10-03-audit-trail-blueprint.md`
- Affected phases: 10.3
- Issue: The blueprint describes immutable audit rows using app-level append-only rules, read-only admin, and no update/delete APIs. It does not define database-level protections, tamper evidence, restricted DB roles, or operational controls for direct SQL modification.
- Why it matters: For a v1 system, app-level append-only is a reasonable lightweight choice. Calling it immutable without stating the trust boundary overstates the security property and can mislead later compliance or incident-response work.
- Recommended blueprint-only fix: Clarify the guarantee as "application-level append-only." Add a security note that DB superusers or migration roles can still modify rows. Add minimal controls: no app update/delete code paths, read-only admin, restricted production DB credentials, audit table backup/retention, and optional future hash-chain or external archive only if compliance requires it.
- Implementation risk if ignored: Teams may rely on audit logs as tamper-proof evidence when they are only protected by application behavior.

### Phase 10.4 Artifacts

#### M-01: Artifact Quota Is Optional And Lacks Tenant Abuse Controls

- Severity: MEDIUM
- Affected documents: `phase-10-04-artifacts-blueprint.md`
- Affected phases: 10.4
- Issue: The blueprint defines per-artifact and per-step limits, but the total per-execution limit is conditional ("if simple") and there is no per-organization, per-day, or per-runner upload abuse control.
- Why it matters: Artifact upload is a storage and availability boundary. Even if files flow through Django and not directly to S3, a runner or compromised token can create storage cost, disk pressure, and database growth.
- Recommended blueprint-only fix: Make total per-execution bytes mandatory. Add configurable per-organization and per-runner upload ceilings, even if implemented as simple settings before auth. Add tests for size, count, and total quota rejection.
- Implementation risk if ignored: Artifact upload abuse can cause storage cost spikes, request latency, or failed executions across tenants.

### Phase 10.5 Integrations

#### H-06: Synchronous Integration Dispatch Conflicts With Fire-And-Forget Semantics

- Severity: HIGH
- Affected documents: `phase-10-05-integrations-blueprint.md`
- Affected phases: 10.5
- Issue: The blueprint says integrations are fire-and-forget with logging, but dispatch is synchronous after commit using a short timeout and no queue. Multiple enabled integrations can still add seconds of latency to user or runner requests and can couple remote endpoint slowness to API responsiveness.
- Why it matters: Avoiding Celery is appropriate for v1, but synchronous outbound HTTP must have an explicit latency budget and failure-isolation model.
- Recommended blueprint-only fix: Add a bounded dispatch budget: maximum integrations per trigger, maximum total dispatch time per request, connect/read timeouts, and explicit behavior when the budget is exhausted. State whether dispatch happens in the request path after commit or in a post-response hook if the framework supports it. Add tests proving integration failures do not fail execution state transitions.
- Implementation risk if ignored: A slow webhook endpoint can degrade API latency, runner polling, or approval flows even though integrations are described as non-blocking.

#### M-04: Integration HTTP Client Contract Drifts Between Sync And Async

- Severity: MEDIUM
- Affected documents: `phase-10-05-integrations-blueprint.md`, `phase-10-09-production-hardening-blueprint.md`
- Affected phases: 10.5, 10.9
- Issue: Phase 10.5 specifies synchronous Django views and `httpx.Client`. Phase 10.9's timeout table refers to Django-to-integrations using `httpx.AsyncClient`.
- Why it matters: Timeout, testing, and request-lifecycle behavior differ between sync and async clients. The difference matters because Phase 10 intentionally avoids queue infrastructure.
- Recommended blueprint-only fix: Choose one client model in the blueprints. For the current sync Django design, use `httpx.Client` consistently unless the integration phase explicitly introduces async views and their operational implications.
- Implementation risk if ignored: Tests may cover a different client behavior than production uses, and timeout enforcement may be inconsistent.

### Phase 10.6 Richer AI Parsing

#### H-05: AI Parsing Before Auth Needs Stronger Cost And Data-Governance Controls

- Severity: HIGH
- Affected documents: `phase-10-06-richer-ai-parsing-blueprint.md`, `phase-10-07-authentication-authorization-blueprint.md`
- Affected phases: 10.6, 10.7
- Issue: Phase 10.6 introduces richer AI parsing before authentication and authorization. The blueprint correctly keeps FastAPI stateless and advisory, but it does not fully gate external provider usage by cost limits, deployment environment, tenant opt-in, or sensitive-content handling.
- Why it matters: Runbook content may include operational commands, hostnames, internal URLs, secrets accidentally pasted by users, or customer-sensitive procedure text. Before auth and tenant controls exist, the only boundary is environment discipline.
- Recommended blueprint-only fix: Add a pre-auth AI safety gate: explicit non-production/private-environment requirement until 10.7, an `AI_PARSE_ENABLED` kill switch, request/body size limits, rate limits, cost ceilings, logging redaction, and a warning that external provider and model details must be verified against current official docs at implementation time.
- Implementation risk if ignored: Sensitive content can be sent to an external AI provider too early, or a public unauthenticated parse endpoint can create unexpected cost exposure.

#### M-02: AI Parse Cache Key Is Too Broad And Unbounded

- Severity: MEDIUM
- Affected documents: `phase-10-06-richer-ai-parsing-blueprint.md`, `phase-10-07-authentication-authorization-blueprint.md`
- Affected phases: 10.6, 10.7
- Issue: The in-memory parse cache is keyed by raw content hash. It does not include title, prompt/schema version, model, enrichment settings, or future organization boundary. It also has no specified maximum size.
- Why it matters: A content-only key can return stale parse output after schema/model changes and can become problematic once tenant context is introduced. An unbounded in-memory cache can also grow under repeated parse attempts.
- Recommended blueprint-only fix: Define a bounded LRU cache key including content hash, title hash if used, parser schema version, prompt version, model identifier, enrichment mode, and organization id once auth exists. Add a maximum item count or memory budget.
- Implementation risk if ignored: Users may receive stale or cross-context parse output, and memory growth can destabilize the AI service.

### Phase 10.7 Authentication And Authorization

#### H-04: Custom User Migration Risk Is Under-Specified

- Severity: HIGH
- Affected documents: `phase-10-07-authentication-authorization-blueprint.md`
- Affected phases: 10.7
- Issue: The blueprint introduces a custom `User` model and `AUTH_USER_MODEL` after earlier phases have already used Django. It notes the database can be dropped and recreated if migration order fails, but it does not make the migration/reset boundary a formal gate.
- Why it matters: Changing `AUTH_USER_MODEL` late in a Django project is migration-sensitive, especially if admin/auth tables or foreign keys already exist. The risk is manageable before production data exists, but it must be explicit.
- Recommended blueprint-only fix: Add a Phase 10.7 preflight gate: confirm no production data preservation requirement, reset or rebuild local/staging DBs if needed, document migration order, and verify admin/auth migrations from a clean database. If data preservation becomes required, require a separate migration plan before implementation.
- Implementation risk if ignored: Auth implementation can leave migrations in a broken state or create inconsistent user references across environments.

#### M-03: Internal JWT Versus Runner Token Error Contract Is Ambiguous

- Severity: MEDIUM
- Affected documents: `phase-10-07-authentication-authorization-blueprint.md`
- Affected phases: 10.7
- Issue: The blueprint says user JWTs on internal endpoints should return 403, while missing runner token returns 401. A typical `RunnerTokenAuthentication` implementation may treat any non-runner bearer token as invalid authentication and return 401 unless the behavior is explicitly designed.
- Why it matters: The distinction is useful for tests and diagnostics, but it must be implementable without weakening internal endpoint security.
- Recommended blueprint-only fix: Define the internal endpoint auth order and error mapping exactly. For example: no bearer token returns 401; valid user JWT on internal namespace returns 403; invalid bearer token returns 401; valid runner token proceeds. Add tests for all cases.
- Implementation risk if ignored: Tests and implementation will diverge, and clients may receive inconsistent auth errors around sensitive internal APIs.

### Phase 10.8 Live Event Streaming

#### B-04: Sync Event Emission Can No-Op In Production

- Severity: BLOCKER
- Affected documents: `phase-10-08-live-event-streaming-blueprint.md`
- Affected phases: 10.8
- Issue: The proposed in-memory event bus emits from synchronous Django services using `asyncio.get_running_loop()`, with a documented no-op when there is no running loop. In Django ASGI, sync views and service code commonly execute in worker threads where no event loop is running.
- Why it matters: The blueprint can pass superficial API tests while silently dropping events in the actual sync service paths that update execution and step state.
- Recommended blueprint-only fix: Redesign the v1 event bus contract before implementation. Options include capturing the ASGI loop and using `asyncio.run_coroutine_threadsafe`, using a loop-safe queue bridge with explicit lifecycle initialization, or making the emitting service path async end-to-end where justified. Add an integration test that updates execution state through the same sync service used by runner APIs and proves an SSE subscriber receives the event.
- Implementation risk if ignored: Live event streaming will appear implemented but fail to deliver state updates in production.

#### B-05: Process-Local SSE Bus Conflicts With Multi-Task API Deployment

- Severity: BLOCKER
- Affected documents: `phase-10-08-live-event-streaming-blueprint.md`, `phase-10-10-aws-deployment-workflows-blueprint.md`
- Affected phases: 10.8, 10.10
- Issue: Phase 10.8 intentionally uses a process-local in-memory event bus and requires one Uvicorn worker. Phase 10.10 proposes production ECS API desired count of at least two tasks. A browser SSE connection and runner state update can land on different API tasks, so the subscriber will not receive the event.
- Why it matters: Sticky browser sessions do not solve cross-client event routing. The runner and frontend are separate clients, and process-local memory is not shared across ECS tasks.
- Recommended blueprint-only fix: Add an explicit Phase 10.10 gate for streaming deployment. Either introduce a justified external pub/sub dependency at the point multi-task API deployment is required, or state that live streaming is disabled/falls back to polling in multi-task production until a pub/sub backend exists. Running one API task is a possible temporary constraint but should be documented as an availability tradeoff, not the production target.
- Implementation risk if ignored: Production live streaming will be intermittent and topology-dependent, with users seeing stale executions despite successful state changes.

### Phase 10.9 Production Hardening

#### H-02: Health Check Couples API Availability To AI Dependency Availability

- Severity: HIGH
- Affected documents: `phase-10-09-production-hardening-blueprint.md`, `phase-10-10-aws-deployment-workflows-blueprint.md`
- Affected phases: 10.9, 10.10
- Issue: Phase 10.9 defines `/health/` as checking both database and AI health and returning 503 if either is unhealthy. Phase 10.10 uses `/health/` as the ALB target health check.
- Why it matters: If FastAPI AI or its upstream provider is degraded, the ALB can mark otherwise healthy Django API tasks unhealthy. That can take down control-plane functionality unrelated to parsing.
- Recommended blueprint-only fix: Split health endpoints. Use a lightweight liveness endpoint for process health, a readiness endpoint for database/migration readiness, and a dependency health endpoint that reports AI/integration status without driving ALB target removal. Update Phase 10.10 to use readiness for ALB.
- Implementation risk if ignored: A non-critical AI outage can cascade into full API unavailability.

#### H-07: CSP Settings Need Actual Middleware Or Package

- Severity: HIGH
- Affected documents: `phase-10-09-production-hardening-blueprint.md`
- Affected phases: 10.9
- Issue: The blueprint lists Content Security Policy settings but does not require `django-csp`, custom middleware, or another mechanism to emit CSP headers.
- Why it matters: Settings alone do not protect the frontend. Without middleware, tests may pass around configuration existence while responses have no CSP header.
- Recommended blueprint-only fix: Add an explicit dependency or custom middleware choice for security headers, and add response-header tests for CSP, HSTS, referrer policy, and related headers in production settings.
- Implementation risk if ignored: The system may be documented as hardened while missing a key browser security control.

#### H-08: Metrics Endpoint Can Fail Open

- Severity: HIGH
- Affected documents: `phase-10-09-production-hardening-blueprint.md`, `phase-10-10-aws-deployment-workflows-blueprint.md`
- Affected phases: 10.9, 10.10
- Issue: The metrics endpoint allows access when `PROMETHEUS_METRICS_TOKEN` is unset for development. The blueprints do not require production startup failure or network isolation when the token is missing.
- Why it matters: Metrics can expose route names, performance characteristics, error rates, and internal service details. In AWS, accidental public exposure is plausible unless explicitly gated.
- Recommended blueprint-only fix: Require `PROMETHEUS_METRICS_TOKEN` or private-network-only access in production. Add a startup check that fails production settings if metrics are enabled without a token or network restriction.
- Implementation risk if ignored: Operational metadata can become publicly accessible.

### Phase 10.10 AWS Deployment Workflows

#### H-01: Internal Runner Endpoints Must Be Private At The AWS Boundary

- Severity: HIGH
- Affected documents: `phase-10-10-aws-deployment-workflows-blueprint.md`, `docs/api/internal-runner-api.md`, `docs/blueprints/phase-04-runner-loop-blueprint.md`
- Affected phases: 10.10
- Issue: Phase 10.10 says internal runner endpoints should not be exposed publicly "if avoidable." That is too weak for `/api/v1/internal/` once the platform is deployed behind a public ALB.
- Why it matters: Runner endpoints operate execution claims, state transitions, logs, and artifacts. Authentication helps, but network reachability should also enforce the internal boundary.
- Recommended blueprint-only fix: Make private routing mandatory for production. Options include a private/internal ALB for runner-to-Django traffic, ECS service discovery inside the VPC, or ALB listener rules that deny `/api/v1/internal/` on the public listener while allowing only the runner security group through the private path. Keep runner token auth as defense in depth.
- Implementation risk if ignored: A token leak or auth bug exposes high-impact internal execution controls to the public internet.

### All Phase 10 Documents

#### M-05: Verification Evidence Is Required But Not Standardized

- Severity: MEDIUM
- Affected documents: `phase-10-platform-expansion-roadmap-blueprint.md`, all Phase 10 expansion blueprints
- Affected phases: All 10.x phases
- Issue: The roadmap and detailed blueprints repeatedly require human gates, readiness checks, verification commands, and rollback notes, but they do not define a standard durable evidence artifact for each phase.
- Why it matters: Phase 10 depends on prior phases being complete and verified. Without a consistent evidence record, later implementation prompts can claim readiness without preserving what was checked, which environment was used, or which rollback assumptions were accepted.
- Recommended blueprint-only fix: Add a standard per-phase verification record template under a documentation path such as `docs/audits/` or `docs/verification/`. Require each Phase 10 implementation to fill in commands run, results, manual checks, environment assumptions, rollback notes, and signoff that prerequisite phase gates were met.
- Implementation risk if ignored: Readiness becomes conversational rather than reproducible, and later phases may build on unverified assumptions.

#### L-01: "File Created" Summary Sections Make Living Blueprints Harder To Audit

- Severity: LOW
- Affected documents: Multiple Phase 10 expansion blueprints
- Affected phases: All 10.x phases
- Issue: Several blueprints include generated-document summary language such as "File created" even though the files now serve as living architecture blueprints.
- Why it matters: This does not affect runtime behavior, but it adds noise and can confuse later audits about whether the document is a creation transcript, a finalized plan, or the current source of truth.
- Recommended blueprint-only fix: During normal blueprint cleanup, replace generated-document completion notes with stable blueprint metadata or remove them entirely.
- Implementation risk if ignored: Low. The main risk is review friction and accidental reliance on stale summary language.

## 7. Cross-Document Drift Findings

The most significant cross-document drift is concentrated in four areas:

1. Approval, policy, and audit sequencing:
   - Roadmap requires approval audit events before Phase 10.3 audit exists.
   - Phase 10.2 can create approval requirements that Phase 10.1 runner behavior does not satisfy.
   - Policy conflict resolution differs between roadmap and Phase 10.2.

2. Live streaming versus production deployment:
   - Phase 10.8 is explicitly process-local.
   - Phase 10.10 deploys multiple API tasks for availability.
   - These cannot both be true for reliable production SSE without an external event transport or a documented polling fallback.

3. Hardening versus deployment health checks:
   - Phase 10.9 includes dependency checks in `/health/`.
   - Phase 10.10 uses `/health/` for ALB target health.
   - This can convert dependency degradation into full API target removal.

4. Integration implementation model:
   - Phase 10.5 uses synchronous HTTP dispatch.
   - Phase 10.9 references async HTTP for integration timeouts.
   - The blueprint set should use one request model until async behavior is intentionally introduced.

## 8. Security Review

Security posture is directionally good but uneven. The blueprints correctly call out many risks, including SSRF, token redaction, credential leakage, unsafe internal APIs, upload limits, and audit metadata restrictions. The remaining problems are concrete and fixable.

SSRF:

- Phase 10.5 has the strongest SSRF treatment: URL validation, private IP blocking, timeouts, no redirects, and failure isolation are described.
- Phase 10.6 should apply similar caution to AI enrichment if future URL fetching or document retrieval is added. Current AI parsing should remain text-only unless a later blueprint explicitly adds fetch controls.

Credential leakage:

- Integration credentials are intended to be encrypted and redacted.
- Audit metadata forbids secrets, runner claim tokens, and raw command output.
- Metrics exposure needs stronger production gating because operational metadata can still leak sensitive topology details.

Unsafe internal endpoints:

- The strongest unresolved issue is AWS exposure of `/api/v1/internal/`. Token auth is necessary but insufficient. Production routing must make those endpoints private or blocked on the public listener.

Overly broad permissions:

- Phase 10.10 should keep AWS IAM policies scoped by resource ARN and task role. The blueprint should reject wildcard S3 and Secrets Manager permissions except where tightly justified.
- Runner permissions should be limited to internal API calls and any artifact upload path through Django.

Missing auth boundaries:

- Auth is intentionally deferred until Phase 10.7, which is a reasonable sequencing choice for domain iteration. The risk is Phase 10.6 external AI parsing before auth. That phase needs environment, cost, and data-governance gates.

Artifact upload abuse:

- Phase 10.4 has per-file and per-step caps, but total and tenant-level quotas need to be mandatory before production.

Audit tampering:

- Phase 10.3 prevents application-level mutation but should not imply database-level immutability. The blueprint needs explicit trust-boundary language and minimal DB-role/backup controls.

## 9. Scalability Review

The blueprint set mostly preserves a lightweight v1 design. It avoids Kafka, Celery, Redis, and WebSockets unless later production requirements justify them. That is consistent with the Phase 01 architecture.

Scalability risks:

- Process-local SSE does not scale across multiple API tasks. This is the one area where the production deployment target may force a justified external pub/sub dependency.
- Synchronous integration dispatch can add request latency proportional to enabled integrations. The blueprint needs a total dispatch budget.
- Approval waits can tie up runner capacity if waiting executions remain claimed.
- Artifact uploads can drive storage and request pressure without mandatory total and tenant quotas.
- AI parse caching needs bounded memory behavior.

The recommended posture is not to add queues broadly. The only likely justified infrastructure addition is an event transport for live streaming if production requires multiple API tasks and reliable push updates. Everything else can remain synchronous and service-based with strict limits.

## 10. Maintainability Review

The Phase 10 documents mostly maintain the established code organization:

- Business logic belongs in `services.py`.
- Views and serializers should stay thin.
- Runner behavior should be driven by Django API responses, not local policy logic.
- FastAPI AI remains advisory and stateless.
- API namespaces remain versioned.

Maintainability gaps:

- Conflicting policy semantics will create duplicated or divergent enforcement logic.
- Runner approval behavior needs one normalized step-start/evaluation contract before policies expand it.
- Health endpoint semantics should be named by operational purpose, not collapsed into one `/health/`.
- Integration sync/async drift will confuse test fixtures and timeout handling.
- The roadmap should map historical expansion labels to actual Phase 10 filenames.

## 11. Testability Review

Several documents define useful test expectations, but the blueprint set should standardize verification evidence.

Missing or weak test gates:

- Policy conflict resolution must have one canonical test set shared by backend and UI expectations.
- Policy-required approval must test the case where workflow `requiresApproval=false` but policy returns `ApprovalRequired`.
- SSE must have an integration test proving a sync Django service state update reaches an active subscriber.
- AWS deployment verification must test that public `/api/v1/internal/` paths are denied.
- Health check tests must prove ALB readiness does not depend on AI availability.
- Metrics tests must prove production metrics access is denied without the configured token/private network path.
- Artifact tests should include per-file, per-step, per-execution, and future per-organization quota failures.

Recommended verification artifact:

- Add a standard per-phase readiness record under a documentation path such as `docs/audits/` or `docs/verification/`.
- Each record should include commands run, manual checks, environment assumptions, rollback notes, and explicit signoff that prior phase gates were met.

## 12. Sequencing/Dependency Review

The intended sequencing is mostly correct:

- Approvals before policies is correct.
- Policies before audit-sensitive expansion is correct.
- Audit before artifacts and integrations is correct where audit-sensitive object and integration events are required.
- Auth after domain iteration is reasonable and avoids destabilizing early workflow/runner/AI design.
- Production hardening before AWS deployment is correct.

Sequencing corrections needed:

1. Phase 10.1 should not be required to emit audit events before Phase 10.3.
2. Phase 10.2 must include the runner contract update needed for policy-driven approval.
3. Phase 10.3 should clarify audit trust boundaries before artifacts and integrations rely on audit for compliance-like claims.
4. Phase 10.6 must add pre-auth AI safety controls because auth intentionally comes later.
5. Phase 10.8 must be reconciled with Phase 10.10 before production deployment.
6. Phase 10.10 must make private internal runner routing mandatory before exposing the AWS stack.

## 13. Recommended Fixes As Patch Plans, Not Actual Patches

Patch plan 1: Roadmap consistency cleanup

- Update policy conflict language to ordered first-match semantics, or update Phase 10.2 to stricter-outcome semantics. Prefer first-match.
- Replace the impossible approval audit release gate with durable approval decision persistence.
- Add a roadmap mapping table from historical expansion labels to Phase 10 document filenames.

Patch plan 2: Approval and policy contract

- Add a Phase 10.2 runner-contract subsection.
- Define a normalized Django response for every step start/evaluation attempt.
- Add tests for policy-required approval on a step that does not declare approval in workflow JSON.

Patch plan 3: Audit trust boundary

- Rename the guarantee to application-level append-only.
- Add DB role, backup, admin read-only, and no-update/delete controls.
- Add a future optional tamper-evidence note without making it v1 scope.

Patch plan 4: Artifact abuse controls

- Make total per-execution artifact quota mandatory.
- Add configurable per-organization/per-runner upload ceilings.
- Add quota failure tests and explicit user-facing error behavior.

Patch plan 5: Integration latency and client consistency

- Define maximum integrations per trigger and total dispatch budget.
- Pick `httpx.Client` or `httpx.AsyncClient` consistently. Prefer sync client for the current sync Django blueprint.
- Add tests proving integration failures never fail primary state transitions.

Patch plan 6: AI parsing safety before auth

- Add `AI_PARSE_ENABLED`, size/rate/cost limits, redaction guidance, and environment restrictions.
- Expand cache key and bound cache size.
- State that external model/API choices must be verified against current official docs during implementation.

Patch plan 7: Auth migration and internal error contract

- Add a preflight gate for custom user migration/reset.
- Define internal endpoint auth error mapping for missing runner token, user JWT, invalid token, and valid runner token.

Patch plan 8: Live streaming production viability

- Fix the sync-to-async event emission mechanism.
- Add an integration test using real sync service updates.
- Add a Phase 10.10 deployment gate: external pub/sub for multi-task API, or disable streaming and use polling fallback until that exists.

Patch plan 9: Hardening and AWS boundary

- Split liveness, readiness, and dependency health endpoints.
- Require CSP middleware/package and response-header tests.
- Require production metrics auth or private network restriction.
- Make public denial/private routing for `/api/v1/internal/` mandatory.

## 14. Prioritized Action Plan

1. Fix B-01, B-02, and B-03 before any Phase 10.1/10.2 implementation prompt is issued.
2. Fix B-04 and B-05 before Phase 10.8 implementation starts or before AWS deployment claims live streaming support.
3. Fix H-01, H-02, and H-08 before any production AWS environment is exposed.
4. Fix H-03 before audit is used as a compliance or security guarantee for artifacts/integrations.
5. Fix H-04 before implementing auth migrations.
6. Fix H-05 before enabling AI parsing outside a private development environment.
7. Fix H-06 before enabling outbound integrations for real users or runners.
8. Clean up the MEDIUM and LOW items during blueprint cleanup before coding each affected phase.

## 15. Must Fix Before Implementation

Must fix before Phase 10 implementation proceeds as a chain:

- B-01: Policy conflict-resolution contract conflicts.
- B-02: Approval audit gate requires audit before audit exists.
- B-03: Policy-required approvals need a runner contract change.
- B-04: Sync event emission can no-op in production.
- B-05: Process-local SSE bus conflicts with multi-task API deployment.

Must fix before production deployment:

- H-01: Internal runner endpoints must be private at the AWS boundary.
- H-02: ALB health checks must not depend on AI availability.
- H-08: Metrics endpoint must not fail open in production.

Must fix before affected phase implementation:

- H-03 before Phase 10.3 audit implementation.
- H-04 before Phase 10.7 auth implementation.
- H-05 before Phase 10.6 is enabled outside private dev/staging.
- H-06 before Phase 10.5 integrations are used by real workflows.
- H-07 before Phase 10.9 claims browser security hardening.

## 16. Safe To Defer

These can be deferred if they are tracked and do not block the affected implementation:

- Full tamper-evident audit storage, as long as the v1 blueprint says application-level append-only and does not claim stronger immutability.
- Queue-backed integration dispatch, as long as synchronous dispatch has strict time and count budgets.
- Redis or another external event bus, as long as Phase 10.8 streaming is not claimed to work across multiple API tasks and polling fallback remains active.
- Advanced artifact lifecycle management such as retention classes and search, as long as quota and upload-abuse controls exist.
- Compliance-grade tenant data preservation during auth migration, as long as the project remains pre-production and DB reset is an accepted gate.
- Roadmap numbering polish, after the blocker sequencing conflicts are fixed.

## 17. Final Readiness Verdict

Phase 10 is architecturally close to the intended lightweight production expansion, but the blueprint set is not implementation-ready. The documents preserve the main Phase 01-09 invariants, but several Phase 10 documents conflict with each other in ways that affect control-plane behavior, security boundaries, and production topology.

Readiness verdict: NOT READY for Phase 10-xx implementation as a chain.

Implementation may proceed only after the blocker-level blueprint corrections are made and re-reviewed. The recommended fixes are mostly small document patches: align policy semantics, correct the approval/audit gate, define the policy-driven runner contract, repair the live event bus design, and reconcile streaming with AWS multi-task deployment. Once those are fixed, the remaining HIGH and MEDIUM findings can be handled phase-by-phase before coding the affected area.
