# Phase 10 Expansion Blueprints — Claude Independent Architecture Audit

| Field | Value |
|---|---|
| Auditor | Claude (Opus 4.7) |
| Scope | All `docs/blueprints/phase-10-*.md` documents and the Phase 10 roadmap |
| Date | 2026-04-24 |
| Mode | Read-only; no source files, blueprints, or other audits modified |
| Companion document | `docs/audits/phase-10-expansion-blueprints-audit.md` (Codex) — read for comparison only |

---

## 1. Executive summary

Phase 10 is a strategically sound expansion roadmap. The architectural invariants (Django as control plane, runner-only-to-Django, frontend-only-to-Django, FastAPI advisory, no premature event infrastructure) are preserved across all ten expansion documents. Sequencing — approvals → policies → audit → artifacts → integrations → AI → auth → streaming → hardening → AWS — is broadly correct.

The blueprint set is **not implementation-ready as a chain**. The defects are not architecture errors; they are contract conflicts, sequencing inconsistencies, and several latent operational hazards that become real the moment the documents are followed literally. Most fixes are document edits; one (live event streaming under multi-task production) requires either accepting a real availability tradeoff or scoping in a justified pub/sub backend.

Highest-impact concerns:

- The roadmap and Phase 10.2 disagree on policy conflict resolution (stricter-wins vs first-match).
- Phase 10.1 runner contract does not satisfy Phase 10.2 policy-driven approval requirements.
- Phase 10.1's release gate requires an audit event that the audit system (10.3) does not yet exist.
- Phase 10.8's process-local SSE bus is incompatible with Phase 10.10's multi-task ECS API service, and the in-process `emit()` path silently no-ops in the most common Django ASGI execution mode.
- Phase 10.5 integration dispatch and Phase 10.6 post-execution AI summarization are both synchronous in request paths driven by the runner, allowing remote third-party latency to stall execution state transitions for tens of seconds.
- Phase 10.10 leaves `/api/v1/internal/` reachable on the public ALB by default ("not exposed publicly *if avoidable*"), defending it only by token auth.
- Phase 10.3 audit immutability is application-only and has unresolved tension with Phase 10.7's `PROTECT` FKs.

**Verdict:** NOT READY. Implementation should not begin until BLOCKER-level issues are resolved with blueprint-only edits.

### Finding counts

| Severity | Count |
|---|---:|
| BLOCKER | 6 |
| HIGH | 11 |
| MEDIUM | 10 |
| LOW | 5 |
| Total | 32 |

---

## 2. Documents reviewed

Phase 10 documents:

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

Architectural references inspected for drift:

- `CLAUDE.md` (project invariants)
- `docs/blueprints/phase-01-end-to-end-vertical-slice-blueprint.md`
- `docs/blueprints/phase-02-django-domain-foundation-blueprint.md` (skim)
- `docs/blueprints/phase-04-versioned-rest-apis-blueprint.md` (skim)
- `docs/blueprints/phase-05-runner-real-flow-blueprint.md` (skim)
- `docs/blueprints/phase-07-ai-service-boundary-blueprint.md` (skim)
- `docs/blueprints/phase-09-local-operational-polish-blueprint.md` (skim)

Comparison reference (read but not used as source of truth):

- `docs/audits/phase-10-expansion-blueprints-audit.md` (Codex)
- `docs/audits/phase-10-readiness-audit.md` (prior readiness audit)

---

## 3. Audit methodology

1. Re-read each Phase 10 blueprint end-to-end (or cover the structural sections in detail and skim repetitive milestone breakdowns).
2. For every cross-document reference (e.g., 10.2 referring to 10.1's runner contract; 10.10 referring to 10.8's stream endpoint), check the referenced blueprint to verify the contract actually exists in the form claimed.
3. Walk the architecture invariants (`CLAUDE.md` §"Architecture") against each blueprint's "Architecture invariants and boundaries" table to look for stated-but-violated rules.
4. Walk the "request lifetime" of an execution from runner claim → step start → policy eval → approval → command → artifacts → completion → integrations dispatch → audit → SSE → AI summary, looking for places where blocking calls accumulate, where state may be observed before commit, or where a single slow dependency stalls the runner.
5. Walk security: SSRF, credential storage, secret leakage in logs/audit/serializers, internal endpoint reachability, audit tampering, artifact upload abuse, AI input handling.
6. Walk multi-tenancy: every model with an `organization` FK, every queryset, every cache key.
7. Compare against the Codex audit only after forming independent findings; mark agreement, refinement, or new ground per finding.

No source files were read or modified. No commands were run. Only blueprint and audit markdown was inspected.

---

## 4. Comparison note against the Codex audit

The Codex audit (21 findings: 5 BLOCKER, 8 HIGH, 6 MEDIUM, 2 LOW) is high-quality. Its blockers are all real, and its fix recommendations are mostly correct. This Claude audit:

- **Confirms** every Codex BLOCKER (B-01 through B-05) as a true blocker, with the same recommended fixes.
- **Confirms** Codex HIGH findings H-01 (internal endpoint AWS reachability), H-02 (health check / AI dependency coupling), H-03 (audit immutability overstated), H-05 (AI parse pre-auth controls), H-06 (sync integration dispatch), H-07 (CSP without middleware), H-08 (metrics fail-open).
- **Refines** Codex M-03 (internal JWT vs runner token) into a concrete contradiction inside Phase 10.7 itself (the documented 401/403 contract in §6.3 is not satisfied by the implementation pattern in §9.3).
- **Refines** Codex H-06 by adding the runner-stall multiplier: dispatch is per-trigger but is called from execution service paths that the runner is actively waiting on, not a user-initiated HTTP request. The latency budget compounds against runner throughput, not just user UX.
- **Adds** several findings Codex did not call out:
  - N-01: Phase 10.6 `summarize_execution` is invoked synchronously from `complete_execution`, so the runner's terminal-state HTTP call can hang up to ~60s on OpenAI.
  - N-02: Phase 10.1 `actor_display_name` on the public decide endpoint is client-supplied and pre-auth — approval attribution is forgeable until 10.7.
  - N-03: Phase 10.1 timeout resolution is read-driven only; if no runner polls and no UI polls (e.g., runner crashed, page closed), expired approvals never resolve. 10.9's `recover_stuck_executions` watchdog covers executions but not approval requests.
  - N-04: Phase 10.2 §11.3 raises an unresolved decision about whether `AutoApprove` may waive workflow `requiresApproval=true` and explicitly defers it to a "human approval gate before implementation" — but no default is documented, and the roadmap and 10.2 contradict each other on this same point.
  - N-05: Phase 10.7 `decided_by` and `actor_user` FKs use `PROTECT`, which makes user deletion impossible after any approval/audit activity. This conflicts with the audit-immutability "denormalized snapshot" rationale and with reasonable account-deletion / GDPR posture.
  - N-06: Phase 10.4 conflicts with itself on storage-write vs DB-create ordering (§5.1 `upload_status: failed` implies DB-first; §13 risk table has "Generate artifact ID and storage key first. Save storage, then create DB row" *and* "Prefer storage write before DB create" *and* the failed-row pattern).
  - N-07: Phase 10.6 model pinning is inconsistent: `.env.example` default is unpinned `gpt-4o`, but the prompt-drift mitigation explicitly recommends pinning to `gpt-4o-2024-11-20`. Drift hits production silently.
  - N-08: Phase 10.10 / 10.7 / 10.5 — the request body's `organization_id` field (in 10.5 integration create, 10.1 approvals query, etc.) is not explicitly cross-checked against `X-Organization-Id` header. After auth, two sources of org identity create a mismatch surface.
  - N-09: Phase 10.5 SSRF mitigation is documented at validation time and dispatch time, but the actual `httpx.Client.post` call resolves DNS *again* — a TOCTOU window remains. Standard mitigation requires pinning the resolved IP into a custom transport.
  - N-10: Phase 10.6 `_load_workflow_schema` uses `Path(__file__).parents[5]` — brittle against future repo layout changes.
  - N-11: Phase 10.6 cache key is content-only — Codex M-02 — but also: post-auth, identical content from two organizations would produce a cross-tenant cache hit until the org_id is added to the key. This is not just stale-output risk but a tenant data confusion risk.
  - N-12: Phase 10.10 leaves AI service entirely auth-less inside the VPC (per INV-4). Network isolation is the only barrier. Should be explicit; should require the AI service security group to be locked to API task SG only — which the blueprint says but does not enforce in a verification gate.
  - N-13: Phase 10.7 `X-Organization-Id` header is required on every authenticated request, but the `/api/v1/auth/me/` flow runs *before* an org is selected. Header-required + bootstrap-without-org needs a documented exception list.
  - N-14: Phase 10.5 integration dispatch happens after `transaction.atomic()` exits but before the request returns; if the same request is wrapped in an outer transaction (some Django middleware patterns), the visibility race remains. The "after commit" rule should explicitly recommend `transaction.on_commit()`.
  - N-15: Phase 10.3 audit emit is required to be in the same transaction as the action — but Phase 10.5 integration dispatch is required to be *outside* the transaction. Both can write to the same `services.py` function. The blueprints do not give a worked example of the correct ordering when both are present.

- **Disagrees with** none of Codex's severity classifications, but escalates the *cumulative* operational risk of B-04 + B-05 + N-01 + Codex H-06 because they all point at the same failure: the runner's per-step Django HTTP calls are gradually being loaded with synchronous third-party calls that no individual blueprint owns end-to-end.

---

## 5. Severity legend

| Severity | Meaning |
|---|---|
| BLOCKER | Must be fixed before any Phase 10-xx implementation prompt is issued. Contracts conflict; following the blueprint as written produces incorrect or unsafe behavior. |
| HIGH | Should be fixed before implementing the affected expansion phase. Operational hazard, security gap, or sequencing error that is small to fix in a blueprint and large to fix in code. |
| MEDIUM | Should be fixed during blueprint cleanup or before coding the affected area. |
| LOW | Polish, clarity, or future-proofing. |

---

## 6. Findings table

| ID | Severity | Phase(s) | Document(s) | Issue | vs Codex |
|---|---|---|---|---|---|
| C-B01 | BLOCKER | Roadmap, 10.2 | Roadmap §4.2; 10.2 §5.2, §11.3 | Policy conflict resolution: roadmap says "stricter outcome wins"; 10.2 says "first match wins, do not add stricter wins." | Confirms B-01 |
| C-B02 | BLOCKER | Roadmap, 10.1, 10.3 | Roadmap §6 release gates; 10.1 §3, §13; 10.3 | Roadmap 10.1→10.2 gate requires "approval audit event written in same transaction" but 10.1 explicitly defers any audit dependency until 10.3. | Confirms B-02 |
| C-B03 | BLOCKER | 10.1, 10.2 | 10.1 §7.1; 10.2 §8.3, §8.8 | Runner only enters the approval branch when `requires_approval=true` from workflow JSON, so policy-driven approvals (workflow says false, policy says required) are never honored by the runner. 10.2 quietly redesigns the runner contract but 10.1 does not adopt it. | Confirms B-03 |
| C-B04 | BLOCKER | 10.8 | 10.8 §6.2 | `ExecutionEventBus.emit()` calls `asyncio.get_running_loop()` and silently returns when no loop exists — the dominant case in sync Django views run via uvicorn's threadpool. Events are dropped while tests pass. | Confirms B-04 |
| C-B05 | BLOCKER | 10.8, 10.10 | 10.8 §6.2; 10.10 §5 ECS section | Process-local in-memory bus + ECS desired count ≥ 2. Runner state-update lands on one task, browser SSE subscriber on another. Sticky sessions on ALB do not solve this (different clients). | Confirms B-05 |
| K-B06 | BLOCKER | 10.2, Roadmap | 10.2 §11.3; Roadmap §4.2 | 10.2 §11.3 explicitly raises but does not resolve whether `AutoApprove` may waive a workflow's `requiresApproval=true`. Roadmap §4.2 says "policy overrides the schema." Both must agree before any policy code is written. | New |
| C-H01 | HIGH | 10.10 | 10.10 §5 (ALB routing) | "Do not expose internal runner endpoints publicly *if avoidable*" is too weak for `/api/v1/internal/` once the public ALB is live. | Confirms H-01 |
| C-H02 | HIGH | 10.9, 10.10 | 10.9 §6.4; 10.10 §5 (health checks) | `/health/` checks DB and AI; AI degradation causes ALB to mark API unhealthy. Liveness/readiness/dependency-health must be split. | Confirms H-02 |
| C-H03 | HIGH | 10.3 | 10.3 §5.5 | "Immutable" overstated; only application-level append-only. DB role/backup/admin posture not specified. | Confirms H-03 |
| C-H04 | HIGH | 10.7 | 10.7 §5.1 ("Critical note"), Milestone 1 | `AUTH_USER_MODEL` swap after FKs to default `auth_user` exist is risky. Blueprint mentions DB drop as workaround but does not gate it. | Confirms H-04 |
| C-H05 | HIGH | 10.6, 10.7 | 10.6 §11; 10.7 (no AI guardrails) | Real LLM parsing is enabled before auth, with no per-org opt-in, no production kill switch, and no enforced cost ceiling. | Confirms H-05 |
| C-H06 | HIGH | 10.5 | 10.5 §7.5; 10.9 §6.1 | Dispatch is synchronous in the request that updates execution state. Multiple integrations + 3s timeout + runner-driven trigger compounds latency. Codex flagged user-latency; *runner throughput* is the bigger hit. | Refines H-06 |
| K-H07 | HIGH | 10.6 | 10.6 §6.3, §10.5 | `summarize_execution` is called inline from `complete_execution`. With `AI_READ_TIMEOUT_SECONDS=60`, the runner's terminal-status HTTP call can stall up to 60s waiting on OpenAI. | New |
| K-H08 | HIGH | 10.1 | 10.1 §6.1 | `actor_display_name` on `POST /approvals/{id}/decide/` is client-supplied. Pre-auth, any caller can spoof "approved by Alice." Audit and integration notifications inherit the lie. | New |
| C-H09 | HIGH | 10.9 | 10.9 §7 (settings only); no CSP middleware | CSP_*_SRC settings are added but `django-csp` (or equivalent middleware) is not added to requirements or `MIDDLEWARE`. Headers never emitted. | Confirms H-07 |
| C-H10 | HIGH | 10.9, 10.10 | 10.9 §5.3 | `/metrics/` allows access when `PROMETHEUS_METRICS_TOKEN` is unset. Production startup must fail closed. | Confirms H-08 |
| K-H11 | HIGH | 10.5, 10.10 | 10.5 §9.2; 10.10 (no enforcement) | SSRF check at validation and at dispatch resolves DNS, but `httpx.Client.post` resolves DNS again → TOCTOU. AWS deployment is the threat boundary; production mitigation needs IP-pinning or an outbound proxy. | New (extends Codex security review) |
| C-M01 | MEDIUM | 10.4 | 10.4 §6.5 | Per-execution total quota and per-org/per-runner quotas are optional. Pre-auth, there is no per-runner accountability either. | Confirms M-01 |
| C-M02 | MEDIUM | 10.6, 10.7 | 10.6 §5.5 | Cache key is content hash only. No prompt version, model, or org. Unbounded dict. | Confirms M-02 |
| K-M03 | MEDIUM | 10.7 | 10.7 §6.3 vs §9.3 | Documented contract is "user JWT on internal → 403"; documented implementation registers only `RunnerTokenAuthentication` on internal views, which produces 401 for invalid Bearer tokens. The blueprint contradicts itself. | Refines Codex M-03 |
| C-M04 | MEDIUM | 10.5, 10.9 | 10.5 §7.5; 10.9 §6.1 | Phase 10.5 says `httpx.Client`; Phase 10.9 timeout table says `httpx.AsyncClient` for integrations. | Confirms M-04 |
| C-M05 | MEDIUM | All 10.x | Roadmap; all phases | Verification evidence required but not standardized as a durable artifact. | Confirms M-05 |
| C-M06 | MEDIUM | 10.1 | 10.1 §11 | Long approval waits hold runner concurrency; no production sizing gate. | Confirms M-06 |
| K-M07 | MEDIUM | 10.1, 10.9 | 10.1 §11 (acknowledged); 10.9 §4 | Approval timeout resolution is "read-driven only" — depends on runner polling or UI polling. Phase 10.9's `recover_stuck_executions` covers executions but does not sweep `ApprovalRequest.expires_at`. | New |
| K-M08 | MEDIUM | 10.4 | 10.4 §5.1 (`upload_status`) vs §13 risk table | Self-conflicting guidance on storage-write vs DB-create ordering and on the `failed` upload status role. | New |
| K-M09 | MEDIUM | 10.5 | 10.5 §9.5 | Audit emission for `integration.created/updated/deactivated` is required, but dispatch path uses `transaction.on_commit`-style ordering while audit requires same-transaction writes. The two patterns must coexist in one service function; no example shows the correct order. | New |
| K-M10 | MEDIUM | 10.7, 10.5 | 10.7 §3; 10.5 §9.4 | Multiple sources of truth for organization scope (URL param, request body `organization_id`, `X-Organization-Id` header). Cross-checks required but not mandated as a service-layer invariant. | New |
| C-L01 | LOW | All 10.x | Multiple | "File created" trailer sections persist as if these were generation artifacts. | Confirms L-01 |
| C-L02 | LOW | Roadmap | Roadmap §4 | Numbering drift between §4.1–4.10 labels and `phase-10-01`–`phase-10-10` filenames. | Confirms L-02 |
| K-L03 | LOW | 10.6 | 10.6 §10.1 (`AI_PARSE_MODEL=gpt-4o`) vs §11 (recommend pinning to dated alias) | Default is unpinned; mitigation recommends pinning. Either default to a pinned dated alias or document the deliberate float. | New |
| K-L04 | LOW | 10.7 | 10.7 §5.4, §5.2 | `decided_by` and FKs to `User` use `PROTECT`. Combined with audit denormalized-actor rationale, user deletion becomes impossible after any approval activity. Should be `SET_NULL` plus reliance on `actor_label` snapshot. | New |
| K-L05 | LOW | 10.8 | 10.8 §8.4 | `applyStreamEvent` matches steps by `position` rather than `step_id`. Brittle if positions are ever reordered. | New |

Legend: `C-*` agrees with Codex (same root issue), `K-*` is a Claude-original finding or substantive refinement.

---

## 7. Detailed findings grouped by phase / document

### 7.1 Roadmap (`phase-10-platform-expansion-roadmap-blueprint.md`)

**C-B01 — Policy conflict resolution conflict (BLOCKER)**

- Roadmap §4.2 "Conflict resolution: If two active policies apply to the same step and produce different outcomes, the stricter outcome wins."
- 10.2 §5.2 "Do not add 'stricter outcome wins' in this phase. It sounds safe but creates surprising behavior … Deterministic first-match semantics are easier to reason about and easier to audit."
- Why it matters: a v1 policy engine with two interpretations across project documents is the most expensive kind of contract drift. It surfaces in code, UI, tests, and auditing simultaneously.
- Recommended blueprint-only fix: keep 10.2's first-match semantics. Update Roadmap §4.2 conflict text to "Rules across all active policies are sorted globally by `(priority, policy.created_at, policy.id, rule.id)`; the first matching rule wins." Update Roadmap §6 10.1→10.2 gate language to match.
- Implementation risk if ignored: divergent enforcement paths between backend, UI preview, and tests; non-auditable policy outcomes.
- Codex agreement: same finding, same fix (B-01). Confirmed.

**C-B02 — Approval audit gate requires audit before audit exists (BLOCKER)**

- Roadmap §6 (10.1→10.2 gate): "Approval audit event written in same transaction: covered by test."
- 10.1 §3 (boundaries): "Approval decisions are persisted in approvals tables only. They do not depend on a future audit app."
- 10.3 introduces `AuditEvent`.
- Why it matters: the gate is unsatisfiable in 10.1 and falsely signals readiness for 10.2.
- Recommended blueprint-only fix: rewrite the 10.1→10.2 gate as "Approval decision and approval-state transition occur in the same DB transaction." Move "approval audit event in same transaction" into 10.3's release gate as forward-only coverage.
- Codex agreement: B-02. Confirmed.

**C-L02 — Numbering drift (LOW)**

- Roadmap uses §4.1–§4.10; filenames use `phase-10-01-` … `phase-10-10-`.
- Recommended blueprint-only fix: add a one-table cross-reference at the top of §4 mapping each label to its filename.
- Codex agreement: L-02. Confirmed.

### 7.2 Phase 10.1 — Approvals

**C-B03 — Runner contract gap with 10.2 (BLOCKER)**

- 10.1 §7.1 step 2: runner only calls the internal approval-request endpoint "for a claimed step with `requires_approval=true`."
- 10.2 §8.3 quietly extends the runner contract: every step start should go through Django, and Django returns the resulting state including `policy_evaluation` and `approval_request`.
- Net effect if 10.1 is implemented as written and 10.2 is implemented later: a policy that says "approval required" on a step whose workflow JSON has `requiresApproval=false` will create an `ApprovalRequest` in Django but the runner will never enter the wait loop — it will just transition pending→running and execute the command.
- Recommended blueprint-only fix: in 10.1 §7.1, replace the `if requires_approval` branch with a normalized "always ask Django to start the step" contract. Django's response carries `runner_action ∈ {run, wait_for_approval, blocked}`. The runner obeys the response. This makes 10.2 a pure additive concern (Django adds policy evaluation behind the same endpoint).
- Codex agreement: B-03 with the same recommendation. Confirmed.

**K-H08 — Pre-auth actor spoofing (HIGH, new)**

- 10.1 §6.1 `POST /api/v1/approvals/{id}/decide/` accepts `actor_display_name` in the request body and stores it on `ApprovalDecision.decided_by_label`.
- 10.1 §13 says "Once auth exists, Django should ignore client-supplied actor labels and derive the actor from the authenticated user."
- Until auth lands (10.7), any caller — including the integration system, a misconfigured curl, an accidental browser bookmark — can submit `{"decision": "approved", "actor_display_name": "VP of Engineering"}`. That label is recorded as the human accountability trail and propagated to integration notifications (10.5) and audit (10.3).
- Recommended blueprint-only fix:
  - Add to 10.1 §3 boundaries: "Pre-auth, `actor_display_name` is informational only. The system MUST NOT present it as authoritative attribution."
  - Add to 10.5: integration payloads built from approvals must include a `pre_auth=true` flag in the `slack_webhook` block text and the `generic_webhook` payload until 10.7 lands.
  - Add to 10.3: pre-auth actor labels must be stored with `actor_type="unknown"`, not synthesized as `actor_type="user"`.
  - Add to 10.7's release gate: "All `actor_display_name`-style payload fields on existing endpoints are removed or ignored after auth."
- Implementation risk if ignored: forged approval audit and forged Slack notifications during the entire 10.1 → 10.7 window. The window is months-long even if everything goes well.
- Codex coverage: not flagged.

**K-M07 — Read-driven timeout resolution (MEDIUM, new)**

- 10.1 §11 acknowledges "A dead runner will delay timeout observation until another control-plane read occurs" as a residual risk.
- The system has no scheduled job, watchdog, or signal that resolves expired approvals if neither the runner nor the UI polls. 10.9's `recover_stuck_executions` sweeps `Execution.last_heartbeat_at` but not `ApprovalRequest.expires_at`.
- Recommended blueprint-only fix: in 10.9 §4, add `recover_expired_approvals(*, batch_size=100)` to the same management command surface and call it from the same scheduled task that runs the execution watchdog.
- Codex coverage: not flagged. (Codex M-06 covers a related but distinct concern — runner capacity tied up by long approval waits.)

**C-M06 — Long approval waits and runner capacity (MEDIUM)**

- 10.1 commits the runner to a poll loop while a step is `waiting_for_approval`, and the execution remains `claimed`. Multiple long-pending approvals proportionally reduce runner concurrency.
- Recommended blueprint-only fix: add a release gate before 10.10 production rollout requiring measurement of "runner concurrency under N concurrent waiting executions." Document the expected sizing.
- Codex agreement: M-06. Confirmed.

### 7.3 Phase 10.2 — Policies

**K-B06 — Unresolved override semantics (BLOCKER, new)**

- 10.2 §11.3 explicitly states a "Decision required before implementation" about whether `AutoApprove` may waive `requiresApproval=true` from workflow JSON.
- This decision is operational sensitivity in disguise: the entire premise of `requiresApproval` on the workflow is that authors expressing "this step needs human approval" can rely on it being honored.
- Roadmap §4.2 says "Policy overrides the schema." 10.2's "Do not allow override" floor is in tension. 10.2 leaves this for "human approval gate" but ships the floor question as undecided.
- Why it matters: this is the same class of error as C-B01 — two readers can implement opposite enforcement and both can claim to be following the blueprint.
- Recommended blueprint-only fix:
  1. Pick one rule. The safer v1 default is "workflow `requiresApproval=true` is a floor; policy can only escalate to `Block` or leave unchanged at `ApprovalRequired`. `AutoApprove` cannot waive an explicit workflow approval requirement."
  2. Update 10.2 §5.4 outcome table and §11.3 with the chosen rule.
  3. Update Roadmap §4.2 to remove the unconditional "policy overrides the schema" language.
  4. Add a release gate before 10.2 implementation: "the override-vs-floor decision is recorded in the blueprint, and tests cover both paths."
- Codex coverage: not flagged distinctly (subset of B-01 in Codex's writeup but operationally separate).

**Cross-references with 10.1 (B-03) and 10.3:** see C-B03 above and §7.4 below.

### 7.4 Phase 10.3 — Audit Trail

**C-H03 — Immutability is application-level only (HIGH)**

- 10.3 §5.5 documents app-level constraints (override `save`/`delete`, read-only admin) but does not mention DB-level controls (restricted DB role for the API, read-only audit role for support, prohibited direct UPDATE/DELETE on the audit table outside Django shell).
- Recommended blueprint-only fix:
  - Rename "Immutability rules" → "Application-level append-only guarantees."
  - Add a "Trust boundary" subsection: "These guarantees do not protect against direct DB modification by superusers, rogue migrations, or backup/restore manipulation."
  - Add to §5.5 a v1 control set: app `services.py` is the only writer; admin is read-only; production DB credentials for the application role do not include `UPDATE`/`DELETE` on the `audit_auditevent` table; PITR backups are retained.
  - Add a forward-pointer for tamper-evidence (hash chain or external WORM archive) gated on compliance need.
- Codex agreement: H-03. Confirmed and refined.

**K-L04 — `PROTECT` FKs to `User` and audit denormalization conflict (LOW, new)**

- 10.7 §5.4 specifies `decided_by` on `ApprovalDecision` as `PROTECT`; `actor_user` on `AuditEvent` as nullable FK.
- 10.3 §5.1 stores `actor_label` as denormalized snapshot specifically so users can be deleted without rewriting history.
- `PROTECT` blocks user deletion. The denormalized snapshot rationale is then moot.
- Recommended blueprint-only fix: in 10.7 §5.4, switch FKs to `SET_NULL` and rely on the `actor_label` snapshot. Add a test that confirms user soft-delete leaves audit/approval rows readable.

**Sequencing tie-in (C-B02):** see roadmap section.

### 7.5 Phase 10.4 — Artifacts

**C-M01 — Quota controls are optional (MEDIUM)**

- 10.4 §6.5 marks per-execution total quota as conditional and per-organization quota as future work. Pre-auth, runner identity is the only abuse-control axis and is itself unauthenticated end-to-end.
- Recommended blueprint-only fix:
  - Make total per-execution bytes mandatory.
  - Add a single global `ARTIFACT_DAILY_BYTES_PER_RUNNER` ceiling (configurable). Pre-auth this is the only meaningful per-actor limit.
  - Add tests for size, count, total quota, and per-runner ceiling rejection.
- Codex agreement: M-01. Confirmed.

**K-M08 — Storage-write vs DB-create ordering self-conflict (MEDIUM, new)**

- §5.1 introduces `upload_status: available | failed`, implying a DB row can exist before storage success or after storage failure.
- §13 risk table contains *both* "Generate artifact ID and storage key first. Save storage, then create DB row in a transaction" *and* "Prefer storage write before DB create" *and* the failed-row pattern.
- Effect: implementers will pick whichever sequence appears first when scanning.
- Recommended blueprint-only fix: pick one order. The safer v1 sequence:
  1. Generate artifact UUID and storage key in memory.
  2. Stream upload to storage with checksum.
  3. Inside a single `transaction.atomic()`: create `Artifact` row with `upload_status="available"`; emit audit event.
  4. On storage failure before step 3: never create a DB row. Log only.
  5. On DB failure after step 3 success: best-effort delete the storage object, log, do not retry.
- Document this canonical sequence in §5.5 and remove conflicting language from §13.

**Other 10.4 observations:**

- §8.3 `POST /api/v1/artifacts/{id}/download/` will produce one audit event per UI download click, including reflexive "URL expired, click again" retries. Consider a debounce or only audit successful URL generation when the previous URL is older than its TTL.
- The `dangerouslySetInnerHTML` consideration for stdout previews is correctly excluded from 10.4 (no inline previews) — keep that.

### 7.6 Phase 10.5 — Integrations

**C-H06 — Synchronous dispatch in execution paths (HIGH)**

- 10.5 §7.5 commits to `httpx.Client` (sync) with a 3s timeout, no retries, no per-trigger budget. §7.4 lists five trigger points, four of which are inside `ExecutionService` functions called by the runner.
- With N active integrations × 3s × any trigger fired during a runner request, the runner's HTTP call to Django can stall by 3N seconds before returning. The runner is single-threaded per execution; this directly reduces fleet throughput.
- Recommended blueprint-only fix:
  - Define `INTEGRATION_DISPATCH_BUDGET_SECONDS` (e.g., 5s total per trigger) and stop iterating connections once the budget is exhausted; remaining failures recorded as `error_detail="dispatch_budget_exceeded"`.
  - Define `INTEGRATION_MAX_PER_TRIGGER` (e.g., 3 integrations per call); excess connections logged as skipped.
  - Use `transaction.on_commit()` for dispatch ordering (see K-M09 below).
  - Add a release gate before 10.10 production rollout: "single-runner throughput is unaffected by 5 enabled integrations responding in 3s each."
- Codex agreement: H-06. Confirmed and refined (Codex's recommendation already covers most of this; the runner-throughput angle is the additional concern).

**C-M04 — sync vs async client drift (MEDIUM)**

- 10.5 §7.5 → `httpx.Client` (sync). 10.9 §6.1 timeout table → `httpx.AsyncClient`.
- Recommended fix: pick one, document the rationale, propagate to both blueprints. For a sync Django stack, keep `httpx.Client`.
- Codex agreement: M-04. Confirmed.

**K-H11 — SSRF DNS TOCTOU (HIGH, new)**

- 10.5 §9.2 mitigates DNS rebinding by resolving the URL hostname and validating the IP against a private blocklist before dispatch. Then `httpx.Client.post(url, ...)` re-resolves DNS independently — the hostname can resolve to a different IP at connect time.
- Standard mitigations:
  - Resolve once, build the URL with the resolved IP, send `Host` header for the original hostname.
  - Or use a custom `httpx` transport that pins the resolved IP.
  - Or route all integration egress through a forward proxy (AWS NAT plus an HTTP egress proxy with allowlist) — easiest in 10.10.
- Recommended blueprint-only fix:
  - Add to 10.5 §9.2: "Resolve the hostname once and pin the resolved IP to the request transport. The `Host` header preserves SNI and HTTP routing."
  - Add to 10.10 §5: "All ECS task egress to integration destinations must traverse a documented egress path (NAT only, or NAT + HTTP egress proxy)."

**K-M09 — Audit-in-transaction vs dispatch-after-commit ordering (MEDIUM, new)**

- 10.3 §8.2: audit events MUST be in the same `transaction.atomic()` as the action.
- 10.5 §7.4 ordering rule: dispatch MUST be after the transaction commits (otherwise the webhook references uncommitted state).
- Both rules apply to the same service function (e.g., `complete_execution` writes the row, emits an audit event, and dispatches integrations).
- Recommended blueprint-only fix: add to 10.5 §7.4 a worked example showing the canonical pattern:

  ```python
  with transaction.atomic():
      execution.status = "failed"
      execution.save(...)
      AuditService.emit(...)             # in-transaction
      transaction.on_commit(
          lambda: IntegrationService.notify(...)
      )                                  # after-commit
  ```

  And state in 10.3 §8.2: "External-effect dispatchers (e.g., integrations) must be scheduled via `transaction.on_commit`, not called inline. Audit emission remains in-transaction."

### 7.7 Phase 10.6 — Richer AI Parsing

**C-H05 — Pre-auth AI safety controls (HIGH)**

- 10.6 enables real LLM parsing before 10.7. Cost ceiling, redaction, and per-org opt-in are partial:
  - `AI_MAX_INPUT_CHARS` is set (good).
  - `AI_USE_LLM_PARSER=false` is described as a kill switch (good).
  - Redaction is reactive (UI warning, log policy) rather than enforced.
  - No per-org opt-in until 10.7.
  - No production-environment guard.
- Recommended blueprint-only fix:
  - Add `AI_PARSE_REQUIRES_PRIVATE_ENV=True` setting; production startup fails if AI parsing is enabled and the deployment is publicly reachable until org-level opt-in is added in 10.7.
  - Add a per-day cost ceiling (`AI_PARSE_DAILY_BUDGET_USD`) checked before each LLM call and surfaced as a 429 with a clear error code.
  - Make the input-size guard explicit in the API error envelope and add a token-budget estimate in the error message.
  - Move the "do not include secrets" warning from runtime UX into the request payload validation (reject on regex match for obvious credential patterns: AWS keys, JWTs, basic-auth URLs). Defense-in-depth, not a guarantee.
- Codex agreement: H-05. Confirmed.

**C-M02 / K-N11 — Cache key (MEDIUM, refined)**

- 10.6 §5.5: cache key is content hash only; cache is unbounded `dict`.
- Codex correctly flagged this. Adding the org-tenancy concern: post-auth, content `"deploy production service"` from org A should not return a cached parse from org B (even though the parse is content-deterministic — the UI display, audit attribution, and parse-source metadata diverge).
- Recommended blueprint-only fix: cache key = `sha256(content_hash || model || prompt_version || schema_version || org_id_or_NULL)`; bounded LRU with `AI_PARSE_CACHE_MAX_ITEMS` (default 256).

**K-H07 — `summarize_execution` blocks `complete_execution` (HIGH, new)**

- 10.6 §6.5 sets `AI_READ_TIMEOUT_SECONDS=60`. §10.5 ("Django service tests") implies summarize is called inside `complete_execution`. If summarize is called inline, the runner's HTTP call to Django to mark the execution complete can hang up to ~60s on OpenAI.
- This is the same class of failure as C-H06 (sync external calls in runner-driven request paths), but worse:
  - Latency budget is 60s, not 3s.
  - If OpenAI errors, the runner sees a 504 from Django and may retry the terminal-state report.
  - Idempotency on `complete_execution` becomes load-bearing for AI availability.
- Recommended blueprint-only fix:
  - Move summarize to a separate post-commit dispatch (same `transaction.on_commit` pattern as integrations).
  - Cap `AI_SUMMARIZE_TIMEOUT_SECONDS` (default 15s) distinct from `AI_READ_TIMEOUT_SECONDS`.
  - On summarize failure, write a placeholder summary artifact (`"summary_unavailable: <error_code>"`) so the artifact list is still consistent.
  - Make summarize fully optional behind `AI_SUMMARIZE_ENABLED` (default false until measured).

**K-L03 — Model pinning inconsistency (LOW, new)**

- §11 prompt-drift mitigation: "Pin the model version in `AI_PARSE_MODEL` (e.g., `gpt-4o-2024-11-20`)."
- §6.6 / `.env.example` default: `AI_PARSE_MODEL=gpt-4o` (floating).
- Recommended fix: change the documented default to a pinned dated alias and add a CI check that `AI_PARSE_MODEL` matches the regex `.*-\d{4}-\d{2}-\d{2}$` in production settings.

**N-10 (LOW, deduplicated as part of polish):** `_load_workflow_schema` uses `Path(__file__).parents[5]` — fragile. Recommend resolving via a Django setting `WORKFLOW_SCHEMA_PATH` populated in `base.py`.

### 7.8 Phase 10.7 — Authentication and Authorization

**C-H04 — Custom user migration risk (HIGH)**

- 10.7 §5.1 warns about `AUTH_USER_MODEL` swap. Mitigation is "drop the DB" — acceptable pre-production but not a formal gate.
- Recommended blueprint-only fix: add a Phase 10.7 preflight gate that explicitly confirms (a) no production data, (b) all environments will be reset, (c) Milestone 1 runs against a fresh DB.
- Codex agreement: H-04. Confirmed.

**K-M03 — Internal endpoint auth contract self-contradiction (MEDIUM, refined from Codex M-03)**

- §6.3 documents the contract: "User JWT used on internal endpoint → 403."
- §9.3 documents the implementation: `class InternalRunnerView(APIView): authentication_classes = [RunnerTokenAuthentication]`. With only `RunnerTokenAuthentication` registered, a Bearer token containing a user JWT will be treated as a non-runner token and produce `AuthenticationFailed("Invalid runner token.")` → 401. The 403 case never executes.
- Recommended blueprint-only fix: pick one. Either:
  - Update §6.3 to document the actual behavior (401 for any non-runner Bearer), and explain it in the runner client failure mode (treat 401 on internal as "exit immediately").
  - Or keep the 403 contract, but add a second authenticator that detects user JWTs and explicitly raises `PermissionDenied("User sessions are not permitted on internal endpoints.")` before `RunnerTokenAuthentication` returns.
- Codex M-03 covered this as ambiguity; Claude refines it as a concrete contradiction inside the same blueprint.

**K-L04 — `PROTECT` FKs to `User` (LOW, new)** — see §7.4.

**K-M10 — Multiple sources of org identity (MEDIUM, new)**

- 10.7 §3 introduces `X-Organization-Id` header.
- Pre-existing endpoints (10.5 integration create, 10.1 approvals query) accept `organization_id` in body or query.
- After auth, both signals are present. Without a service-layer invariant, drift is inevitable.
- Recommended blueprint-only fix: add to 10.7 §6.4 — "When both `X-Organization-Id` and a body/query `organization_id` are present, they MUST match. Mismatch returns 400 `org_id_mismatch`. The header is the source of truth; body fields become redundant after auth and SHOULD be removed in a 10.7 cleanup pass."

**N-13 (LOW, polish):** `/api/v1/auth/me/` runs before any org is selected. Document the explicit "endpoints that don't require `X-Organization-Id`" allowlist (auth/, health/, metrics/).

### 7.9 Phase 10.8 — Live Event Streaming

**C-B04 — Sync `emit()` no-op (BLOCKER)**

- 10.8 §6.2 `emit()`:
  ```python
  try:
      loop = asyncio.get_running_loop()
  except RuntimeError:
      return  # no event loop in sync test context; ignore
  ```
- Sync Django views run in uvicorn's threadpool by default. There is no running loop in the calling thread. Every emit silently returns. Tests that exercise the SSE endpoint directly may pass because they run in the async view's loop. Tests that exercise the runner's API call → service → emit path will pass (no exception) but no event is delivered.
- Recommended blueprint-only fix:
  - Capture the loop reference at process startup (e.g., in `apps.executions.apps.ExecutionsConfig.ready` after a check) and call `loop.call_soon_threadsafe` against the captured loop, not the caller's loop.
  - Or use `asgiref.sync.async_to_sync(bus._async_emit)(...)` from sync paths — but this blocks the calling thread on the bus, which is exactly what should not happen for an SSE side-effect.
  - Add an integration test: sync service path updates execution state; SSE subscriber on the same process receives the event within 100ms. Without this test, the bug returns silently on every refactor.
- Codex agreement: B-04. Confirmed.

**C-B05 — Process-local bus vs multi-task ECS (BLOCKER)**

- 10.8 §6.2: "It is **process-local**: two `uvicorn` processes will not share event state … Phase 10.10 addresses it with sticky sessions on the ALB or by externalizing the bus to Redis pub/sub."
- 10.10 §5: API service `Desired count production: minimum 2 across AZs`.
- Sticky sessions do not solve cross-client routing: the runner's API call lands on whatever task is selected by the ALB; the browser SSE connection lands on whatever task the user's session is sticky to. They are different clients. There is no policy under which they reliably land on the same task.
- Recommended blueprint-only fix:
  - In 10.8 §6.2 / §11, drop the "sticky sessions" suggestion (it does not solve the problem).
  - Add a 10.10 release gate: "Live streaming is enabled only when one of the following is true: (a) API task count is fixed at 1 (documented availability tradeoff), or (b) an externalized event transport — Redis pub/sub, Postgres LISTEN/NOTIFY without PgBouncer transaction mode, or AWS EventBridge with a per-task subscriber — is in place."
  - In 10.8, explicitly state that the in-process bus is dev/test only and the production bus is gated on 10.10's choice.
- Codex agreement: B-05. Confirmed.

**K-L05 — Step lookup by `position` (LOW, new)**

- 10.8 §8.4 `applyStreamEvent` uses `step.position === event.data.position`. If positions are ever reordered or a workflow defines duplicate positions, the wrong step updates.
- Recommended fix: match by `step_id` (already in the payload).

### 7.10 Phase 10.9 — Production Hardening

**C-H02 — Health check couples API to AI (HIGH)**

- 10.9 §6.4 defines `/health/` to check DB and AI; returns 503 if either is down.
- 10.10 §5 uses `/health/` as the ALB target health check.
- Recommended blueprint-only fix: split into `/health/live` (process up), `/health/ready` (DB + migrations OK), and `/health/dependencies` (AI + integrations + S3, never used by ALB). Update 10.10 §5 to use `/health/ready` for ALB target health.
- Codex agreement: H-02. Confirmed. (10.9 §6.4 already mentions `/health/ready/` for migrations — the fix is to make ALB use it and to drop the AI check from the ALB-facing endpoint.)

**C-H09 — CSP without middleware (HIGH)**

- 10.9 §7 (around line 595) defines `CSP_DEFAULT_SRC`, `CSP_SCRIPT_SRC`, etc.
- No `django-csp` package or custom middleware is added in 10.9 §4 requirements. Settings exist; headers never emit.
- Recommended blueprint-only fix: add `django-csp>=3.7` to `apps/api/requirements/base.txt`, register `csp.middleware.CSPMiddleware` in `MIDDLEWARE`. Add a response-header test: production settings + `curl -I` returns `Content-Security-Policy: default-src 'self'; …`.
- Codex agreement: H-07. Confirmed.

**C-H10 — Metrics fail-open (HIGH)**

- 10.9 §5.3: "allow all if not set (dev mode)".
- Production deployments that forget to set `PROMETHEUS_METRICS_TOKEN` expose `/metrics/` to anyone who can reach the ALB.
- Recommended blueprint-only fix: in `prod.py`, add a startup check: if `PROMETHEUS_METRICS_ENABLED=True` and `PROMETHEUS_METRICS_TOKEN` is empty and no private-network gate is configured, raise `ImproperlyConfigured`. Default `PROMETHEUS_METRICS_ENABLED=False` in `prod.py` until a token is set.
- Codex agreement: H-08. Confirmed.

**N-N15 cross-reference:** see K-M09 in 10.5 for the audit/dispatch ordering finding that touches 10.9's request-lifecycle work.

### 7.11 Phase 10.10 — AWS Deployment Workflows

**C-H01 — Internal endpoints reachable on public ALB (HIGH)**

- 10.10 §5 ALB routing: "Do not expose internal runner endpoints publicly *if avoidable*. If public API and internal API share one Django service, protect `/api/v1/internal/` with Django runner authentication and optionally ALB rules/security restrictions for runner-originating private traffic."
- "If avoidable" / "optionally" are not enough for endpoints that mediate execution claim, state transitions, and artifact upload. Token leak → public exposure.
- Recommended blueprint-only fix: replace "if avoidable" with a hard requirement:
  - Production option A: separate internal ALB (or service-discovery DNS) for runner traffic; runner SG only.
  - Production option B: shared ALB with a listener rule that returns 403 for `/api/v1/internal/*` on the public listener; a private listener (or path on a private ALB) accepts those paths from the runner SG only.
  - Verification gate: "External `curl https://api.example.com/api/v1/internal/executions/claim-next/` returns 403 from the ALB, not 401 from Django."
- Codex agreement: H-01. Confirmed and strengthened.

**N-12 (HIGH, claimed earlier) — AI service auth boundary (refined to MEDIUM)**

- 10.10 §5 puts the AI service on an internal ALB or service discovery, with SG locked to API task SG. INV-4 keeps it auth-less.
- This is the right v1 posture **provided** the SG is enforced exactly as documented. There is no Phase 10.10 verification gate that proves "AI service rejects connections from any task other than the API task."
- Recommended blueprint-only fix: add a verification: "From a debug task in the runner SG, `curl http://ai.internal:8001/parse/runbook` connects-refused or times-out."
- (Adjusting severity to MEDIUM after re-reading the SG language; the gate is the missing piece, not the design.)

**Streaming reconciliation (B-05):** see 10.8 above.

**IAM scope:** Codex recommended scoping IAM to resource ARNs. 10.10 §5 already says "Application IAM policy grants least-privilege access to required prefixes only" and "Runner task role is minimal. It should not include RDS permissions." This is acceptable as a v1 blueprint, but the verification gate should explicitly call for `iam:Simulate` against expected vs unexpected ARNs.

### 7.12 All Phase 10 documents

**C-M05 — Verification evidence not standardized (MEDIUM)** — Codex M-05 covers this fully. Recommend a `docs/verification/phase-10-{NN}-evidence.md` template populated per phase, including commands run, pytest output excerpt, manual gate signoff, and "prerequisite phases verified" checkbox referencing prior evidence files.

**C-L01 — "File created" trailers (LOW)** — Codex L-01.

---

## 8. Cross-document drift findings

The four drift clusters Codex identified are correct. Adding two more:

5. **Audit-in-transaction vs external-effect-after-commit (10.3 vs 10.5 vs 10.6).** Three blueprints make valid demands on the same service function. No worked example shows the canonical pattern. See K-M09.

6. **Runner request lifecycle accumulation (10.1 + 10.2 + 10.5 + 10.6 + 10.8 + 10.9).** The runner makes one HTTP call to Django to start a step. Behind that call, Django now: validates ownership, evaluates policy (10.2), creates an approval request (10.1), holds a `select_for_update` lock (10.2 §8.7), emits audit (10.3), schedules an integration dispatch (10.5), schedules an SSE event (10.8), and increments metrics (10.9). On `complete_execution`, additionally: an inline summarize call may run (10.6 if not deferred). No blueprint owns the cumulative latency budget for this single request. Recommend that 10.9 include a "step transition latency budget" table (e.g., P95 ≤ 200ms exclusive of external calls; integration dispatch deferred to `on_commit`; summarize deferred entirely).

---

## 9. Security review

**SSRF**

- 10.5 has the strongest SSRF treatment in the set. Two gaps:
  - DNS TOCTOU (K-H11) — needs IP pinning or egress proxy.
  - Future AI enrichment routes that fetch URLs (e.g., parsing a Confluence URL instead of pasted text) are not in scope, but a forward-pointer in 10.6 §12 ("Do not let `/parse` accept URLs in v1") would prevent regression.

**Credential leakage**

- 10.5 redaction rules are correct: `encrypted_credentials` not serialized, `payload_preview` size-bounded.
- Risk: `payload_preview` is a free-form `JSONField`. If a future contributor stores `{"webhook_url": "https://..."}` they leak the URL. Recommend service-layer key allowlist on `_build_payload_preview`.
- Audit metadata forbids secrets, claim tokens, raw output — good.
- Metrics endpoint must fail closed (C-H10).

**Unsafe internal endpoints**

- 10.10 must make `/api/v1/internal/` private at the AWS boundary (C-H01).
- 10.7 internal-vs-user JWT contract must be implementable (K-M03).

**Overly broad permissions**

- 10.10 IAM language is conservative but lacks `iam:SimulatePrincipalPolicy`-based verification.
- Runner task role explicitly excludes RDS — good.
- Frontend has no AWS credentials — good.

**Missing auth boundaries**

- The 10.6 → 10.7 window: sensitive runbook content can flow to OpenAI without per-org opt-in, kill switch, or production guard (C-H05).
- Pre-auth `actor_display_name` spoofing (K-H08) is the largest concrete leak in the pre-10.7 window.

**Artifact upload abuse**

- Per-file size capped, per-step count capped. Per-org / per-runner ceilings optional (C-M01).

**Audit tampering**

- Application-only append-only (C-H03). DB role + admin posture must be added.

**AI input handling**

- Input size capped. No per-org rate limit until 10.7. No regex-level secret detection. Recommended in fix list.

---

## 10. Scalability review

The blueprint set preserves the lightweight v1 posture: no Kafka, no Celery, no Redis (until 10.8 forces the question). Risks ranked by likelihood × blast radius:

1. **Process-local SSE under multi-task production (B-05)** — highest. Fix is explicit; defer or externalize.
2. **Synchronous integration dispatch in runner-driven request paths (H-06 + K-H07)** — high. Compounds with summarize-in-complete-execution (K-H07).
3. **Approval polling concurrency (M-06)** — medium. Bounded by runner fleet size.
4. **Audit table growth (Codex 4.3 risks)** — already correctly addressed; only flag is missing index gate.
5. **AI parse cache memory growth (M-02)** — bounded by adding LRU.

The recommended posture remains: do not introduce queues. The single justified infrastructure addition is a real event transport for live streaming if and only if production requires multiple API tasks.

---

## 11. Maintainability review

The Phase 10 documents mostly preserve `services.py` ownership, thin views, advisory FastAPI, and versioned APIs. The maintainability gaps are concentrated in:

- Two blueprints documenting opposite policy semantics (C-B01).
- Two blueprints documenting opposite integration HTTP client choices (C-M04).
- One blueprint documenting opposite storage-write orderings inside itself (K-M08).
- One blueprint documenting an auth contract its own implementation pattern doesn't satisfy (K-M03).
- The roadmap's §4.x label vs `phase-10-NN` filename drift (C-L02).

Each is fixable with small text edits.

The cumulative loading of synchronous side-effects on the runner's per-step request (drift cluster #6) is a maintainability bomb: as written, every blueprint adds another inline call to the same hot path, and no document owns the budget.

---

## 12. Testability review

Strong testability where each blueprint already calls for service-layer tests, contract tests, and concurrency tests. Weak testability where contracts span two blueprints:

- Policy + approval (C-B03): needs a contract test that exercises `requiresApproval=false` workflow + matching policy → `ApprovalRequest` created + runner enters wait.
- SSE + sync service (C-B04): needs an integration test that calls a sync service from a sync DRF view and asserts an SSE subscriber on the same process receives the event.
- AWS public denial (C-H01): needs an automated check that a test request to `/api/v1/internal/*` against the public ALB returns 403.
- Health vs ALB (C-H02): needs a test that AI down + DB up returns 200 from the ALB-facing `/health/ready/`.
- Metrics auth (C-H10): production startup test that `PROMETHEUS_METRICS_TOKEN` absent → startup failure.
- Storage ordering (K-M08): test that DB-row count and storage-object count are equal after a fault-injected upload.

Standardize evidence per Codex M-05.

---

## 13. Sequencing / dependency review

Sequencing is broadly correct. Adjustments needed:

1. 10.1 must not be required to emit audit events before 10.3 exists (C-B02).
2. 10.2 must update the runner contract (C-B03), because 10.1 cannot anticipate it.
3. 10.3 audit trust boundaries must be clarified before 10.4 / 10.5 cite audit as a security control (C-H03).
4. 10.6 must add pre-auth AI safety controls because auth intentionally comes later (C-H05).
5. 10.7 must resolve its internal endpoint auth contradiction before runner deployment depends on 401-vs-403 behavior (K-M03).
6. 10.8 must be reconciled with 10.10 before any production rollout claims live streaming (C-B05).
7. 10.9 must add `recover_expired_approvals` alongside `recover_stuck_executions` (K-M07).
8. 10.10 must mandate private routing for `/api/v1/internal/` (C-H01).

Order of expansion phases is otherwise correct.

---

## 14. Findings Codex missed or treated differently

| ID | Codex coverage | Difference |
|---|---|---|
| K-B06 | Subset of B-01 | Claude separates the override-vs-floor decision because it is operationally distinct from conflict resolution. |
| K-H07 | Not flagged | Synchronous summarize in `complete_execution` blocks runner; same family as Codex H-06 but worse latency budget. |
| K-H08 | Not flagged | Pre-auth `actor_display_name` spoofing across 10.1/10.3/10.5. |
| K-H11 | Implicit in security review | Codex described SSRF as "strongest treatment in the set"; Claude flags the DNS TOCTOU still present. |
| K-M03 | Codex M-03 (ambiguity) | Claude finds it is a self-contradiction inside 10.7 §6.3 vs §9.3. |
| K-M07 | Not flagged | Read-driven approval timeout; 10.9 watchdog gap. |
| K-M08 | Not flagged | 10.4 self-conflict on storage/DB ordering. |
| K-M09 | Not flagged | Audit-in-tx vs dispatch-after-commit must coexist; no worked example. |
| K-M10 | Not flagged | Multiple sources of org identity post-auth. |
| K-L03 | Not flagged | Model-pinning inconsistency in 10.6. |
| K-L04 | Not flagged | `PROTECT` FKs to `User` vs audit denormalization. |
| K-L05 | Not flagged | SSE step lookup by `position`. |

Severity disagreements: none of Codex's classifications are escalated or downgraded. C-H06 is refined (added runner-throughput angle) but the severity is unchanged.

---

## 15. Recommended fixes as patch plans (not actual patches)

**Patch plan 1: Roadmap consistency**

- §4.2: replace "stricter outcome wins" with "ordered first matching rule wins (sort key: priority, policy.created_at, policy.id, rule.id)".
- §4.2: remove "Policy overrides the schema" or qualify as "Policy can escalate to `ApprovalRequired` or `Block`; policy cannot waive a workflow's `requiresApproval=true`."
- §6 (10.1→10.2 gate): replace audit-event requirement with "Approval decision and approval-state transition occur in the same DB transaction."
- §6 (10.2→10.3 gate): add "Workflow `requiresApproval=true` floor is honored by tests."
- §4 add a label-to-filename mapping table.

**Patch plan 2: Approval / policy / runner contract**

- 10.1 §7.1: replace "if requires_approval" branch with "always call `POST /api/v1/internal/executions/{id}/steps/{id}/start`; obey `runner_action ∈ {run, wait_for_approval, blocked}`."
- 10.2 §8.8: confirm Django's start endpoint owns policy evaluation; remove any need for runner-local schema reads.
- Add contract test in 10.1 milestone gate: `requiresApproval=false` workflow + future policy match returns `runner_action=wait_for_approval`.
- 10.1 §6.1: deprecate `actor_display_name`; pre-auth, accept it but tag the resulting decision with `decided_by_label_unverified=true`.

**Patch plan 3: Audit trust boundary**

- 10.3 §5.5: rename to "Application-level append-only guarantees." Add trust-boundary subsection. List minimal v1 controls (DB role, admin, backups). Add forward-pointer for hash-chain / external archive.
- 10.7 §5.4: change `decided_by` and `actor_user` FKs to `SET_NULL`; rely on `actor_label` snapshot. Add user-deletion test.

**Patch plan 4: Artifact controls and ordering**

- 10.4 §6.5: make total per-execution bytes mandatory; add `ARTIFACT_DAILY_BYTES_PER_RUNNER` global ceiling.
- 10.4 §5.5 (new): document canonical storage→DB→audit ordering. Remove conflicting language from §13.

**Patch plan 5: Integrations (sync, budget, audit-vs-dispatch ordering)**

- 10.5 §7.5: define `INTEGRATION_DISPATCH_BUDGET_SECONDS` and `INTEGRATION_MAX_PER_TRIGGER`. Use `httpx.Client` consistently. Update 10.9 §6.1 timeout table to match.
- 10.5 §7.4: add worked example showing `with transaction.atomic():` containing audit emission + `transaction.on_commit(...)` for dispatch.
- 10.3 §8.2: add cross-reference: "External-effect dispatchers must be scheduled via `transaction.on_commit`; audit emission stays in-transaction."
- 10.5 §9.2: add IP pinning recommendation; 10.10 §5: document egress proxy posture.

**Patch plan 6: AI parsing safety and consistency**

- 10.6 §11: add `AI_PARSE_REQUIRES_PRIVATE_ENV`, `AI_PARSE_DAILY_BUDGET_USD`.
- 10.6 cache key: include model, prompt version, schema version, org_id (post-auth); add LRU bound.
- 10.6 default `AI_PARSE_MODEL` to a pinned dated alias.
- 10.6 §6.5: split `AI_SUMMARIZE_TIMEOUT_SECONDS` from `AI_READ_TIMEOUT_SECONDS`; default summarize disabled (`AI_SUMMARIZE_ENABLED=False`).
- 10.6 §6.3: schedule summarize via `transaction.on_commit`.

**Patch plan 7: Auth migration and internal contract**

- 10.7 add preflight gate for fresh-DB requirement.
- 10.7 §6.3 vs §9.3: pick one auth contract for internal endpoints. Recommend updating §6.3 to "401 for any non-runner Bearer; 401 for missing token; 200 only for valid runner token" and explaining in runner client error handling that 401 on internal means "exit immediately."
- 10.7 §6.4: require `X-Organization-Id` and any body `organization_id` to match.

**Patch plan 8: Streaming production viability**

- 10.8 §6.2: replace `asyncio.get_running_loop()`-based emit with a captured-loop pattern; add integration test for sync-service → SSE-subscriber.
- 10.8 §11 / 10.10 §5: drop "sticky sessions" suggestion. Add 10.10 release gate: "Live streaming enabled only with API task count = 1 (documented availability tradeoff) or with externalized event transport."
- 10.8 §8.4: match steps by `step_id` not `position`.

**Patch plan 9: Hardening and AWS boundary**

- 10.9 §6.4 / 10.10 §5: split health endpoints; ALB uses `/health/ready/`.
- 10.9 §4: add `django-csp` to requirements; register middleware; add response-header tests.
- 10.9 §5.3: production startup fails closed if metrics enabled without token.
- 10.9 §4: add `recover_expired_approvals` alongside `recover_stuck_executions`.
- 10.10 §5 ALB routing: replace "if avoidable" with mandatory private routing for `/api/v1/internal/`; add curl-based verification gate.

---

## 16. Prioritized action plan

1. Fix BLOCKERs C-B01, C-B02, C-B03, K-B06 before any 10.1/10.2 implementation prompt is issued.
2. Fix C-B04 and C-B05 before any 10.8 milestone begins, and before 10.10 promises streaming.
3. Fix C-H01, C-H02, C-H10 before any production AWS environment is exposed.
4. Fix C-H03 before audit is cited as a security control by 10.4 / 10.5.
5. Fix C-H04 before 10.7 migration milestone starts.
6. Fix C-H05 before 10.6 is enabled outside private dev/staging.
7. Fix C-H06 + K-H07 before 10.5 / 10.6 runs against real workflows.
8. Fix K-H08 before any environment that any user other than the implementer can reach.
9. Fix C-H09 before 10.9 claims browser security hardening.
10. Fix K-H11 before integrations are enabled in any AWS environment.
11. Clean up MEDIUM and LOW items during blueprint cleanup before coding the affected area.

---

## 17. Must fix before implementation

Must fix before Phase 10 implementation proceeds as a chain:

- C-B01: Policy conflict resolution.
- C-B02: Approval audit gate sequencing.
- C-B03: Runner contract for policy-driven approvals.
- K-B06: `AutoApprove`-vs-floor decision.
- C-B04: SSE sync emit no-op.
- C-B05: SSE bus vs multi-task ECS.

Must fix before the affected production deployment:

- C-H01: Private routing for `/api/v1/internal/` on AWS.
- C-H02: ALB health check decoupled from AI.
- C-H10: Metrics fail-closed in production.
- K-H11: SSRF DNS TOCTOU mitigation in 10.10.

Must fix before the affected phase implementation:

- C-H03 before 10.3.
- C-H04 before 10.7.
- C-H05 before 10.6 is enabled outside private dev.
- C-H06 + K-H07 before 10.5 / 10.6 dispatch is enabled.
- K-H08 before any environment is shared with non-implementers.
- C-H09 before 10.9 claims browser hardening.

---

## 18. Safe to defer

These can be deferred if tracked and not blocking the affected implementation:

- Tamper-evident audit storage (hash chains, WORM archive) — defer past 10.3 as long as the v1 blueprint says "application-level append-only" and does not overstate.
- Queue-backed integration dispatch — defer as long as sync dispatch has strict budget + count caps.
- Redis pub/sub (or other event transport) for SSE — defer as long as 10.8 is not claimed to work across multiple API tasks and polling fallback remains active.
- Artifact retention / lifecycle — defer past 10.4 as long as quotas exist.
- Compliance-grade tenant data preservation in auth migration — defer as long as fresh-DB is the documented gate.
- Per-org AI opt-in UI — defer to 10.7, but the kill switch and cost ceiling must land in 10.6.
- Roadmap label/filename mapping (C-L02) — defer until BLOCKERs are addressed.

---

## 19. Final readiness verdict

Phase 10 is architecturally on-track and preserves the lightweight v1 posture established by Phases 01–09. The blueprint set is **NOT READY** for Phase 10-xx implementation as a chain.

The required corrections are blueprint edits, not architectural redesigns. Once the six BLOCKERs (C-B01, C-B02, C-B03, K-B06, C-B04, C-B05) are resolved with the patch-plan edits above, Phase 10.1 implementation can begin. The HIGH and MEDIUM findings should be resolved in the affected blueprint immediately before each phase implementation prompt is issued, in the order listed in §16.

The architecture itself — Django as control plane, runner-only-to-Django, frontend-only-to-Django, advisory FastAPI, no premature queues — is sound and worth defending against future expansion temptation.
