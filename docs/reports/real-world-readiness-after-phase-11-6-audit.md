# Real-World Readiness After Phase 11.6 — Repository Audit

| Field | Value |
|---|---|
| Audit date | 2026-05-05 |
| Audited report | `docs/report/real-world-readiness-after-phase-11-6.md` |
| Required output path | `docs/reports/real-world-readiness-after-phase-11-6-audit.md` |
| Repository root | `/home/dylan/code/runbook-platform` |
| Verdict | Not ready for a real pilot |

## 1. Executive Verdict

The readiness report is useful as a strategic gap analysis, but it is not accurate as a current-state implementation assessment. Its key assumption is that Phases 11.1 through 11.6 are complete, verified, and blueprint-aligned. The repository does not support that assumption.

Current implementation reality:

- Phase 11.1 is substantially implemented through `apps/api/apps/changes/`.
- Phase 11.2 is partially implemented: change windows, freeze rules, target locks, and dispatch preflight exist, but dispatch semantics drift from the blueprint.
- Phase 11.3 is not implemented as modeled in the blueprint. There are status names such as `verification_pending`, but no `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`, or closure API.
- Phase 11.4 is not implemented. Free-text freeze exception fields exist, but emergency exceptions, breakglass sessions, retro-review, and breakglass audit semantics do not.
- Phase 11.5 is not implemented. There is no sealed evidence bundle model, deterministic manifest, export package, legal hold model, or bundle sealing workflow.
- Phase 11.6 is not implemented. There is no auditor app, scoped auditor grant model, auditor workspace API/UI, service catalog, external reference snapshot model, or control coverage model.
- The runner remains simulated. `apps/runner/runner/sandbox.py` is a stub, and `apps/runner/runner/executor.py` simulates command success unless the command contains a fail marker.
- Artifact storage is local-only. `apps/api/apps/artifacts/storage.py` rejects non-local backends.
- AWS production infrastructure is explicitly not implemented. `infra/aws/README.md` says there are no live AWS resources, no IaC root, and no deployment workflow.

Pilot readiness: **Not ready**.

The highest-risk gap is not a single missing UI page. It is that the platform currently lacks a complete governed change lifecycle after approval, a real execution boundary, sealed evidence, auditor access controls, and pilot-grade operational deployment. A small real organization should not use this repository for governed production-change evidence until those are closed or explicitly scoped out of a non-production demo.

## 2. Audit Scope and Method

Scope reviewed:

- `docs/report/real-world-readiness-after-phase-11-6.md`
- `docs/blueprints/`
- `apps/api/`
- `apps/runner/`
- `apps/web/`
- `apps/ai/`
- `packages/`
- `infra/`
- `docker-compose.yml`
- `Makefile`
- `.env.example`
- `.github/workflows/`

Priority blueprint comparison:

- `docs/blueprints/phase-11.1-change-dossier-blueprint.md`
- `docs/blueprints/phase-11.2-windows-freezes-target-locks-blueprint.md`
- `docs/blueprints/phase-11.3-verification-closure-blueprint.md`
- `docs/blueprints/phase-11.4-emergency-exceptions-breakglass-blueprint.md`
- `docs/blueprints/phase-11.5-sealed-evidence-bundles-blueprint.md`
- `docs/blueprints/phase-11.6-auditor-workspace-control-coverage-blueprint.md`
- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-09-production-hardening-blueprint.md`

Method:

- Read the target report and treated its major claims as assertions to verify.
- Compared Phase 11 blueprints against concrete Django models, services, URLs, tests, runner behavior, frontend API clients, and infrastructure files.
- Classified report claims as Accurate, Partially accurate, Outdated, Missing implementation evidence, Contradicted by repository code, or Too vague to verify.
- Checked architecture invariants against code boundaries.
- Ran or attempted the requested verification commands and recorded the result.

Uncertainty:

- This audit is source-level and local-environment based. It does not include a live API walkthrough because the `api` and `runner` Docker services were not running.
- File paths are stable evidence. Line numbers are intentionally omitted in this report because the audit file may remain useful after nearby edits shift line numbers.

## 3. Report Accuracy Review

| Report claim | Classification | Repository evidence | Assessment |
|---|---|---|---|
| "Phases 11.1 through 11.6 are complete, verified, and aligned with their blueprints" | Contradicted by repository code | `apps/api/config/settings/base.py`, `apps/api/config/api_v1_urls.py`, `apps/api/apps/changes/models.py`, `apps/api/apps/changes/urls.py` | Only the `changes` app is registered for Phase 11 work. There are no verification, emergency, evidence, auditor, service catalog, external reference, or control coverage apps/routes/models. |
| The platform would model production changes, freeze windows, target locks, approvals, policy gates, verification, emergency exceptions, sealed evidence bundles, auditor search, external references, and control coverage | Partially accurate as a hypothetical, inaccurate as repo state | `apps/api/apps/changes/models.py`, `apps/api/apps/changes/services.py`, missing apps under `apps/api/apps/` | Change records, windows, freezes, locks, approvals, and policy linkage exist. Verification, emergency exceptions, sealed bundles, auditor search, external references, and control coverage are not implemented. |
| Runner still simulates work | Accurate | `apps/runner/runner/sandbox.py`, `apps/runner/runner/executor.py` | `Sandbox` is empty. `_execute_command()` checks for a fail marker, sleeps, uploads synthetic output, and marks terminal status. |
| Phase 11.6 does not solve real command execution, credentials, real targets, or operational failures | Accurate | `apps/runner/runner/`, `apps/api/apps/artifacts/storage.py`, `infra/aws/README.md` | These concerns are outside implemented Phase 11 code and remain real blockers. |
| Django is the control plane and owns persistence, orchestration, validation, state transitions, audit, and API contracts | Accurate with gaps | `apps/api/apps/*/services.py`, `apps/api/config/api_v1_urls.py` | The architecture is mostly preserved. Some service gates are permissive by default and not pilot-safe, but the boundary is correct. |
| Runner talks only to Django internal APIs | Accurate | `apps/runner/runner/client.py`, `apps/api/apps/executions/internal_views.py`, `apps/api/apps/changes/urls.py` | Runner client uses Django internal endpoints. No direct database or AI access was found in the runner. |
| React talks only to Django public APIs | Accurate | `apps/web/src/shared/api/client.ts`, `apps/web/src/features/changes/api/changesApi.ts` | The API client blocks internal API paths and uses Django routes. No direct AI or runner calls were found. |
| AI service is advisory and stateless | Accurate with one config caveat | `apps/ai/app/services/workflow_parser.py`, `apps/ai/app/core/config.py`, `apps/api/apps/workflows/services.py` | AI does not persist state. Django validates and persists. Caveat: if LLM parsing is enabled, `workflow_parser.py` defaults to `gpt-4o` when `AI_PARSE_MODEL` is empty. |
| Approvals, policies, audit, artifacts, integrations, auth, live execution streaming, and a substantial changes app are present | Accurate, but scope-sensitive | `apps/api/apps/approvals/`, `apps/api/apps/policies/`, `apps/api/apps/audit/`, `apps/api/apps/artifacts/`, `apps/api/apps/integrations/`, `apps/api/apps/users/`, `apps/api/apps/executions/`, `apps/api/apps/changes/` | These apps exist. Their presence should not be read as complete enterprise capability. Authorization remains coarse, artifact storage is local-only, and change lifecycle after execution is incomplete. |
| Production hardening exists in code and documentation | Partially accurate | `apps/api/config/settings/prod.py`, `.github/workflows/ci.yml`, `Makefile`, `docker-compose.yml` | There is meaningful hardening and CI scaffolding. However, local config drift exists, AWS deployment is absent, and production assumptions remain unvalidated locally. |
| Artifact storage is local-only | Accurate | `apps/api/apps/artifacts/storage.py`, `apps/api/apps/artifacts/views.py`, `apps/api/apps/artifacts/services.py` | The storage class raises for any backend other than `local`. Downloads stream local files through Django. |
| AWS infrastructure is not scaffolded | Accurate | `infra/aws/README.md` | The README explicitly states there are no live resources, no Terraform/CDK/Pulumi root, and no deployment workflow. |
| Default AI parser is deterministic and mostly creates manual tasks | Accurate | `apps/ai/app/services/workflow_parser.py`, `apps/ai/app/core/config.py` | `AI_USE_LLM_PARSER` defaults false. Deterministic parsing creates `manual_task` steps from numbered text. |
| Workflow schema is thin | Accurate | `packages/workflow-schema/workflow.schema.json` | Schema is minimal: workflow name and step list with basic step fields. |
| Report's recommended gaps are enough to guide implementation | Partially accurate | `docs/report/real-world-readiness-after-phase-11-6.md` | It identifies real production gaps, but it under-separates current blockers from post-Phase-11 hypothetical gaps and is not granular enough for coding agents. |
| Report distinguishes pilot blockers from production enhancements | Partially accurate | `docs/report/real-world-readiness-after-phase-11-6.md` | The report discusses major gaps, but it does not rigorously classify blockers, controlled pilot limitations, and future production work against current code. |

## 4. Repository Implementation Reality

### Current Implemented Foundations

- Organization-scoped auth exists through JWT and `X-Organization-Id`.
  Evidence: `apps/api/apps/common/org_context.py`, `apps/api/apps/common/permissions.py`, `apps/api/apps/users/models.py`.
- Public and internal API separation exists.
  Evidence: `apps/api/config/api_v1_urls.py`, `apps/api/apps/executions/internal_views.py`, `apps/api/apps/changes/urls.py`.
- Runner authentication for internal endpoints exists.
  Evidence: `apps/api/apps/common/authentication.py`, `apps/api/apps/common/permissions.py`.
- Approval and policy apps exist and are wired into execution/change paths.
  Evidence: `apps/api/apps/approvals/`, `apps/api/apps/policies/`, `apps/api/apps/executions/internal_views.py`, `apps/api/apps/changes/services.py`.
- Audit event append-only behavior exists at the Django model/service layer.
  Evidence: `apps/api/apps/audit/models.py`, `apps/api/apps/audit/services.py`.
- Artifact upload/download scaffolding exists for local storage.
  Evidence: `apps/api/apps/artifacts/models.py`, `apps/api/apps/artifacts/services.py`, `apps/api/apps/artifacts/storage.py`, `apps/api/apps/artifacts/views.py`.
- Change dossier, operation profile, production targets, execution binding, windows, freeze rules, target locks, and dispatch eligibility checks exist.
  Evidence: `apps/api/apps/changes/models.py`, `apps/api/apps/changes/services.py`, `apps/api/apps/changes/tests/`.
- Frontend can create, list, view, and submit changes.
  Evidence: `apps/web/src/features/changes/api/changesApi.ts`, `apps/web/src/routes/changes/ChangeCreatePage.tsx`, `apps/web/src/routes/changes/ChangeDetailPage.tsx`.

### Current Partial or Unsafe Areas

- Dispatch is not a user-visible explicit action. Approval/submission can make a change dispatchable and create an execution reservation automatically.
  Evidence: `apps/api/apps/changes/services.py`, `apps/api/apps/changes/urls.py`.
- Dispatch preflight can pass with no policy evaluation linked.
  Evidence: `apps/api/apps/changes/services.py`, `apps/api/apps/changes/tests/test_preflight_service.py`.
- Dispatch preflight can pass with no change window.
  Evidence: `apps/api/apps/changes/services.py`, `apps/api/apps/changes/tests/test_preflight_service.py`.
- Freeze exceptions are free-text fields on `ChangeRecord`, not typed exception records with approval or retro-review.
  Evidence: `apps/api/apps/changes/models.py`, `apps/api/apps/changes/services.py`.
- Change completion with verification required transitions to `verification_pending`, but no verification workflow exists.
  Evidence: `apps/api/apps/changes/services.py`, `apps/api/apps/changes/models.py`.
- Authorization is organization-role based and coarse.
  Evidence: `apps/api/apps/common/permissions.py`, `apps/api/apps/approvals/views.py`.
- `.env.example`, `docker-compose.yml`, and `Makefile` do not consistently document/pass `CHANGE_DISPATCH_TOKEN_SECRET`.
  Evidence: `.env.example`, `docker-compose.yml`, `Makefile`, `apps/api/config/settings/base.py`, `apps/api/config/settings/prod.py`.

### Current Missing Phase 11 Surface

- No verification app or closure models/routes.
- No emergency exception app, breakglass session, or retro-review model/routes.
- No evidence bundle app, sealed manifest, export, retention, or legal hold model/routes.
- No auditor workspace app or scoped read-only auditor grants.
- No service catalog, external change references, or control coverage models.
- No frontend screens for verification, breakglass, evidence bundles, auditor workspace, service catalog, or control coverage.

## 5. Pilot Readiness Assessment

| Area | Readiness | Evidence | Assessment |
|---|---|---|---|
| Authentication and authorization | Partial | `apps/api/apps/users/`, `apps/api/apps/common/permissions.py` | Auth exists, but roles are coarse. No SSO, SCIM, scoped service accounts, fine-grained RBAC, or separation of duties. |
| Organization scoping / tenancy | Partial | `apps/api/apps/common/org_context.py`, app querysets/services | `X-Organization-Id` checks are a good base. Pilot still needs broader endpoint-by-endpoint authorization review and auditor scoping. |
| ChangeRecord lifecycle | Partial | `apps/api/apps/changes/models.py`, `apps/api/apps/changes/services.py` | Dossier lifecycle through dispatch/running exists. Verification, closure, cancellation semantics, stuck recovery after change binding, and evidence finalization are incomplete. |
| Approval and policy gates | Partial | `apps/api/apps/approvals/`, `apps/api/apps/policies/`, `apps/api/apps/changes/services.py` | Gates exist but are too permissive for pilot. No SoD; policy preflight passes when no policy evaluation is linked. |
| Change windows, freezes, target locks | Partial | `apps/api/apps/changes/models.py`, `apps/api/apps/changes/services.py` | Models and checks exist. Defaults allow no window; freeze exception is free text; no typed exception workflow. |
| Verification and closure | Not ready | `apps/api/apps/changes/models.py`, absence of verification app | Status names exist, but blueprint models and workflow are absent. |
| Emergency / breakglass controls | Not ready | `apps/api/apps/changes/models.py`, absence of breakglass app | No `ChangeException`, `BreakglassSession`, or `RetroReview`. |
| Evidence bundle sealing and export | Not ready | `apps/api/apps/artifacts/`, absence of evidence app | Artifacts exist locally; sealed evidence bundles do not. |
| Auditor workspace and scoped read-only access | Not ready | Absence of auditor app/routes/UI | No scoped external auditor access model or workspace. |
| Runner safety and execution boundaries | Not ready | `apps/runner/runner/sandbox.py`, `apps/runner/runner/executor.py` | Runner simulates execution and has no real sandbox, target access, cancellation, credential injection, or action isolation. |
| Artifact handling | Partial | `apps/api/apps/artifacts/storage.py`, `apps/api/apps/artifacts/services.py` | Local upload/download works as a scaffold. Durable object storage and evidence retention are absent. |
| Audit trail completeness | Partial | `apps/api/apps/audit/models.py`, `apps/api/apps/audit/services.py` | Append-only application audit exists for implemented objects. Missing audit object types for Phases 11.3-11.6. No WORM/tamper-evident backend. |
| Operational hardening | Partial | `apps/api/config/settings/prod.py`, `.github/workflows/ci.yml`, `Makefile` | Some prod settings and CI checks exist. Deployment, backups, restore, alerts, and production runbooks are absent. |
| Local/demo deployment readiness | Partial | `docker-compose.yml`, `.env.example` | Compose has core services, but API and runner were not running during verification and dispatch secret config is incomplete. |
| CI/testing reliability | Partial | `.github/workflows/ci.yml`, app tests | CI is relatively broad. Local Docker checks could not run because services were stopped. Phase 11.3-11.6 tests are absent because features are absent. |
| Documentation/runbooks | Partial | `docs/blueprints/`, `infra/aws/README.md`, `docs/report/` | Blueprints are strong, but operator runbooks for real pilot deployment, incident handling, onboarding, backups, and evidence export are missing. |
| Known unsafe assumptions | Not ready | `apps/runner/`, `apps/api/apps/changes/services.py`, `apps/api/apps/artifacts/storage.py` | Simulated execution, permissive dispatch defaults, local artifact storage, and incomplete lifecycle controls are unsafe for real production-change evidence. |

## 6. Blocking Pilot Gaps

The following must be fixed before a real organization uses the platform for governed production-change evidence.

1. **Phase 11.3 through 11.6 implementation is missing.**
   The report assumes these phases are complete, but the repository lacks the models, APIs, UI, and tests for verification/closure, emergency exceptions, sealed evidence bundles, and auditor workspace.

2. **Runner execution is simulated and not sandboxed.**
   A real pilot cannot treat synthetic step success as production evidence. There is no real command execution boundary, no resource limits, no target credential model, and no hard kill/cancel semantics.

3. **Dispatch gates are too permissive and drift from Phase 11.2.**
   The blueprint expects explicit, preflighted dispatch. The code can create execution reservations automatically from submit/approval and allows no-policy/no-window cases to pass.

4. **Verification and closure are not implemented.**
   The system can place a change into `verification_pending`, but it has no controlled verification plan/result/closure workflow.

5. **Emergency and breakglass controls are not implemented.**
   Free-text freeze exceptions are not equivalent to emergency exceptions, breakglass sessions, typed approvals, or retro-review.

6. **Evidence bundles are mutable/nonexistent as sealed governance artifacts.**
   Local artifacts can be uploaded, but there is no sealed manifest, export, retention lock, legal hold, or auditor-ready evidence package.

7. **Auditor workspace and scoped read-only access are absent.**
   There is no way to grant an external or internal auditor a bounded read-only evidence scope.

8. **Authorization is too coarse for governed production changes.**
   There is no separation of duties, verifier role, dispatcher permission, emergency authority, auditor role, or scoped service account model.

9. **Artifact storage is local-only.**
   Local filesystem storage is not durable, not independently retained, and not suitable as production evidence storage.

10. **Production deployment architecture is absent.**
    There is no AWS/IaC/deployment workflow, backup/restore design, monitoring, alerting, or migration procedure for pilot operations.

11. **Configuration drift can break local/prod safety gates.**
    `CHANGE_DISPATCH_TOKEN_SECRET` is required by production settings and by dispatch token generation, but is not consistently documented or passed by local compose/Makefile paths.

12. **Stuck execution and change recovery is incomplete for real operations.**
    Execution recovery scaffolding exists, but real runner disappearance, stuck verification, stuck dispatchable changes, and operator repair flows are not pilot-ready.

## 7. Controlled Pilot Limitations

These are not necessarily blockers if the pilot is explicitly constrained, but they must be documented in the pilot agreement and operator runbooks.

- No SSO/SAML/OIDC enterprise identity. Local user/JWT auth only.
- No SCIM or directory-driven onboarding. User and organization setup is manual.
- No high-availability architecture. Single-region/single-stack assumptions only.
- No multi-region, disaster recovery, or tested restore drills.
- No full observability stack. CI has checks, but pilot operations need dashboards, alerts, and incident procedures.
- Limited integration depth. Integrations exist as app scaffolding, but external ITSM/PagerDuty evidence references from Phase 11.6 are missing.
- Frontend change-management UI is partial. It supports create/list/detail/submit, not the full operational lifecycle.
- AI parsing is advisory and limited. Deterministic parsing is intentionally simple; LLM parsing is optional and still requires human review.
- Workflow/action model is thin and mostly unsuitable for precise production operations without a typed action catalog.
- Audit trail is append-only at application level, not cryptographically sealed or stored in WORM infrastructure.
- No formal support model, incident response path, customer data handling procedure, or retention policy.

## 8. Future Production Gaps

After a constrained pilot is safe, future production readiness should address:

- SOC 2 control mapping polish and formal evidence taxonomy.
- SAML/OIDC SSO, SCIM, enterprise group mapping, and service accounts.
- Fine-grained RBAC by project, service, environment, target, action type, and operation profile.
- HA deployment with database backups, point-in-time recovery, restore drills, and infrastructure rollbacks.
- Centralized observability: metrics, traces, logs, dashboards, alerts, SLOs, and support diagnostics.
- Runner fleet management: registration, pools, labels, scheduling, draining, concurrency, and customer-network install path.
- Durable artifact and evidence storage with KMS, retention locks, object lifecycle policies, and export monitoring.
- Release management: migration gates, rollout stages, rollback playbooks, and customer-visible change logs.
- Load and resilience testing for API, runner, artifact upload, SSE/live events, and evidence export.
- Formal data retention, deletion, legal hold, and customer offboarding procedures.

## 9. Blueprint Drift Analysis

| Blueprint | Expected | Repository reality | Drift |
|---|---|---|---|
| Phase 11.1 Change Dossier | Change records, operation profiles, targets, execution binding, immutable submitted dossier | Mostly implemented in `apps/api/apps/changes/` | Low to medium. The core exists, but downstream lifecycle phases are absent. |
| Phase 11.2 Windows, Freezes, Target Locks | Explicit dispatch after successful preflight; windows, freeze rules, locks; target serialization | Partially implemented in `apps/api/apps/changes/` | Medium to high. No public dispatch endpoint; auto-dispatch behavior exists; no-policy/no-window gates can pass; freeze exception is free text. |
| Phase 11.3 Verification and Closure | `VerificationPlan`, checks, results, attestations, `ChangeClosure`, controlled closure | Not implemented | High. Only status labels and transition to `verification_pending` exist. |
| Phase 11.4 Emergency Exceptions and Breakglass | `ChangeException`, `BreakglassSession`, `RetroReview`, typed emergency workflow | Not implemented | High. Current freeze exception fields explicitly are not breakglass. |
| Phase 11.5 Sealed Evidence Bundles | Evidence bundles, deterministic manifests, redaction, export packages, retention/legal hold | Not implemented | High. Artifact upload exists, but sealed evidence does not. |
| Phase 11.6 Auditor Workspace and Control Coverage | Auditor grants, auditor search/detail/export, service catalog, external references, control mapping | Not implemented | High. No auditor app/routes/UI or control coverage models. |
| Phase 10 Platform Expansion Roadmap | Runner should actually poll, claim, execute, stream logs, and handle failures before platform expansion | Runner polls and reports, but execution is simulated | High. The roadmap warned against expanding on a stub execution foundation. |
| Phase 10.9 Production Hardening | Prod settings, graceful runner shutdown, health checks, watchdog, CI hardening, no new infra | Some hardening exists | Medium. CI is broader than the blueprint's initial state, PgBouncer exists in compose, and recovery code exists; deployment and runtime validation remain incomplete. |

## 10. Architecture Invariant Review

| Invariant | Status | Evidence | Notes |
|---|---|---|---|
| Django is the control plane | Preserved | `apps/api/apps/*/services.py`, `apps/api/config/api_v1_urls.py` | Business state is centralized in Django. Missing features should continue this pattern. |
| Runner only talks to Django APIs | Preserved | `apps/runner/runner/client.py` | Runner does not access DB/AI directly. Keep this invariant when adding real execution. |
| Frontend only talks to Django APIs | Preserved | `apps/web/src/shared/api/client.ts` | Client blocks internal API paths. Missing UI should use public Django APIs only. |
| AI is stateless and advisory | Preserved | `apps/ai/app/services/workflow_parser.py`, `apps/api/apps/workflows/services.py` | Django validates and persists workflow candidates. |
| Business logic in services | Mostly preserved | `apps/api/apps/changes/services.py`, `apps/api/apps/executions/services.py`, `apps/api/apps/approvals/services.py` | Continue implementing lifecycle logic in services, not views. |
| UUIDs everywhere | Mostly preserved | `apps/api/apps/common/models.py`, domain models | No major exposed integer-ID drift found in reviewed code. |
| No secrets in audit/evidence | Partially preserved | `apps/api/apps/audit/services.py` | Audit service rejects/scrubs sensitive metadata keys. Real runner/evidence work must extend masking to stdout, stderr, artifacts, exports, and integration payloads. |
| No new infra unless justified | Preserved so far | `infra/aws/README.md`, `docker-compose.yml` | No premature event queue found. Pilot will justify durable object storage and deployment infrastructure. |

## 11. Required Fix Examples

### Gap: Current report overstates implemented Phase 11 readiness

Severity: Blocking

Current evidence:

- `docs/report/real-world-readiness-after-phase-11-6.md`
- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/changes/urls.py`

Why it matters:

The report can mislead an implementation agent or pilot sponsor into treating blueprint-only features as implemented controls. That creates false assurance around verification, breakglass, sealed evidence, and auditor access.

Required fix examples:

- Update the readiness report or add a current-state addendum that separates implemented, partial, and blueprint-only capabilities.
- Add a Phase 11 status matrix to `docs/report/` or `docs/reports/`.
- Require implementation prompts to reference current repository status before modifying code.

Acceptance criteria:

- [ ] Report states that Phase 11.3 through 11.6 are not implemented.
- [ ] Report distinguishes hypothetical post-Phase-11.6 readiness from repository reality.
- [ ] Each claimed capability links to concrete model/API/test evidence.
- [ ] Pilot blockers and controlled pilot limitations are separated.

### Gap: Dispatch semantics drift from Phase 11.2

Severity: Blocking

Current evidence:

- `apps/api/apps/changes/services.py`
- `apps/api/apps/changes/urls.py`
- `apps/api/apps/changes/tests/test_preflight_service.py`
- `docs/blueprints/phase-11.2-windows-freezes-target-locks-blueprint.md`

Why it matters:

Production change dispatch must be an explicit controlled action with a fresh gate decision. Automatic transition from submit/approval to execution reservation weakens operator intent and makes it harder to prove that a final dispatch decision occurred after all gates were known.

Required fix examples:

- Add explicit public dispatch API, for example `POST /api/v1/changes/{id}/dispatch/`.
- Require a fresh successful `DispatchEligibilityCheck` within a short TTL before dispatch.
- Stop creating execution reservations automatically from submit/approval unless the operation profile explicitly allows auto-dispatch for non-production/demo use.
- Change no-policy/no-window behavior from pass-by-default to profile-configured behavior.
- Replace free-text freeze exceptions with typed, approved exceptions or require a Phase 11.4 exception object.

Acceptance criteria:

- [ ] A submitted/approved change does not create an execution reservation unless dispatch is explicitly requested or profile policy permits auto-dispatch.
- [ ] Dispatch fails without a fresh successful preflight.
- [ ] Dispatch fails when a required policy evaluation is missing.
- [ ] Dispatch fails when a required window is missing.
- [ ] Tests cover dispatch denial for missing policy, missing window, active freeze, active lock, stale preflight, and unauthorized actor.

### Gap: Runner execution is simulated

Severity: Blocking

Current evidence:

- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/schemas.py`

Why it matters:

A real pilot depends on evidence that work actually ran against intended targets. Synthetic success is acceptable for demos, but it is unsafe as governed production-change evidence.

Required fix examples:

- Define a `SandboxProvider` interface with local-dev and container-backed implementations.
- Implement real command execution only for an explicitly allowed pilot action type.
- Capture exit code, stdout, stderr, timeout, signal, start/end time, and working directory.
- Enforce wall-clock timeout and cancellation.
- Mask secrets before logs/artifacts leave the runner.
- Fail closed for unsupported step types.
- Add a runner integration test against Django internal APIs.

Acceptance criteria:

- [ ] A pilot step executes a real process in an isolated workspace.
- [ ] Timeout and cancellation terminate the process and mark the step/execution correctly.
- [ ] Unsupported step types fail closed.
- [ ] Logs and artifacts are captured from real process output.
- [ ] Known secret values are redacted from stdout, stderr, errors, artifacts, audit metadata, and integration payloads.

### Gap: Credential and target access model is missing

Severity: Blocking

Current evidence:

- `apps/runner/runner/executor.py`
- `apps/api/apps/changes/models.py`
- `packages/workflow-schema/workflow.schema.json`

Why it matters:

Real operations require credentials and network reachability. Without a safe credential model, teams either cannot execute useful work or will leak powerful secrets through workflows, requested inputs, logs, artifacts, or audit events.

Required fix examples:

- Add secret reference fields to typed action specs, not raw secret values.
- Add per-organization/environment secret namespaces backed by a real secret manager for pilot.
- Add step-scoped injection of declared secrets only.
- Add runner target capability labels and scheduling checks.
- Add target access validation to dispatch preflight.

Acceptance criteria:

- [ ] Workflows cannot store raw secret values.
- [ ] Requested inputs cannot include secret material unless handled as secret references.
- [ ] Runner receives only scoped short-lived or referenced credentials required by the step.
- [ ] Dispatch refuses when no eligible runner/target access exists.
- [ ] Tests prove secret masking across logs, artifacts, audit events, and API errors.

### Gap: Verification and closure workflow is absent

Severity: Blocking

Current evidence:

- `apps/api/apps/changes/models.py`
- `apps/api/apps/changes/services.py`
- Missing `apps/api/apps/verification/` or equivalent models/routes
- `docs/blueprints/phase-11.3-verification-closure-blueprint.md`

Why it matters:

For governed production changes, success of execution is not enough. Operators need controlled verification, failed-verification handling, attestations, and final closure.

Required fix examples:

- Add `VerificationPlan`, `VerificationCheck`, `VerificationResult`, and `ChangeClosure` models.
- Add service methods for creating verification plans, recording results, attesting, failing verification, and closing a change.
- Add public APIs and frontend actions for verification and closure.
- Add audit object types/actions for verification and closure.
- Link verification artifacts to sealed evidence bundle inputs.

Acceptance criteria:

- [ ] A change with `verification_required=True` cannot close directly from execution success.
- [ ] Verification checks can be passed/failed with actor, timestamp, evidence references, and notes.
- [ ] Failed verification transitions to an explicit failure/remediation state.
- [ ] Closure requires required verification checks.
- [ ] Tests cover happy path, failed verification, unauthorized verifier, and double closure.

### Gap: Emergency and breakglass controls are absent

Severity: Blocking

Current evidence:

- `apps/api/apps/changes/models.py`
- `apps/api/apps/changes/services.py`
- Missing emergency/breakglass app/routes
- `docs/blueprints/phase-11.4-emergency-exceptions-breakglass-blueprint.md`

Why it matters:

Real organizations need emergency changes, but those controls must be typed, bounded, audited, and retro-reviewed. A free-text freeze exception reference is not sufficient.

Required fix examples:

- Add `ChangeException`, `BreakglassSession`, and `RetroReview` models.
- Require typed exception reason, scope, expiry, approving authority, and affected controls.
- Enforce session TTL and single-use or bounded-use semantics.
- Require retro-review before closure/evidence finalization.
- Add prominent audit events for breakglass activation and use.

Acceptance criteria:

- [ ] Breakglass cannot be used without typed scope and expiry.
- [ ] Breakglass use is visible in change detail, audit trail, and evidence bundle manifest.
- [ ] Retro-review is mandatory after emergency execution.
- [ ] Breakglass cannot silently waive verification/evidence unless the exception explicitly says so and is audited.
- [ ] Tests cover expired, over-scoped, unauthorized, and retro-review-missing cases.

### Gap: Sealed evidence bundles are absent

Severity: Blocking

Current evidence:

- `apps/api/apps/artifacts/`
- Missing evidence bundle app/routes
- `docs/blueprints/phase-11.5-sealed-evidence-bundles-blueprint.md`

Why it matters:

Auditors need deterministic, immutable, exportable evidence packages. Local mutable artifacts and regular audit rows do not provide sealed evidence.

Required fix examples:

- Add `EvidenceBundle`, manifest, bundle item, export, retention, and legal hold models.
- Generate deterministic manifests over change, execution, approvals, policy evaluations, verification, exceptions, audit events, and artifact checksums.
- Add redaction profiles for exports.
- Seal bundles with a digest and immutable state transition.
- Support export package generation and audit of export access.

Acceptance criteria:

- [ ] A sealed bundle cannot be modified in application code.
- [ ] Rebuilding the manifest from unchanged source data produces the same digest.
- [ ] Export package includes manifest, metadata, and referenced artifacts or references.
- [ ] Legal hold prevents deletion/retention cleanup.
- [ ] Tests cover tamper detection, redaction, export authorization, and legal hold.

### Gap: Auditor workspace and scoped read-only access are absent

Severity: Blocking

Current evidence:

- Missing auditor app/routes/UI
- `apps/api/config/api_v1_urls.py`
- `apps/web/src/app/router.tsx`
- `docs/blueprints/phase-11.6-auditor-workspace-control-coverage-blueprint.md`

Why it matters:

A real pilot with governed evidence needs a safe way to expose only approved evidence to auditors. Normal organization roles are too broad and not audit-specific.

Required fix examples:

- Add `AuditorAccessGrant` with scope, expiration, export permissions, and revoked state.
- Add auditor-only read APIs for search, change detail, evidence bundle detail, and export.
- Add service catalog, external reference, and control coverage models.
- Add frontend auditor workspace routes.
- Add audit events for auditor access, search, view, export, revoke, and expiry.

Acceptance criteria:

- [ ] Auditor users can access only granted organizations/projects/services/time ranges/control IDs.
- [ ] Auditor access is read-only.
- [ ] Export requires explicit grant permission.
- [ ] Grant expiry and revocation take effect immediately.
- [ ] Tests prove cross-scope data is not returned.

### Gap: Authorization and separation of duties are insufficient

Severity: Blocking

Current evidence:

- `apps/api/apps/common/permissions.py`
- `apps/api/apps/organizations/models.py`
- `apps/api/apps/approvals/views.py`
- `apps/api/apps/approvals/services.py`

Why it matters:

Governed changes require distinct powers: request, approve, dispatch, verify, close, breakglass, retro-review, export, and administer. The current owner/admin/operator/viewer model cannot enforce those distinctions.

Required fix examples:

- Add capability checks or scoped role assignments for requester, approver, dispatcher, verifier, closer, breakglass operator, retro-reviewer, auditor, and export operator.
- Add separation-of-duties policies, especially requester cannot approve, dispatcher cannot verify, breakglass activator cannot retro-review.
- Add service-level permission helpers and tests around each state transition.
- Add audit events for denied privileged actions.

Acceptance criteria:

- [ ] A user cannot approve their own change when SoD is enabled.
- [ ] Dispatch requires explicit dispatch permission.
- [ ] Verification and closure require separate permissions.
- [ ] Breakglass activation and retro-review require distinct permissions.
- [ ] Auditor grants do not imply operator permissions.

### Gap: Durable artifact storage is absent

Severity: Blocking

Current evidence:

- `apps/api/apps/artifacts/storage.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/artifacts/views.py`
- `.env.example`

Why it matters:

Local filesystem artifacts are not durable evidence. They are vulnerable to container replacement, disk cleanup, partial backup coverage, and local operator tampering.

Required fix examples:

- Implement S3 or equivalent object storage backend.
- Add KMS encryption, bucket policy, object ownership, and lifecycle configuration.
- Add checksum verification on upload/download.
- Add retention and legal-hold integration for evidence-related artifacts.
- Add migration path from local dev storage to pilot storage.

Acceptance criteria:

- [ ] Pilot environment stores artifacts outside containers/ephemeral disks.
- [ ] Artifact bytes are checksum-verified.
- [ ] Download access is authorized and audited.
- [ ] Deletion is blocked for held/sealed evidence artifacts.
- [ ] Tests cover object backend upload/download and authorization failures.

### Gap: Production deployment and operations are absent

Severity: Blocking

Current evidence:

- `infra/aws/README.md`
- `docker-compose.yml`
- `.github/workflows/ci.yml`
- `Makefile`

Why it matters:

A pilot needs a repeatable environment with backups, deploy/rollback, secrets, monitoring, incident response, and clear ownership. Local compose is not a pilot operating model.

Required fix examples:

- Add IaC for the chosen pilot environment.
- Add staged deployment workflows with migration checks and manual approval.
- Add database backup/restore runbook and restore test.
- Add health checks, metrics, alerts, and log retention.
- Add runner deployment model and private network path.
- Add incident runbooks for stuck execution, failed dispatch, artifact upload failure, evidence export failure, and breakglass abuse.

Acceptance criteria:

- [ ] A new pilot environment can be created from documented steps.
- [ ] Secrets are not stored in git or compose files.
- [ ] Deploy and rollback are tested.
- [ ] Backup restore is tested.
- [ ] Alerts exist for API down, runner offline, stuck executions, failed artifact writes, and evidence seal/export failures.

### Gap: Local and production config drift

Severity: Blocking

Current evidence:

- `.env.example`
- `docker-compose.yml`
- `Makefile`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/prod.py`

Why it matters:

Dispatch token generation rejects insecure/missing secrets. If local/demo paths omit `CHANGE_DISPATCH_TOKEN_SECRET`, operators may see confusing failures or bypass real dispatch verification in ad hoc ways.

Required fix examples:

- Document `CHANGE_DISPATCH_TOKEN_SECRET` in `.env.example`.
- Pass it through `docker-compose.yml` for API.
- Include it in `Makefile` production check commands.
- Add startup/system check that detects insecure defaults outside dev/test.

Acceptance criteria:

- [ ] `docker compose exec api python manage.py check` passes with documented env.
- [ ] `make check-prod` passes with required non-placeholder secrets.
- [ ] Dispatch tests fail if the secret is placeholder/insecure.
- [ ] No production path uses the base insecure fallback.

## 12. Recommended Pilot-Readiness Implementation Sequence

### Phase 0: Reconcile Current-State Documentation

Goal:

Make the repository's readiness status impossible to misread.

Scope:

- Update readiness documentation to separate implemented, partial, and blueprint-only capabilities.
- Add a Phase 11 implementation matrix.
- Define the exact controlled pilot target: production evidence only, non-production execution, or real production execution.

Files touched:

- `docs/report/real-world-readiness-after-phase-11-6.md`
- `docs/reports/`
- `docs/blueprints/`

Drift risks:

- Documentation may continue to describe ideal Phase 11 rather than current code.
- Agents may implement production runner work before governance blockers are closed.

Verification steps:

- Read report against registered Django apps/routes.
- Confirm every "implemented" claim has code/test evidence.

Exit criteria:

- Stakeholders can identify exactly what exists today and what must be built before pilot.

### Phase 1: Close Dispatch and Authorization Safety Gaps

Goal:

Prevent unintended or weakly authorized production dispatch.

Scope:

- Add explicit dispatch semantics.
- Harden preflight defaults.
- Add dispatch permission and SoD checks.
- Fix dispatch secret config drift.

Files touched:

- `apps/api/apps/changes/models.py`
- `apps/api/apps/changes/services.py`
- `apps/api/apps/changes/views.py`
- `apps/api/apps/changes/urls.py`
- `apps/api/apps/changes/tests/`
- `apps/api/apps/common/permissions.py`
- `.env.example`
- `docker-compose.yml`
- `Makefile`

Drift risks:

- Existing tests encode pass-by-default behavior for missing windows/policies.
- Frontend may assume submit is enough to progress a change.

Verification steps:

- API tests for explicit dispatch.
- Negative tests for missing policy, missing window, stale preflight, active freeze, active lock, unauthorized actor, and SoD failure.
- `docker compose exec api python manage.py check`
- `docker compose exec api pytest`

Exit criteria:

- No production change can reach runner reservation without explicit, authorized, fresh dispatch.

### Phase 2: Implement Pilot-Grade Execution Boundary

Goal:

Replace simulated execution with a narrowly scoped real execution path suitable for pilot constraints.

Scope:

- Add sandbox provider abstraction.
- Implement one conservative pilot action type.
- Add real process result envelope and secret masking.
- Add runner timeout/cancel semantics.
- Add runner pool/target capability minimum viable model if real targets are included.

Files touched:

- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/schemas.py`
- `apps/api/apps/executions/`
- `apps/api/apps/changes/`
- `packages/workflow-schema/workflow.schema.json`

Drift risks:

- Accidental broad `shell_command` support can create a large unsafe blast radius.
- Secret masking must be shared between runner output, artifacts, and audit metadata.

Verification steps:

- Runner unit tests for timeout, cancellation, unsupported step type, failed exit code, stdout/stderr capture, and secret masking.
- API integration tests for runner callbacks.
- Manual smoke test in a non-production target.

Exit criteria:

- The pilot action executes real work in a bounded environment and produces trustworthy result data.

### Phase 3: Implement Verification and Closure

Goal:

Make successful execution insufficient for closure unless required verification passes.

Scope:

- Add verification and closure models/services/APIs/UI.
- Add verifier permissions and SoD.
- Add audit events and evidence inputs.

Files touched:

- `apps/api/apps/changes/`
- New or existing verification app under `apps/api/apps/`
- `apps/api/apps/audit/`
- `apps/web/src/features/changes/`
- `apps/web/src/routes/changes/`

Drift risks:

- Treating verification as a text note rather than structured checks.
- Allowing the same actor to request, approve, verify, and close.

Verification steps:

- Tests for verification required, failed verification, closure denial, double closure, unauthorized verifier, and audit events.
- Frontend flow test for recording verification and closure.

Exit criteria:

- Change closure is controlled, auditable, and cannot bypass required verification.

### Phase 4: Implement Emergency Exceptions and Breakglass

Goal:

Support exceptional operations without hiding governance bypass.

Scope:

- Add exception, breakglass session, and retro-review models/services/APIs/UI.
- Replace free-text freeze exception bypass with typed exception references.
- Add mandatory retro-review and evidence visibility.

Files touched:

- `apps/api/apps/changes/`
- New emergency/breakglass app under `apps/api/apps/`
- `apps/api/apps/audit/`
- `apps/web/src/`

Drift risks:

- Breakglass can become a generic bypass if scope/expiry/retro-review are weak.
- Evidence bundles must prominently expose emergency status.

Verification steps:

- Tests for expired session, over-scoped session, missing retro-review, unauthorized activation, and audited use.

Exit criteria:

- Emergency execution is possible only through typed, bounded, audited controls with mandatory review.

### Phase 5: Implement Durable Artifacts and Sealed Evidence Bundles

Goal:

Create auditor-ready immutable evidence packages.

Scope:

- Add object storage backend.
- Add evidence bundle models, deterministic manifest, sealing, export, retention, legal hold, and redaction.
- Link artifacts, audit events, approvals, policies, verification, breakglass, and external references.

Files touched:

- `apps/api/apps/artifacts/`
- New evidence app under `apps/api/apps/`
- `apps/api/apps/audit/`
- `apps/api/apps/changes/`
- `infra/`
- `.env.example`

Drift risks:

- Export package may expose secrets if redaction is not centralized.
- Bundle sealing must be deterministic and immutable.

Verification steps:

- Tests for digest stability, tamper detection, export authorization, redaction, legal hold, and object-storage failure handling.

Exit criteria:

- A closed pilot change can produce a sealed, exportable evidence bundle with durable artifact references.

### Phase 6: Implement Auditor Workspace and Control Coverage

Goal:

Allow scoped read-only evidence access without granting operator privileges.

Scope:

- Add auditor grants, auditor API, auditor UI, service catalog, external references, and control coverage.
- Add export permissions and access audit.

Files touched:

- New auditor app under `apps/api/apps/`
- `apps/api/config/api_v1_urls.py`
- `apps/web/src/app/router.tsx`
- `apps/web/src/`
- `apps/api/apps/audit/`

Drift risks:

- Auditor APIs may accidentally reuse broad organization member permissions.
- Search endpoints are common cross-tenant leakage points.

Verification steps:

- Cross-tenant and cross-scope negative tests.
- Expired/revoked grant tests.
- Export permission tests.

Exit criteria:

- Auditors can search/view/export only explicitly granted evidence scopes.

### Phase 7: Pilot Deployment and Operations

Goal:

Run the platform in a repeatable controlled environment.

Scope:

- Add pilot IaC/deployment path.
- Add secrets, backups, restore, monitoring, alerts, migration gates, incident runbooks, and support procedures.
- Add runner deployment and private network design.

Files touched:

- `infra/`
- `.github/workflows/`
- `docker-compose.yml`
- `.env.example`
- `docs/runbooks/` or equivalent docs path
- `Makefile`

Drift risks:

- Adding infrastructure before app safety gates are closed can create false production readiness.
- Long-lived cloud credentials in CI would violate pilot security posture.

Verification steps:

- Fresh environment build.
- Deploy/rollback drill.
- Backup/restore drill.
- Runner offline/stuck execution drill.
- Evidence export drill.

Exit criteria:

- A pilot environment can be provisioned, operated, monitored, restored, and retired from documented steps.

## 13. Verification Plan

Requested verification commands and current result:

| Command | Result | Notes |
|---|---|---|
| `docker compose exec api python manage.py check` | Not runnable | Docker returned `service "api" is not running`. |
| `docker compose exec api pytest` | Not runnable | Docker returned `service "api" is not running`. |
| `docker compose exec runner pytest` | Not runnable | Docker returned `service "runner" is not running`. |
| `cd apps/web && npm run lint` | Passed | ESLint completed with exit code 0. |
| `cd apps/web && npm run build` | Passed | TypeScript/Vite production build completed successfully. |

Local Docker status during audit:

- Running: `ai`, `pgbouncer`, `postgres`
- Not running: `api`, `runner`

Minimum verification suite before a real pilot:

- `docker compose exec api python manage.py check`
- `docker compose exec api python manage.py check --deploy` with production settings and non-placeholder secrets
- `docker compose exec api pytest`
- `docker compose exec runner pytest`
- `cd apps/web && npm run lint`
- `cd apps/web && npm run build`
- API cross-tenant authorization tests for every change/evidence/auditor endpoint
- Runner integration tests for real pilot action execution
- Dispatch gate negative tests
- Verification/closure lifecycle tests
- Breakglass and retro-review lifecycle tests
- Evidence bundle digest/export/redaction/legal-hold tests
- Auditor grant scope and revocation tests
- Object storage upload/download/retention tests
- Backup/restore drill
- Stuck execution recovery drill
- Runner offline/drain/requeue drill
- Evidence export drill with an auditor account

## 14. Final Recommendation

Do not start a real pilot yet.

The repository is a strong control-plane prototype with meaningful Phase 10 foundations and a substantial Phase 11.1/11.2 start. It is not yet a safe governed production-change evidence platform. The current report should be revised or paired with this audit before it is used as implementation guidance.

The minimum highest-leverage next step is to **close the dispatch/control-plane drift and produce an explicit Phase 11 implementation status matrix**. That creates the safety boundary and planning clarity needed before implementing the larger runner, verification, evidence, and auditor work.

## Final Verdict

Pilot readiness: **Not ready**

Reason:

The repository lacks implemented Phase 11.3-11.6 controls, uses simulated runner execution, has permissive dispatch defaults, stores artifacts locally, lacks auditor/evidence/breakglass workflows, and has no pilot deployment architecture.

Minimum required next step:

Implement explicit, preflighted, authorized dispatch semantics and publish a current-state Phase 11 implementation matrix so future work starts from accurate repository reality.
