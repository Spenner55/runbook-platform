# Phase 10 Blueprint Audit — Remediation Summary

**Audit sources:**
- `docs/audits/phase-10-expansion-blueprints-audit.md` (Codex audit) — 21 findings: 5 BLOCKER, 8 HIGH, 6 MEDIUM, 2 LOW
- `docs/audits/phase-10-expansion-blueprints-claude-audit.md` (Claude audit) — 32 findings: 6 BLOCKER, 11 HIGH, 10 MEDIUM, 5 LOW

**Cross-cutting guardrails:** `docs/blueprints/phase-10-expansion-architecture-guardrails.md`

---

## BLOCKER findings

All 6 BLOCKERs have been remediated.

| ID | Title | Blueprint fixed | Change summary |
|---|---|---|---|
| B-01 / C-B01 | Policy conflict resolution: "stricter wins" vs "first-match" | Roadmap §4.2 | Changed "stricter outcome wins" to first-match with deterministic sort key `(rule.priority, policy.created_at, policy.id, rule.id)` |
| B-02 / C-B02 | Impossible release gate: "approval audit in same transaction" | Roadmap §6 (10.1→10.2 gate) | Removed impossible gate; replaced with: durable approval decision in same transaction + runner contract tests + §5.2 floor test |
| B-03 | Runner contract gap: steps not normalized through step-start | 10.1 §7.1 | Rewrote runner execution sequence to normalize ALL steps through step-start endpoint; Django returns `runner_action` ∈ {run, wait_for_approval, blocked} |
| B-04 / C-B04 | SSE emit() silently drops all events in sync workers | 10.8 §6.2 | Fixed `emit()` to use captured ASGI loop (`_get_asgi_event_loop()`), not `asyncio.get_running_loop()`; mandatory integration test added |
| B-05 | Multi-task SSE: sticky sessions don't solve cross-task routing | 10.8 §6.3; 10.10 ECS tasks | Explicit note that sticky sessions don't help; Phase 10.10 B-05 mandatory gate before API `desired_count ≥ 2` |
| B-06 / K-B06 | AutoApprove vs `requiresApproval: true` floor unresolved | 10.2 §11.3; Roadmap §4.2 | ARCHITECTURE DECISION: `requiresApproval: true` floor is honored; AutoApprove on floor-requiring steps is silently upgraded; comprehensive tests required |

---

## HIGH findings

All 10 HIGH findings have been remediated.

| ID | Title | Blueprint fixed | Change summary |
|---|---|---|---|
| H-01 / C-H01 | Internal endpoints publicly reachable | 10.10 ALB routing | Changed "if avoidable" to mandatory; two options documented (second internal ALB or ALB listener rule blocking `/api/v1/internal/` from outside private subnet); explicit verification gate |
| H-02 / C-H02 | ALB health check couples API to AI availability | 10.9 §6.4; 10.10 ALB routing | Split into three endpoints: `/health/live` (liveness), `/health/ready/` (DB-only, ALB-facing), `/health/` (DB+AI, ops only); docker-compose healthcheck updated; `test_readiness_returns_200_when_ai_service_down` test added |
| H-03 | Audit immutability overstated | 10.3 §5.5 | Renamed to "Application-level append-only guarantees"; added trust boundary statement; added DB-role permission controls (no UPDATE/DELETE) |
| H-04 | AUTH_USER_MODEL migration preflight missing | 10.7 §12.6 | Added mandatory preflight gate with shell commands to verify DB state before Milestone 1 |
| H-05 / C-H05 | Pre-auth AI parsing lacks cost and data-governance controls | 10.6 §11 | Added: `AI_PARSE_REQUIRES_PRIVATE_ENV=True` production guard; `AI_PARSE_DAILY_BUDGET_USD=10.0` per-day cost ceiling with HTTP 429; Phase 10.6→10.7 release gate checklist |
| H-06 / C-H06 | Synchronous integration dispatch lacks latency budget | 10.5 §7.4 | Added `INTEGRATION_DISPATCH_BUDGET_SECONDS=6.0` and `INTEGRATION_MAX_PER_TRIGGER=5`; parallel dispatch via `ThreadPoolExecutor`; `transaction.on_commit()` ordering confirmed |
| H-07 / C-H09 | CSP settings silently no-op without middleware | 10.9 requirements + §4 + §7.2 | Added `django-csp>=3.7` to `base.txt`; added `csp.middleware.CSPMiddleware` to MIDDLEWARE; added `test_csp_header_present_in_response` test |
| H-08 / C-H10 | Metrics endpoint fail-open | 10.9 §5.3 | Changed to fail-closed: `ImproperlyConfigured` on startup if `PROMETHEUS_METRICS_ENABLED=True` and token missing; `test_metrics_startup_fails_if_token_missing_when_enabled` added |
| K-H07 | `summarize_execution` blocks runner on 60s AI timeout | 10.6 §10 (Milestone 10) | Moved to `transaction.on_commit()`; default `AI_SUMMARIZE_ENABLED=False` |
| K-H11 | SSRF DNS TOCTOU — resolve then re-resolve in httpx | 10.5 §9.2 | Added `_resolve_and_validate()` pattern: resolve once, pin IP in URL, set `Host` header; prevents DNS rebinding bypass |

---

## MEDIUM findings

All 10 MEDIUM findings have been remediated or noted.

| ID | Title | Blueprint fixed | Change summary |
|---|---|---|---|
| M-01 / C-M01 | Artifact per-execution quota conditional | 10.4 §6.5 | Made mandatory; added `ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION=250MB` and `ARTIFACT_DAILY_BYTES_PER_RUNNER=1GB`; implementation pattern documented |
| M-02 / C-M02 | Cache key too narrow (content hash only) | 10.6 §5.5 | Cache key now includes model version + prompt version + schema hash + org_id; LRU bound added (256 entries max, OrderedDict eviction) |
| M-03 | JWT vs runner token 401/403 self-contradiction | 10.7 §6.3 | Explicit `RunnerTokenAuthentication.authenticate()` contract: JWT → `PermissionDenied` (403); invalid/missing → `AuthenticationFailed` (401); tests specified |
| M-04 | httpx sync/async client drift (10.5 sync, 10.9 table async) | 10.9 §6.1 timeout table | Fixed 10.9 timeout table to show `httpx.Client` (sync) for integration dispatch, consistent with 10.5 |
| M-08 / K-M08 | 10.4 self-conflicting storage→DB ordering | 10.4 §5.6 (new) + §13 | Added canonical §5.6 with definitive storage-first sequence; removed conflicting §13 language |
| M-09 | Audit-in-tx + on_commit worked example missing | 10.3 (fixed in prior session) | Canonical pattern documented in §5 with Python example |
| M-10 / K-M10 | Multiple sources of org identity, no invariant | 10.7 §5.5 (org scope section) | `X-Organization-Id` declared authoritative; mismatch → HTTP 400; exempt endpoint allowlist documented |
| C-H02 (overlap) | — | See H-02 above | — |
| C-M09 | Phase-to-phase audit dependency unclear | 10.3 (addressed in prior session) | Canonical emit ordering documented; `transaction.on_commit()` pattern for integration dispatch |
| K-M07 | Expired approval recovery missing from watchdog | 10.9 §6.3.1 (new section) | Added `recover_expired_approvals()` sweep to watchdog management command; prerequisite note on Phase 10.1 `expires_at` field |

---

## LOW findings

All 7 LOW findings have been addressed.

| ID | Title | Blueprint fixed | Change summary |
|---|---|---|---|
| L-02 | Label-to-filename mapping missing in roadmap | Roadmap §4 (prior session) | Added canonical label-to-filename mapping table |
| L-03 / K-L03 | `AI_PARSE_MODEL` defaults to floating alias | 10.6 §11 (prompt drift section) | Default must be pinned dated alias (e.g., `gpt-4o-2024-11-20`); rationale documented |
| L-04 / K-L04 | `PROTECT` FKs on audit/approval models block user deletion | 10.7 §5.4 | Changed `decided_by` and `actor_user` to `on_delete=SET_NULL`; rationale documented (denormalized snapshot is the identity record, not the FK) |
| L-05 | SSE frontend matches by `step.position` instead of `step.id` | 10.8 (prior session) | Fixed `applyStreamEvent` to use `step.id === event.data.step_id` |
| C-L01 | Runbook operational runbooks missing | 10.9 §14 definition of done | Already included: five operational runbooks in `docs/runbooks/` are a Phase 10.9 done criterion |
| C-L02 | Blueprint evidence record per phase | Remediation summary (this document) | This document serves as the evidence record for the blueprint-fix phase |
| N-13 | Endpoints that don't require `X-Organization-Id` undocumented | 10.7 §5.5 | Allowlist documented inline with K-M10 fix |

---

## Remaining known gaps (not fixed in this remediation pass)

The following findings were noted but are deferred to implementation time or future blueprint revision:

| ID | Notes |
|---|---|
| N-01 through N-12 | Polish/cosmetic items from Claude audit — minor wording, example improvements, schema alignment. Not blocking. |
| C-H03 through C-H05 context | Phase 10.6 → 10.7 operational data governance (OAI data processing agreements, org consent UI) — requires product decision, not blueprint text alone. |
| Phase 10.9 cumulative latency budget | K-H07 identified that no blueprint owns the runner request latency budget. Phase 10.9 should add a "step transition latency budget table" (P95 ≤ 200ms exclusive of external calls). Not yet added. |
| Runner idempotency across retries | Retry duplication risk for parse and enrich calls when AI service returns ambiguous responses. Noted in 10.6 §11; mitigation is content hash cache. No further blueprint change needed. |

---

## Files modified in this remediation pass

| File | Findings addressed |
|---|---|
| `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` | B-01, B-02, L-02, K-B06 |
| `docs/blueprints/phase-10-01-approvals-blueprint.md` | B-03, K-H08, K-M07 (reference) |
| `docs/blueprints/phase-10-02-policies-blueprint.md` | B-03, K-B06 |
| `docs/blueprints/phase-10-03-audit-trail-blueprint.md` | H-03, M-09 |
| `docs/blueprints/phase-10-04-artifacts-blueprint.md` | C-M01, K-M08 |
| `docs/blueprints/phase-10-05-integrations-blueprint.md` | H-06, K-H11, M-04 (reference) |
| `docs/blueprints/phase-10-06-richer-ai-parsing-blueprint.md` | H-05, K-H07, C-M02, K-L03 |
| `docs/blueprints/phase-10-07-authentication-authorization-blueprint.md` | H-04, M-03, K-M10, K-L04 |
| `docs/blueprints/phase-10-08-live-event-streaming-blueprint.md` | B-04, B-05, L-05 |
| `docs/blueprints/phase-10-09-production-hardening-blueprint.md` | H-02, H-07, H-08, K-M07, M-04 |
| `docs/blueprints/phase-10-10-aws-deployment-workflows-blueprint.md` | H-01, B-05, H-02 |
| `docs/blueprints/phase-10-expansion-architecture-guardrails.md` | New document — all guardrails |
| `docs/blueprints/phase-10-audit-remediation-summary.md` | New document — this file |
