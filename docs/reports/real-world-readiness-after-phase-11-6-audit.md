# Real-World Readiness After Phase 11.6 — Repository Audit

| Field | Value |
|---|---|
| Audit date | 2026-05-05 |
| Audited report | `docs/report/real-world-readiness-after-phase-11-6.md` |
| Output location | `docs/reports/real-world-readiness-after-phase-11-6-audit.md` |
| Verdict | Not ready for a real pilot |

## 1. Executive Verdict

The report is directionally honest about the platform's largest real-world gaps, especially simulated runner execution, local-only artifact storage, missing deployment infrastructure, missing credentials, and enterprise-readiness limitations. However, it is not accurate as a current-state readiness report because it relies on the explicit assumption that Phases 11.1 through 11.6 are complete. The repository does not satisfy that assumption.

The implementation reality is:

- Phase 11.1 is substantially implemented through the `changes` app.
- Phase 11.2 is partially implemented in backend models and services, but has important drift from the blueprint around explicit dispatch, mandatory windows, policy gates, freeze exceptions, and UI support.
- Phase 11.3, Phase 11.4, Phase 11.5, and Phase 11.6 are not implemented as product surfaces. They remain blueprint-only except for status names, small placeholders, or unrelated scaffolding.
- The runner still simulates execution. It does not execute real production operations.
- Artifact storage is local-only.
- AWS/deployment infrastructure is explicitly not implemented.
- Authorization is organization-scoped but coarse; it lacks pilot-grade separation of duties, scoped auditor access, runner pools, project/service/environment scoping, and enterprise identity.

Final pilot readiness: **Not ready**.

A real organization should not use the current repository for governed production-change evidence except as a non-production demo of control-plane concepts. The minimum required next step is an end-to-end pilot vertical slice for one narrowly scoped operation: explicit dispatch gates, real sandboxed execution, secret/target access, verification closure, sealed evidence, and read-only auditor access.

## 2. Audit Scope and Method

This audit prioritized the requested files and directories:

- `docs/report/real-world-readiness-after-phase-11-6.md`
- `docs/blueprints/phase-11.1-change-dossier-blueprint.md`
- `docs/blueprints/phase-11.2-windows-freezes-target-locks-blueprint.md`
- `docs/blueprints/phase-11.3-verification-closure-blueprint.md`
- `docs/blueprints/phase-11.4-emergency-exceptions-breakglass-blueprint.md`
- `docs/blueprints/phase-11.5-sealed-evidence-bundles-blueprint.md`
- `docs/blueprints/phase-11.6-auditor-workspace-control-coverage-blueprint.md`
- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-09-production-hardening-blueprint.md`
- `apps/api/`, `apps/runner/`, `apps/web/`, `apps/ai/`, `packages/`, `infra/`
- `docker-compose.yml`, `Makefile`, `.env.example`, `.github/workflows/`

The review method was:

- Read the audited report first and treated its Phase 11.6 completion statement as a claim requiring validation.
- Compared Phase 11.x blueprint nouns and flows against actual Django apps, models, services, URLs, serializers, tests, frontend API clients, runner behavior, and package schemas.
- Used repository searches for expected Phase 11.3-11.6 implementation objects such as `VerificationPlan`, `ChangeException`, `BreakglassSession`, `EvidenceBundle`, `AuditorAccessGrant`, `ControlMappingProfile`, and `ChangeControlCoverage`.
- Inspected runner execution paths to determine whether the platform executes real commands or simulated work.
- Inspected artifact storage and infrastructure paths for production deployment and evidence durability.
- Ran or attempted the requested verification commands where possible.

`docs/reports/` already exists, so this report uses the requested output path. No fallback to `docs/report/` was needed.

## 3. Report Accuracy Review

| Report claim | Classification | Evidence | Audit finding |
|---|---|---|---|
| The report's key assumption is that Phases 11.1 through 11.6 are complete, verified, and aligned with blueprints. | Contradicted by repository code | `docs/report/real-world-readiness-after-phase-11-6.md:5-8`, `apps/api/config/settings/base.py:25-49`, `apps/api/config/api_v1_urls.py:44-67` | The repo registers `apps.changes` but no `apps.evidence`, `apps.auditor`, or separate emergency/verification apps. URL registration has changes/freeze rules but no evidence, auditor, verification, closure, exception, or breakglass APIs. |
| If Phase 11.6 is fully implemented, the platform would model verification, emergency exceptions, sealed bundles, auditor search, external references, and control coverage. | Missing implementation evidence | `docs/report/real-world-readiness-after-phase-11-6.md:12-16`, `apps/api/apps/` directory listing | This is valid as a hypothetical blueprint summary, but not as a current implementation statement. The corresponding code surfaces are absent. |
| The runner simulates work and `sandbox.py` is a stub. | Accurate | `docs/report/real-world-readiness-after-phase-11-6.md:16`, `apps/runner/runner/sandbox.py`, `apps/runner/runner/executor.py:316-385` | `Executor._execute_command()` checks for `FAIL_STEP`, sleeps, emits synthetic stdout/stderr, and marks the step terminal. It does not execute the step command. |
| Django is the control plane. | Accurate | `apps/api/config/api_v1_urls.py:44-67`, `apps/api/apps/changes/services.py`, `apps/api/apps/executions/services.py` | State transitions, approvals, change dispatch, execution claims, artifacts, audit, and organization scoping are controlled through Django services and APIs. |
| Runner talks only to Django internal APIs. | Accurate | `apps/runner/runner/client.py`, `apps/runner/runner/executor.py:85-103` | Runner binding, heartbeat, step start/update, approvals, completion, and artifact uploads go through Django internal endpoints. |
| React talks only to Django public APIs. | Accurate | `apps/web/src/shared/api/client.ts:9-10`, `apps/web/src/shared/api/client.ts:190-193` | The browser client explicitly blocks `/api/v1/internal/` paths and goes through the Django API client. |
| The AI service is advisory and stateless. | Accurate | `apps/ai/app/services/workflow_parser.py`, workflow parser call paths in API | The default parser is deterministic; AI parsing is not in the execution authority path. |
| Approvals, policies, audit, artifacts, integrations, authentication, live execution streaming, and a substantial `changes` app are present. | Accurate with scope caveat | `apps/api/apps/approvals/`, `apps/api/apps/policies/`, `apps/api/apps/audit/`, `apps/api/apps/artifacts/`, `apps/api/apps/integrations/`, `apps/api/apps/changes/` | These apps exist, but the `changes` app mostly covers Phase 11.1 and part of Phase 11.2. It does not implement the later governance surfaces claimed by the Phase 11.6 assumption. |
| Production hardening exists in code and documentation, while AWS deployment remains blueprint-only. | Partially accurate | `Makefile`, `.github/workflows/ci.yml`, `infra/aws/README.md:1-21` | CI and local hardening scaffolding are real, but production deployment is absent and the current local Docker API container is unhealthy. |
| Artifact storage is local-only. | Accurate | `docs/report/real-world-readiness-after-phase-11-6.md:38`, `apps/api/apps/artifacts/storage.py:23-29` | `ArtifactStorage` raises if `ARTIFACT_STORAGE_BACKEND != "local"`. S3 settings exist only as future validation/config placeholders. |
| AWS infrastructure is not scaffolded. | Accurate | `infra/aws/README.md:1-21` | The README states there are no live resources, no Terraform/CDK/Pulumi root, and no deployment workflow. |
| Workflow schema is thin. | Accurate | `packages/workflow-schema/workflow.schema.json:1-27` | The schema requires only workflow name and step `id`, `name`, `type`, and `risk`, with optional `command`, approval flag, and approval timeout. It lacks typed action specs, declared secrets, declared artifacts, target requirements, rollback semantics, and output schemas. |
| The report's real-world gap list is the correct next guidance after Phase 11.6. | Partially accurate, too optimistic | `docs/report/real-world-readiness-after-phase-11-6.md:65-220` | The listed gaps are valid, but the repo is blocked earlier than the report suggests. The first priority is not only post-Phase-11.6 execution maturity; it is also completing or intentionally narrowing Phase 11.3-11.6. |
| The report is sufficient pilot guidance. | Partially accurate but too broad | Whole report | It lists many real gaps, but does not classify current implementation blockers, blueprint drift, acceptance criteria, test requirements, or AI-agent-sized implementation slices. |

## 4. Repository Implementation Reality

The repository is a strong governed-control-plane prototype, not a pilot-ready production-change platform.

Implemented or substantially present:

- Organization context enforcement through `X-Organization-Id` in `apps/api/apps/common/org_context.py:8-25`.
- Basic organization membership roles: owner, admin, operator, viewer in `apps/api/apps/common/permissions.py:6-17`.
- Email/password user model and JWT-style auth foundations in `apps/api/apps/users/models.py:9-28`.
- Change dossier primitives: `OperationProfile`, `ChangeRecord`, `ChangeTarget`, and `ChangeExecutionBinding` in `apps/api/apps/changes/models.py`.
- Phase 11.2 backend primitives: `ChangeWindow`, `FreezeRule`, `TargetLock`, and `DispatchEligibilityCheck`.
- Backend dispatch binding from change records into execution rows in `apps/api/apps/changes/services.py:1196-1255`.
- Direct execution guard for workflows controlled by active operation profiles in `apps/api/apps/executions/services.py:71-85`.
- Runner-side change binding refusal before step execution in `apps/runner/runner/executor.py:85-103`.
- Runner-owned artifact upload through Django, not direct object storage.
- Audit metadata key rejection/scrubbing for obvious secret-bearing fields in `apps/api/apps/audit/services.py:18-56`.
- Frontend guard against browser calls to internal APIs in `apps/web/src/shared/api/client.ts:190-193`.
- Web lint and production build currently pass locally.

Not implemented or not pilot-grade:

- Phase 11.3 verification plans, checks, results, attestations, and closure workflow.
- Phase 11.4 emergency exceptions, breakglass sessions, and retro-review.
- Phase 11.5 sealed evidence bundles, immutable manifests, retention, export, and legal holds.
- Phase 11.6 auditor workspace, auditor grants, external references, service catalog, and control coverage.
- Real runner execution and sandboxing.
- Production secret brokerage and target access model.
- Runner registration records, runner pools, capability labels, environment/network scheduling, and queue isolation.
- Durable artifact/evidence storage.
- Production infrastructure, deployment workflow, backup/restore workflow, and private runner networking.
- Fine-grained RBAC, separation of duties, scoped auditor access, SSO/OIDC/SAML, SCIM, service accounts, and narrow API tokens.
- UI/API completeness for change windows, freeze exception requests, dispatch preflight review, explicit dispatch, verification, evidence bundles, and auditor search.

Current Phase 11 status:

| Phase | Blueprint intent | Repository reality |
|---|---|---|
| 11.1 Change dossier | Model governed change records, operation profiles, targets, bindings | Mostly implemented in `apps/api/apps/changes/` |
| 11.2 Windows, freezes, target locks | Gate dispatch on windows, freezes, locks, and explicit eligibility | Partially implemented in backend; important drift remains |
| 11.3 Verification and closure | Verification plans/results and controlled closure | Not implemented beyond status names such as `verification_pending` |
| 11.4 Emergency exceptions/breakglass | Exception records, breakglass sessions, retro-review | Not implemented; only free-text freeze exception fields exist |
| 11.5 Sealed evidence bundles | Immutable evidence bundles, redaction, export, retention, legal holds | Not implemented |
| 11.6 Auditor workspace/control coverage | Scoped auditor grants, evidence search, external references, service catalog, control mapping | Not implemented |

## 5. Pilot Readiness Assessment

| Domain | Readiness | Evidence | Assessment |
|---|---|---|---|
| Authentication and authorization | Partial, not pilot-grade | `apps/api/apps/users/models.py:9-28`, `apps/api/apps/common/permissions.py:6-17` | Basic auth and org roles exist. Missing SSO, fine-grained scopes, auditor role/grants, service accounts, and separation-of-duties rules. |
| Organization scoping / tenancy | Partial | `apps/api/apps/common/org_context.py:8-25`, `apps/api/apps/common/permissions.py:28-71` | Header and membership enforcement are useful. Needs broader cross-tenant negative tests for every Phase 11 endpoint and future auditor/evidence exports. |
| ChangeRecord lifecycle | Partial | `apps/api/apps/changes/models.py`, `apps/api/apps/changes/services.py` | Dossier lifecycle is meaningful through dispatch and execution binding, but verification/closure/emergency/evidence states are incomplete. |
| Approval and policy gates | Partial, blocking gaps | `apps/api/apps/approvals/views.py:61-90`, `apps/api/apps/changes/services.py:2733-2759` | Operators can decide approvals. No SoD guard. Dispatch preflight passes when no policy evaluation is linked. |
| Change windows, freezes, target locks | Partial | `apps/api/apps/changes/services.py:2762-2877`, `apps/api/apps/changes/services.py:2880-2937` | Backend checks exist, but no mandatory production window, no typed freeze exception approval, no explicit dispatch API, and limited UI. |
| Verification and closure | Not ready | `apps/api/apps/changes/services.py:2011-2022`, missing `VerificationPlan`/`VerificationResult` classes | Changes can enter `verification_pending`, but there is no implemented verification or closure workspace to move them safely forward. |
| Emergency / breakglass controls | Not ready | Missing `ChangeException`, `BreakglassSession`, `RetroReview` implementation | Emergency controls are blueprint-only. Free-text freeze exception references are not enough. |
| Evidence bundle sealing and export | Not ready | Missing `apps/api/apps/evidence/`; `apps/api/apps/artifacts/storage.py:23-29` | No sealed bundle model, immutable manifest, redaction/export flow, legal hold, or durable storage. |
| Auditor workspace and scoped read-only access | Not ready | Missing `apps/api/apps/auditor/`; no auditor role in `apps/api/apps/common/permissions.py:6-17` | No scoped external or internal auditor access model. |
| Runner safety and execution boundaries | Not ready | `apps/runner/runner/sandbox.py`, `apps/runner/runner/executor.py:316-385` | Runner execution is simulated and has no sandbox, resource controls, cancellation semantics, or target access boundary. |
| Artifact handling | Partial, not durable | `apps/api/apps/artifacts/storage.py:23-61` | Artifact services are useful scaffolding but local storage is not pilot-grade evidence storage. |
| Audit trail completeness | Partial | `apps/api/apps/audit/models.py:7-12`, `apps/api/apps/audit/models.py:23-49`, `apps/api/apps/audit/services.py:18-56` | Application-layer append-only and metadata scrubbing exist. Audit object coverage stops at Phase 11.2 objects. No tamper-evident chain or sealed evidence export. |
| Operational hardening | Partial | `Makefile`, `.github/workflows/ci.yml`, `infra/aws/README.md:1-21` | CI/hardening scaffolding exists, but production deployment and restore workflows are absent. The current API service is unhealthy in compose. |
| Local/demo deployment readiness | Partial | `docker-compose.yml`, `.env.example`, `apps/api/config/settings/base.py:210-213`, `apps/api/config/settings/prod.py:21-24`, verification results in section 13 | Current compose state cannot run API/runner verification because API is exited and runner is not running. `.env.example` and `docker-compose.yml` do not document/pass `CHANGE_DISPATCH_TOKEN_SECRET`, while production settings require it and base settings default it to an insecure placeholder. |
| CI/testing reliability | Partial | `.github/workflows/ci.yml`, local verification results | Web lint/build pass locally. Docker API/runner checks could not be executed in the current environment. No tests exist for Phase 11.3-11.6 because those surfaces are absent. |
| Documentation/runbooks | Partial | `docs/blueprints/`, `infra/aws/README.md` | Blueprints are detailed, but implementation status and pilot runbooks are not aligned with current code. |
| Known unsafe assumptions | Blocking | Report assumption, simulated runner, local storage, missing deployment | The repo cannot yet produce trustworthy evidence for real production work. |

## 6. Blocking Pilot Gaps

These must be fixed before any real pilot with an actual organization:

1. The audited report assumes Phases 11.1 through 11.6 are complete, but Phase 11.3 through Phase 11.6 are not implemented.
2. The runner does not execute real operations and has no sandbox.
3. There is no production credential, secret reference, or target access model.
4. Verification and closure are absent; changes can become `verification_pending` without a completion path.
5. Emergency exceptions and breakglass controls are absent.
6. Sealed evidence bundles and immutable exports are absent.
7. Auditor workspace and scoped read-only evidence access are absent.
8. Authorization lacks separation of duties and fine-grained scopes.
9. Dispatch gates drift from the Phase 11.2 blueprint: approval can auto-dispatch, windows and policy evaluations can pass by default, and freeze exceptions can be free-text.
10. Artifact storage is local-only and unsuitable as durable pilot evidence storage.
11. Production infrastructure and deployment workflows are absent.
12. Runner registration, runner pools, capability scheduling, and queue isolation are absent.
13. Operational recovery is incomplete for real execution: no running cancellation, no step retry/repair flow, and no pilot-grade stuck-execution runbook.
14. Local/demo verification is currently blocked because the `api` service is exited and the `runner` service is not running.

## 7. Controlled Pilot Limitations

These are not necessarily blockers if explicitly excluded from the pilot contract, but they must be documented before any controlled pilot:

- No SSO/OIDC/SAML or SCIM. The pilot would rely on local accounts.
- No high availability, multi-region deployment, or production scaling architecture.
- Manual onboarding for organizations, users, operation profiles, workflows, and targets.
- Limited frontend coverage for Phase 11.2 controls; operators cannot manage or inspect the full change-window/freeze/preflight lifecycle from the UI.
- No ServiceNow/Jira/PagerDuty external change-reference model despite blueprint intent.
- No service catalog or control coverage model.
- AI parsing is advisory and default-deterministic; it should not be marketed as reliable production workflow authoring.
- Workflow authoring is not pilot-grade for typed operational actions, rollback, dry run, declared artifacts, or declared secrets.
- Audit events are application-layer append-only, not database/WORM/tamper-evident.
- Branch protection, release management, deployment approval, backup restore, incident response, and customer support runbooks need pilot-specific evidence.

## 8. Future Production Gaps

These can come after a narrowly scoped pilot, but they are required for broader production readiness:

- Enterprise identity: SSO, SCIM, group mapping, service accounts, scoped API tokens, session/device management.
- Full observability stack: centralized logs, metrics, traces, dashboards, alerting, SLOs, error reporting, and customer-facing status.
- HA and scale: multi-AZ database, object storage lifecycle, runner autoscaling, queue backpressure, rate limits, and noisy-neighbor isolation.
- Compliance operations: SOC 2 control mapping, evidence retention policy, legal hold workflows, data export/delete workflows, audit review workflow, and compliance admin UI.
- Multi-region or customer-managed runner architecture.
- Workflow testing/promotion lifecycle: lint, dry-run, non-production promotion, rollback association, golden tests, version migration.
- Advanced action catalog: Terraform/Kubernetes/database/cloud actions with typed contracts and action-specific policy hooks.
- Support operations: admin diagnostics, impersonation controls, incident runbooks, break-fix access, customer notifications, and support audit trails.

## 9. Blueprint Drift Analysis

| Blueprint | Expected architecture | Repository alignment | Drift |
|---|---|---|---|
| Phase 10 platform expansion roadmap | Django control plane, runner only through Django APIs, frontend only public Django APIs, AI stateless/advisory, UUIDs, business logic in services, no premature infra | Mostly aligned | The core invariants are preserved. The main issue is not invariant violation; it is missing implementation required for a real pilot. |
| Phase 10.09 production hardening | Production checks, CI hardening, watchdog/recovery, structured logs, migration/security checks | Partially aligned | Makefile and CI scaffolding exist, but production deployment is absent and local API health currently fails in compose. |
| Phase 11.1 change dossier | Operation profiles, change records, targets, execution binding, immutable request snapshots | Mostly aligned | Backend implementation is substantial. Remaining pilot concerns are UI/admin completeness, SoD, profile governance, and end-to-end test coverage. |
| Phase 11.2 windows/freezes/locks | Explicit pre-dispatch eligibility, windows, freezes, target locks, dispatch refusal, auditability | Partially aligned | Backend objects and preflight checks exist. Drift: approval can call `schedule_or_make_dispatchable()` immediately, no explicit public dispatch endpoint is registered, windows pass by default when absent, policy passes by default when absent, and freeze exceptions are free-text references. |
| Phase 11.3 verification/closure | Verification plans, checks, results, attestation, controlled closure | Not aligned | Code only has status names and transition to `verification_pending`; no verification domain models, URLs, services, or UI. |
| Phase 11.4 emergency/breakglass | Exception requests, breakglass sessions, expiry, retro-review, audit | Not aligned | No emergency domain objects. `freeze_exception_reference` is not an approved exception model. |
| Phase 11.5 sealed evidence bundles | Immutable bundles, manifest, redaction, export, retention, legal holds | Not aligned | No evidence app, bundle model, seal/export workflow, legal hold, or durable storage backend. |
| Phase 11.6 auditor workspace/control coverage | Scoped auditor grants, evidence search, external references, service catalog, control coverage | Not aligned | No auditor app, auditor role/grants, external reference models, service catalog, or control mapping profile. |

The largest documentation drift is that `docs/report/real-world-readiness-after-phase-11-6.md` analyzes what would remain after Phase 11.6, but the repository is still before most of Phase 11.3-11.6.

## 10. Architecture Invariant Review

| Invariant | Status | Evidence | Risk |
|---|---|---|---|
| Django is the control plane | Preserved | `apps/api/config/api_v1_urls.py:44-67`, `apps/api/apps/changes/services.py` | Keep this invariant. Future runner/action work must not move state authority into the runner. |
| Runner only talks to Django APIs | Preserved | `apps/runner/runner/client.py`, `apps/runner/runner/executor.py:85-103` | Future real execution must still report facts to Django and never mutate platform state directly. |
| Frontend only talks to Django APIs | Preserved | `apps/web/src/shared/api/client.ts:9-10`, `apps/web/src/shared/api/client.ts:190-193` | Future auditor/evidence UI must not call runner, AI, storage, or internal APIs directly. |
| AI is stateless and advisory | Preserved | `apps/ai/app/services/workflow_parser.py` | Keep AI out of policy, approval, dispatch, verification, and evidence authority. |
| Business logic in services | Mostly preserved | `apps/api/apps/changes/services.py`, `apps/api/apps/executions/services.py`, `apps/api/apps/artifacts/services.py` | Some view-level permission checks are acceptable, but SoD and dispatch authorization need service-level enforcement too. |
| UUIDs everywhere | Mostly preserved | Core models use UUID primary keys | Continue for evidence, auditor, exception, runner, and secret-reference models. |
| No secrets in audit/evidence | Partially preserved | `apps/api/apps/audit/services.py:18-56` | Audit metadata scrubbing exists, but there is no secret model and no sealed evidence redaction pipeline. Real runner stdout/stderr can leak secrets unless masking is implemented before pilot. |
| No new infra unless justified | Preserved, but now blocks pilot | `infra/aws/README.md:1-21` | This was a good earlier invariant. A real pilot now justifies minimal deployment and storage infrastructure. |

## 11. Required Fix Examples

### Gap: Phase 11.3 through Phase 11.6 are not implemented

Severity: Blocking

Current evidence:

- `docs/report/real-world-readiness-after-phase-11-6.md:5-8`
- `apps/api/config/settings/base.py:25-49`
- `apps/api/config/api_v1_urls.py:44-67`
- Missing directories: `apps/api/apps/evidence/`, `apps/api/apps/auditor/`
- Repository search found no implementation classes for `VerificationPlan`, `VerificationResult`, `ChangeException`, `BreakglassSession`, `EvidenceBundle`, `AuditorAccessGrant`, or `ChangeControlCoverage`.

Why it matters:

The report evaluates a post-Phase-11.6 platform, but the codebase is not there. A pilot plan based on this report would overstate readiness and omit critical implementation tasks.

Required fix examples:

- Add an implementation-status matrix to the readiness report family that separates blueprint intent, implemented code, tested behavior, UI support, and pilot status.
- Complete or intentionally defer Phase 11.3-11.6 with explicit pilot exclusions.
- Add migration-backed models, services, serializers, URLs, and tests for every Phase 11 object included in the pilot scope.

Acceptance criteria:

- [ ] Every Phase 11.3-11.6 blueprint object is classified as implemented, deferred, or intentionally out of pilot scope.
- [ ] Deferred objects have documented risk and compensating controls.
- [ ] Implemented objects have model/service/API tests and cross-org negative tests.
- [ ] Readiness reports no longer rely on unvalidated assumptions.

### Gap: Real sandboxed execution is absent

Severity: Blocking

Current evidence:

- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/executor.py:316-385`
- `packages/workflow-schema/workflow.schema.json:1-27`

Why it matters:

The current runner creates evidence around simulated work. A real organization would be relying on audit records and artifacts that do not prove any production operation actually happened.

Required fix examples:

- Introduce a `SandboxProvider` interface owned by the runner.
- Implement a conservative pilot sandbox for one approved step type, with real command execution, timeout, stdout/stderr capture, exit code capture, workspace cleanup, and kill semantics.
- Add typed action specs to the workflow schema for the pilot operation instead of relying on free-form `command`.
- Fail closed on unsupported step types.
- Keep Django as the state authority; runner executes and reports facts only.

Acceptance criteria:

- [ ] A pilot step executes real work in an isolated workspace.
- [ ] Timeout, cancellation, signal handling, exit code, stdout, stderr, and artifact capture are tested.
- [ ] Unsupported action types fail before dispatch or at step start, not as silent success.
- [ ] Runner cannot bypass Django step-start, approval, artifact, binding, or completion APIs.
- [ ] Tests cover successful execution, failed execution, timeout, cancellation, and runner crash.

### Gap: Secret, credential, target access, and runner pool model is absent

Severity: Blocking

Current evidence:

- `packages/workflow-schema/workflow.schema.json:1-27`
- `apps/runner/runner/executor.py:316-385`
- `docker-compose.yml` runner configuration
- No runner registry, runner pool, secret reference, target credential, or capability scheduling models found.

Why it matters:

Real production operations need credentials and network access. Without a secret and runner-pool model, the platform either cannot perform useful work or will encourage unsafe secrets in workflows, requested inputs, logs, or artifacts.

Required fix examples:

- Add secret reference fields to typed action definitions, not raw secret values.
- Add a secret backend interface and pilot backend decision, such as AWS Secrets Manager, SSM Parameter Store, Vault, or a clearly marked local-dev backend.
- Add runner registration records in Django, with org, pool, environment, region, capabilities, last heartbeat, version, and status.
- Add dispatch scheduling constraints so production changes only go to eligible runner pools.
- Mask secret values in runner logs, stdout/stderr artifacts, exceptions, audit metadata, and integration payloads.

Acceptance criteria:

- [ ] Pilot workflows declare required secret references without storing raw secrets.
- [ ] Runner receives only step-scoped credentials.
- [ ] No raw secret appears in audit events, execution snapshots, artifacts, frontend responses, or integration payloads in tests.
- [ ] A runner from one org/pool cannot claim another org/pool's execution.
- [ ] Dispatch fails when no eligible runner is available.

### Gap: Verification and closure workflow is absent

Severity: Blocking

Current evidence:

- `apps/api/apps/changes/services.py:2011-2022`
- Missing `VerificationPlan`, `VerificationCheck`, `VerificationResult`, and `ChangeClosure` implementation.

Why it matters:

For profiles with `verification_required`, successful executions move to `verification_pending`. There is no implemented workflow to verify results, attest findings, reject closure, or close the change with evidence. A pilot would accumulate stuck governed changes or close them manually outside the system.

Required fix examples:

- Add verification plan/check/result/closure models under the Django control plane.
- Add service functions for creating verification plans from operation profiles or templates.
- Add verifier permissions and SoD enforcement so requester/approver/executor cannot automatically verify their own work where policy forbids it.
- Add closure decisions with outcome, notes, evidence references, and audit events.
- Add frontend detail views for verification and closure actions.

Acceptance criteria:

- [ ] A succeeded change requiring verification cannot close until all required checks pass or are explicitly waived through an approved path.
- [ ] Failed verification blocks closure or requires documented exception.
- [ ] Cross-org users cannot view or act on verification records.
- [ ] Every verification and closure decision emits audit events.
- [ ] Tests cover pass, fail, waiver, stale execution, and SoD denial paths.

### Gap: Emergency exceptions and breakglass controls are absent

Severity: Blocking for pilots that include emergency paths; otherwise an explicit pilot exclusion

Current evidence:

- `apps/api/apps/changes/services.py:2803-2877`
- No `ChangeException`, `BreakglassSession`, or `RetroReview` implementation.
- Current freeze exception logic only checks `change.freeze_exception_reference`.

Why it matters:

Free-text exception references are not governed exceptions. Emergency access must be time-bounded, approved or explicitly breakglass, auditable, and followed by retro-review. Otherwise operators can bypass freezes or emergency controls without enforceable evidence.

Required fix examples:

- Add `ChangeException`, `BreakglassSession`, and `RetroReview` models.
- Replace free-text freeze exception acceptance with a linked approved exception record.
- Add expiry, scope, approver/activator identity, target constraints, and mandatory retro-review.
- Add preflight checks that validate the exception record, not only the presence of a string.

Acceptance criteria:

- [ ] Dispatch during an `allow_with_exception` freeze requires a valid approved exception or active breakglass session.
- [ ] Exception scope must match organization, profile, targets, and time window.
- [ ] Expired or used-up exceptions fail closed.
- [ ] Breakglass creates mandatory retro-review before final closure.
- [ ] Tests cover exception approval, denial, expiry, scope mismatch, and retro-review enforcement.

### Gap: Sealed evidence bundles and immutable exports are absent

Severity: Blocking

Current evidence:

- Missing `apps/api/apps/evidence/`
- `apps/api/apps/artifacts/storage.py:23-29`
- `apps/api/apps/audit/models.py:23-49`

Why it matters:

A governed production-change pilot needs an evidence package that can be handed to an auditor or customer and later proven unchanged. Current audit rows and local artifacts are useful but not sealed evidence.

Required fix examples:

- Add an evidence app with bundle, bundle item, manifest, export, retention, and legal hold models.
- Generate deterministic manifests containing change, execution, approval, policy, target, lock, verification, artifact checksum, and audit-event references.
- Seal bundles with a stable hash and immutable status.
- Implement redaction profiles and export jobs.
- Store evidence artifacts in durable object storage before declaring pilot readiness.

Acceptance criteria:

- [ ] A closed pilot change can produce a sealed evidence bundle.
- [ ] Bundle manifest is deterministic and hash-stable.
- [ ] Sealed bundles cannot be mutated through application services.
- [ ] Export includes all required evidence and excludes secrets.
- [ ] Tests detect manifest mutation, missing artifacts, checksum mismatch, cross-org export attempts, and redaction failures.

### Gap: Auditor workspace and scoped read-only access are absent

Severity: Blocking if pilot includes auditor/customer review; otherwise an explicit pilot exclusion

Current evidence:

- Missing `apps/api/apps/auditor/`
- `apps/api/apps/common/permissions.py:6-17`
- `apps/api/config/api_v1_urls.py:44-67`

Why it matters:

Auditor access cannot be simulated with normal organization viewer permissions. A pilot needs scoped grants, read-only evidence access, limited exports, and audit trails around auditor activity.

Required fix examples:

- Add auditor access grants with org, scope, expiry, allowed objects, export permissions, and revocation.
- Add auditor search/detail APIs that only return sealed or explicitly shareable evidence.
- Add frontend auditor workspace routes.
- Add audit events for grant creation, access, export, revocation, and expiry.

Acceptance criteria:

- [ ] Auditor users can only see granted objects.
- [ ] Revoked or expired grants deny access immediately.
- [ ] Auditor export permissions are separate from view permissions.
- [ ] Auditor activity is itself audited.
- [ ] Cross-org and over-scope access tests fail closed.

### Gap: Authorization is too coarse and lacks separation of duties

Severity: Blocking

Current evidence:

- `apps/api/apps/common/permissions.py:6-17`
- `apps/api/apps/approvals/views.py:61-90`
- `apps/api/apps/changes/services.py:2940-2953`

Why it matters:

Owner/admin/operator/viewer is not enough for governed production changes. A requester approving their own change, an executor verifying their own work, or an emergency activator reviewing their own breakglass action undermines the evidence.

Required fix examples:

- Define a pilot permission matrix for requester, approver, dispatcher, executor, verifier, auditor, org admin, and support.
- Enforce SoD in services, not only in views.
- Add policy-configurable SoD rules for operation profiles.
- Include actor identity in dispatch preflight authorization and denial reasons.

Acceptance criteria:

- [ ] Requester self-approval is denied when SoD is enabled.
- [ ] Executor self-verification is denied when SoD is enabled.
- [ ] Breakglass activator cannot retro-review the same breakglass session.
- [ ] Dispatch actor authorization checks specific permissions, not just actor presence.
- [ ] Tests cover role, scope, and SoD denial for every pilot action.

### Gap: Dispatch, policy, and window gates drift from Phase 11.2 intent

Severity: Blocking

Current evidence:

- `apps/api/apps/changes/services.py:1063-1070`
- `apps/api/apps/changes/services.py:1096-1119`
- `apps/api/apps/changes/services.py:1196-1255`
- `apps/api/apps/changes/services.py:2733-2800`
- `apps/api/config/api_v1_urls.py:44-67`

Why it matters:

Approval can immediately make a change dispatchable. Policy and window checks can pass by default. There is no explicit public dispatch endpoint. This weakens the separation between approval, scheduling, preflight review, and dispatch authorization.

Required fix examples:

- Add explicit dispatch API/service command for approved/scheduled changes.
- Stop auto-dispatching immediately on approval unless the pilot scope explicitly requires it and documents why.
- Require a successful current policy evaluation before dispatch for governed profiles.
- Require an open change window for production profiles unless an approved exception applies.
- Surface preflight results in the UI before dispatch.

Acceptance criteria:

- [ ] Approval does not create an execution unless explicit dispatch policy allows it.
- [ ] Production changes without a current open window fail preflight.
- [ ] Missing policy evaluation fails preflight for governed profiles.
- [ ] Dispatch actor must have the dispatch permission and satisfy SoD.
- [ ] Tests cover approval-only, scheduled, explicit dispatch, policy missing/failing, window missing/closed, and target-lock conflict paths.

### Gap: Artifact storage is local-only and evidence durability is not pilot-grade

Severity: Blocking

Current evidence:

- `apps/api/apps/artifacts/storage.py:1-61`
- `infra/aws/README.md:1-21`
- `docker-compose.yml`

Why it matters:

Local filesystem artifacts are not a reliable evidence substrate for a real organization. Container rebuilds, host loss, volume misconfiguration, or manual file mutation can destroy or alter pilot evidence.

Required fix examples:

- Implement S3 or equivalent object storage backend behind the existing `ArtifactStorage` abstraction.
- Use KMS encryption, bucket policies, checksum verification, and lifecycle controls.
- Add retention and legal-hold controls for evidence-related artifacts.
- Ensure downloads are short-lived and organization-scoped.

Acceptance criteria:

- [ ] Pilot artifacts are stored in durable object storage.
- [ ] Artifact upload verifies checksum and size constraints.
- [ ] Artifact download authorization is organization-scoped and audited.
- [ ] Evidence-related artifacts cannot be deleted while under legal hold or sealed bundle dependency.
- [ ] Tests cover upload/download/checksum/cross-org/delete/retention behavior.

### Gap: Production deployment and operational runbooks are absent

Severity: Blocking

Current evidence:

- `infra/aws/README.md:1-21`
- `Makefile`
- `.github/workflows/ci.yml`
- Docker verification results in section 13

Why it matters:

A real pilot needs a controlled environment, backups, restore evidence, secrets, logs, network boundaries, deployment rollback, and support playbooks. Local compose is useful for development but not enough for a real organization.

Required fix examples:

- Define minimal pilot deployment architecture, even if intentionally small.
- Add infrastructure-as-code for API, web, database, object storage, secrets, logs, and private runner connectivity.
- Add deployment workflow with manual production gate, rollback plan, and migration check.
- Add backup/restore runbook and evidence.
- Add pilot incident response and operational support runbooks.

Acceptance criteria:

- [ ] Pilot environment can be rebuilt from code and documented secrets.
- [ ] Database backup and restore drill has recorded evidence.
- [ ] Object storage retention and recovery are tested.
- [ ] Deployment has preflight checks, rollback path, and manual approval.
- [ ] Logs and alerts cover API health, runner liveness, failed dispatch, failed verification, and artifact errors.

### Gap: Local/demo configuration does not reliably support change dispatch

Severity: Blocking for local pilot rehearsal; pilot limitation if the pilot never uses local compose

Current evidence:

- `apps/api/config/settings/base.py:210-213`
- `apps/api/config/settings/prod.py:21-24`
- `.env.example`
- `docker-compose.yml`
- Verification results in section 13

Why it matters:

Change dispatch token generation rejects missing or insecure placeholder secrets, but the sample environment and compose API service do not make that required variable obvious. A pilot rehearsal can fail at dispatch even when the rest of the local stack appears healthy. The current compose state also has the API container exited and runner not running, so the documented verification commands cannot establish readiness.

Required fix examples:

- Add `CHANGE_DISPATCH_TOKEN_SECRET` to `.env.example` with a non-secret placeholder instruction.
- Pass the variable explicitly through `docker-compose.yml`.
- Add startup or bootstrap documentation that explains when local dispatch requires a strong dev-only value.
- Add a local readiness command that checks API health, migrations, required env, runner liveness, and dispatch-token configuration.

Acceptance criteria:

- [ ] A fresh local bootstrap documents every required variable for change dispatch.
- [ ] `docker compose exec -T api python manage.py check` runs after documented bootstrap.
- [ ] A seeded dev change can reach dispatch without hitting insecure dispatch-token configuration.
- [ ] Local readiness docs distinguish dev-only secrets from production secret handling.

### Gap: Operational recovery for real execution is incomplete

Severity: Blocking for real execution; pilot limitation for simulated demos

Current evidence:

- `apps/api/apps/executions/services.py`
- `apps/runner/runner/main.py`
- `apps/runner/runner/poller.py`
- Current public cancellation supports only queued execution paths.

Why it matters:

Real production operations fail mid-step, hang, lose runner connectivity, or require operator cancellation. Without well-defined cancellation, retry, repair, and lock release semantics, a pilot can strand locks, leave unknown target state, or create misleading evidence.

Required fix examples:

- Add running execution cancellation and runner kill propagation.
- Add step retry rules with explicit safe/unsafe retry policy.
- Add lock release and repair workflows for crashed or recovered executions.
- Add operator runbooks for stuck dispatchable, running, verification-pending, and sealed-bundle-failed states.

Acceptance criteria:

- [ ] Running cancellation stops runner work and records final state.
- [ ] Stale claimed/running executions recover without cross-tenant or target-lock leakage.
- [ ] Target locks are released or repaired under documented conditions.
- [ ] Manual repair actions are permissioned and audited.
- [ ] Tests simulate runner crash, heartbeat timeout, API restart, cancellation, retry denial, and repair.

## 12. Recommended Pilot-Readiness Implementation Sequence

### Phase 0: Define the pilot contract and fail-closed scope

Goal:

Define one real organization pilot scenario and explicitly exclude everything else.

Scope:

- One organization.
- One operation profile.
- One target type/environment.
- One typed action or small typed action set.
- One runner pool.
- One evidence bundle type.
- One auditor view/export flow.

Files touched:

- `docs/runbooks/` or `docs/reports/` for pilot contract and risk register.
- `docs/blueprints/` implementation-status updates.
- `.env.example` and deployment docs for required pilot configuration.

Drift risks:

- Over-scoping into enterprise production before one safe vertical slice works.
- Treating simulated execution as acceptable pilot evidence.

Verification steps:

- Architecture review confirms all exclusions are documented.
- Security review confirms excluded paths are disabled or inaccessible.

Exit criteria:

- Pilot contract names supported workflows, targets, users, roles, runner pools, evidence outputs, and explicit non-goals.

### Phase 1: Repair dispatch and authorization gates

Goal:

Make the current Phase 11.1/11.2 control plane fail closed before adding real execution.

Scope:

- Explicit dispatch API.
- No approval-triggered auto-dispatch unless explicitly allowed by operation profile.
- Mandatory policy evaluation for governed profiles.
- Mandatory production window or approved exception.
- Service-level dispatch permission and SoD.

Files touched:

- `apps/api/apps/changes/models.py`
- `apps/api/apps/changes/services.py`
- `apps/api/apps/changes/views.py`
- `apps/api/apps/changes/serializers.py`
- `apps/api/apps/changes/urls.py`
- `apps/api/apps/changes/tests/`
- `apps/web/src/features/changes/`

Drift risks:

- Breaking existing happy-path tests that assume approval auto-dispatches.
- Duplicating permission checks in views without service-level enforcement.

Verification steps:

- Unit tests for every preflight gate.
- API tests for explicit dispatch.
- Cross-org negative tests.
- UI smoke tests for preflight and dispatch.

Exit criteria:

- A production change cannot create an execution until explicit dispatch succeeds through policy, window, freeze, lock, actor, and SoD checks.

### Phase 2: Build real runner execution and target/secret boundaries

Goal:

Replace simulated execution for the pilot operation with a safe, typed, sandboxed execution path.

Scope:

- Typed pilot action schema.
- Runner sandbox provider.
- Secret references and step-scoped injection.
- Runner registry/pool/capability scheduling.
- Cancellation/timeout behavior.

Files touched:

- `packages/workflow-schema/`
- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/client.py`
- `apps/api/apps/executions/`
- `apps/api/apps/changes/`
- New or existing Django app for runner registration/secret references.

Drift risks:

- Moving state authority into runner.
- Logging raw secrets.
- Allowing generic shell execution without a pilot threat model.

Verification steps:

- Runner unit tests for success, failure, timeout, cancellation, secret masking, and unsupported action denial.
- API tests for runner pool selection and claim refusal.
- End-to-end test for one real pilot action.

Exit criteria:

- A pilot change executes real work in a sandboxed runner and records trustworthy result evidence.

### Phase 3: Implement verification and closure MVP

Goal:

Give every pilot change a controlled post-execution verification and closure path.

Scope:

- Verification plan/check/result models.
- Closure decision model.
- Verifier role/permission and SoD.
- Frontend verification workspace.

Files touched:

- `apps/api/apps/changes/` or a new Django verification app.
- `apps/api/apps/audit/`
- `apps/web/src/features/changes/`
- `apps/web/src/app/router.tsx`

Drift risks:

- Treating verification as a text note instead of structured evidence.
- Allowing executor self-verification.

Verification steps:

- Tests for verification pass/fail/waiver.
- Tests for closure blocked until required checks pass.
- Cross-org and SoD negative tests.

Exit criteria:

- A successful pilot execution cannot close until verification requirements are satisfied and audited.

### Phase 4: Implement durable artifacts and sealed evidence bundles

Goal:

Produce immutable, exportable evidence for a closed pilot change.

Scope:

- Durable artifact backend.
- Evidence bundle models.
- Deterministic manifest.
- Seal hash.
- Redaction/export job.
- Legal hold and retention minimums.

Files touched:

- `apps/api/apps/artifacts/`
- New `apps/api/apps/evidence/`
- `apps/api/apps/audit/`
- `infra/`
- `.env.example`
- `.github/workflows/ci.yml`

Drift risks:

- Sealing references to mutable local files.
- Including secrets in export.
- Generating non-deterministic manifests.

Verification steps:

- Bundle determinism tests.
- Artifact checksum tests.
- Redaction tests.
- Cross-org export denial tests.
- Storage backend integration tests.

Exit criteria:

- A closed pilot change can generate a sealed evidence export that remains hash-stable and excludes secrets.

### Phase 5: Implement scoped auditor workspace

Goal:

Allow read-only review of pilot evidence without granting broad organization access.

Scope:

- Auditor access grants.
- Auditor search/detail APIs.
- Auditor frontend routes.
- Export permissions and revocation.
- Audit events for auditor activity.

Files touched:

- New `apps/api/apps/auditor/`
- `apps/api/apps/common/permissions.py`
- `apps/api/config/api_v1_urls.py`
- `apps/web/src/features/auditor/`
- `apps/web/src/app/router.tsx`

Drift risks:

- Reusing viewer membership as auditor access.
- Allowing auditor search to cross organization or scope boundaries.

Verification steps:

- Grant/revoke/expire tests.
- Search scope tests.
- Export permission tests.
- UI smoke tests.

Exit criteria:

- An auditor can view and export only the evidence explicitly granted to them, and all access is audited.

### Phase 6: Stand up a pilot operations environment

Goal:

Run the platform in an environment that can support a real organization's controlled pilot.

Scope:

- Minimal infrastructure-as-code.
- Durable database and object storage.
- Secrets management.
- Private runner connectivity.
- Deployment workflow.
- Backup/restore runbook.
- Monitoring and alerting.

Files touched:

- `infra/`
- `.github/workflows/`
- `docker-compose.yml` only for local parity, not as production deployment.
- `.env.example`
- `docs/runbooks/`

Drift risks:

- Building unmanaged cloud resources outside IaC.
- Running production-like pilot from local compose.
- Skipping restore and rollback evidence.

Verification steps:

- Deployment dry run.
- Migration check.
- Backup/restore drill.
- Runner connectivity test.
- Full pilot e2e test in the pilot environment.

Exit criteria:

- The pilot environment is reproducible, observable, backed up, and capable of running the end-to-end pilot scenario.

## 13. Verification Plan

Requested verification command results from this audit:

| Command | Result | Notes |
|---|---|---|
| `docker compose exec api python manage.py check` | Not runnable | `api` service is not running. The current compose state shows `runbook-platform-api-1` exited with code 1. |
| `docker compose exec api pytest` | Not runnable | `api` service is not running. |
| `docker compose exec runner pytest` | Not runnable | `runner` service is not running; container exists but is in `Created` state. |
| `cd apps/web && npm run lint` | Passed | Local web lint completed successfully. |
| `cd apps/web && npm run build` | Passed | Local Vite/TypeScript build completed successfully. |

Additional environment evidence:

- `docker compose ps` showed only `postgres`, `pgbouncer`, and `ai` running.
- `docker compose ps -a` showed `api` exited, `runner` created, and `web` created.
- `docker compose logs api` showed readiness health checks returning 500 before the API container exited.

This means the repository should not be considered test-clean from this audit. Web checks passed, but API and runner verification could not be executed in the current Docker state.

Required verification before any pilot:

- `docker compose exec -T api python manage.py check`
- `docker compose exec -T api pytest`
- `docker compose exec -T runner pytest`
- `cd apps/web && npm run lint`
- `cd apps/web && npm run build`
- Migration check for every new Django app.
- Cross-org API negative tests for changes, approvals, verification, evidence, auditor, artifacts, and exports.
- End-to-end pilot test: create org, configure operation profile, publish typed workflow, create change, add target, attach/open window, approve, preflight, explicitly dispatch, execute real pilot action, verify, close, seal bundle, grant auditor access, export evidence.
- Security tests for secret redaction in audit metadata, execution snapshots, stdout/stderr artifacts, evidence bundle manifests, exports, frontend responses, and integration payloads.
- Operational tests for runner crash, API restart, heartbeat timeout, cancellation, stale locks, failed verification, failed bundle sealing, and recovery runbooks.

## 14. Final Recommendation

The repository should not be used for a real organization pilot yet. It is suitable for a non-production demo of control-plane concepts and for continued implementation of the Phase 11 architecture, but not for governed production-change evidence.

The audited report should be revised or accompanied by an implementation-status audit before being used as planning input. Its gap list is useful, but its key assumption is false for the current repository.

## Final Verdict

Pilot readiness: **Not ready**

Reason:

The current repository does not implement Phase 11.3 through Phase 11.6, the runner simulates work, evidence bundles and auditor access are absent, artifact storage is local-only, dispatch gates need fail-closed repair, authorization lacks pilot-grade separation of duties, and production deployment is not implemented.

Minimum required next step:

Build and verify one end-to-end pilot vertical slice: explicit dispatch gates, real sandboxed runner execution, scoped secret/target access, verification closure, sealed evidence export, and scoped auditor read-only access for one narrowly defined operation.
