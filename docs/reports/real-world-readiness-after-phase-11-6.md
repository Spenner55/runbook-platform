# Real-World Readiness After Phase 11.6

| Field | Value |
|---|---|
| Report date | 2026-05-05 |
| Scope | Repository read and gap analysis for what remains after Phase 11.6 is fully implemented |
| Primary question | What must still be built for this platform to work on real projects? |
| Key assumption | Phases 11.1 through 11.6 are complete, verified, and aligned with their blueprints |

## Executive Summary

If Phase 11.6 is fully implemented, this repository would have a strong governed change-management and audit-evidence control plane. It would be able to model production changes, freeze windows, target locks, approvals, policy gates, verification, emergency exceptions, sealed evidence bundles, auditor search, external references, and control coverage.

That still would not make it a real project execution platform.

The missing center is the execution plane. Today the runner still simulates work. `apps/runner/runner/sandbox.py` is a stub, and `apps/runner/runner/executor.py` still treats a step as success after a sleep unless the command contains `FAIL_STEP`. Phase 11.6 does not solve that. It adds audit-facing controls around completed evidence, not a safe way to run real commands, connect to real targets, inject real credentials, capture real logs, or recover from real operational failures.

The practical answer is:

1. Build a real sandboxed runner and typed action system.
2. Add a production credential and target-access model.
3. Deploy the platform onto real infrastructure with real storage, private runner networking, backups, monitoring, and rollback.
4. Add project onboarding primitives: runner pools, environments, service catalog, operation templates, variables, secrets, and workflow testing.
5. Harden the product for enterprise use: SSO, fine-grained RBAC, separation of duties, audit export operations, compliance retention, support workflows, and operational runbooks.

Until those exist, the repo is best understood as a governed control-plane prototype with increasingly complete compliance workflows, not a system that can safely execute production work for customers.

## Current Repository Read

The repo currently has these important foundations:

- Django is the control plane and owns persistence, orchestration, validation, state transitions, audit, and API contracts.
- The runner talks only to Django internal APIs under `/api/v1/internal/`.
- React talks only to Django public APIs.
- The AI service is advisory and stateless.
- Approvals, policies, audit events, artifacts, integrations, authentication, live execution streaming, and a substantial `changes` app are present in the working tree.
- Production hardening exists in code and documentation, but Phase 10.10 AWS deployment remains blueprint-only.
- Artifact storage is still local-only in code. `ArtifactStorage` explicitly raises if `ARTIFACT_STORAGE_BACKEND != "local"`.
- AWS infrastructure is not scaffolded. `infra/aws/README.md` says there are no live resources, no Terraform/CDK/Pulumi root, and no deployment workflow.
- AI parsing can use OpenAI when enabled, but the default parser is deterministic and mostly converts numbered text into `manual_task` steps.
- The workflow schema is still thin: step `id`, `name`, `type`, `risk`, optional `command`, optional `requiresApproval`, and optional `approvalTimeoutSeconds`.

The most important runner facts:

- `apps/runner/runner/sandbox.py` contains only `class Sandbox: pass`.
- `Executor._execute_command()` does not run a command. It checks for `FAIL_STEP`, sleeps for 0.5 seconds on the happy path, uploads synthetic stdout/stderr, and marks the step terminal.
- Runner APIs, heartbeats, approvals, artifacts, and change binding are meaningful scaffolding, but they surround simulated execution.

## What Phase 11.6 Would Add

Assuming Phases 11.1 through 11.6 are completed as designed, the platform would gain the following governance surface:

- `ChangeRecord` dossiers for high-risk production operations.
- Operation profiles that allowlist workflows and enforce production target discipline.
- Change windows, freeze rules, target locks, and dispatch preflight checks.
- Verification plans, verification results, attestations, and controlled closure.
- Emergency exceptions, breakglass sessions, and mandatory retro-review.
- Sealed evidence bundles with deterministic manifests, redaction, exports, retention, and legal holds.
- Auditor workspace APIs and UI for scoped evidence search and read-only change detail.
- External references for ServiceNow, Jira, PagerDuty, and custom systems as persisted snapshots.
- Service catalog metadata and control coverage mapping from sealed evidence.

That is valuable, but it is mostly about whether work is authorized, traceable, reviewable, exportable, and auditable. It does not provide the mechanical ability to execute real operations.

## Real-World Gaps

### 1. Real Sandboxed Execution

This is the largest blocker.

The platform needs an actual execution backend with a clear threat model. A safe implementation is more than `subprocess.run()`.

Required capabilities:

- Per-step isolated workspace creation and cleanup.
- Command execution with timeout, stdout/stderr capture, exit code capture, and signal handling.
- Configurable CPU, memory, process, file size, and wall-clock limits.
- Network egress controls by runner pool, project, environment, and step type.
- Filesystem controls: read-only roots, writable scratch space, mounted artifacts, and path traversal protection.
- Environment-variable redaction and secret masking in logs and artifacts.
- Cancellation and kill semantics from Django to runner.
- Retry policy that distinguishes safe retry, unsafe retry, and manual retry.
- Step-level artifact collection from actual files, not synthetic stdout/stderr only.
- Explicit unsupported-feature failures rather than silent success for unknown step types.

Recommended implementation direction:

- Introduce a `SandboxProvider` interface in the runner.
- Start with a conservative local process sandbox only for development.
- Add a container-backed sandbox for real pilot use.
- Treat each step as a job with an immutable execution spec and a result envelope.
- Keep Django as the state authority; the runner should execute and report facts only.

### 2. Typed Action Catalog

The current workflow definition is too generic for real projects. A free-form `command` string cannot carry enough safety, validation, UI, or audit semantics.

Needed additions:

- Workflow schema v2 with typed step specs.
- Step types such as `shell_command`, `http_request`, `manual_task`, `approval_gate`, `script`, `terraform_plan`, `terraform_apply`, `kubernetes_rollout`, `database_migration`, and `verification_check`, added only as actually needed.
- Per-step input schema, output schema, and validation.
- Declared required secrets and target access.
- Declared artifact outputs.
- Declared rollback or compensation behavior where supported.
- Dry-run support for actions that can safely preview work.
- Idempotency keys or explicit "not idempotent" declarations.
- Versioned action contracts so old workflows remain executable.

Without this, policy and audit can say a step was approved, but they cannot reliably explain what the step was allowed to do.

### 3. Target Connectivity And Runner Pools

Real projects need runners that can reach real systems. A single generic poller is not enough.

Needed additions:

- Runner registration records in Django, not just bearer-token identity.
- Runner pools mapped to organizations, projects, environments, regions, networks, and capabilities.
- Runner labels and scheduling constraints, for example `prod-vpc`, `aws-us-east-1`, `kubernetes`, `terraform`, or `db-readonly`.
- Queue selection by target, operation profile, required action type, and environment.
- Concurrency limits per runner, pool, organization, target, and operation profile.
- Backpressure and dispatch refusal when no eligible runner is online.
- Runner liveness UI and operator diagnostics.
- Graceful runner drain for upgrades.
- Safe requeue or fail behavior when a runner disappears mid-step.
- A control contract for cancellation, timeout, and stuck job recovery.

For customer environments, the likely shape is an installable agent or runner service inside the customer's network, not only a central hosted runner.

### 4. Secrets And Credential Brokerage

Real execution requires credentials. The repo must not solve this by storing raw secrets in workflows, requested inputs, logs, artifacts, or audit metadata.

Needed additions:

- Secret references in workflow/action definitions.
- Secret storage integration: AWS Secrets Manager, SSM Parameter Store, HashiCorp Vault, or another configured backend.
- Per-organization and per-environment secret namespaces.
- Short-lived credential minting where possible, especially cloud credentials through OIDC or STS.
- Step-scoped injection of only the secrets the action declares.
- Secret masking in stdout, stderr, exception text, artifact metadata, audit events, and integration payloads.
- Rotation workflows and usage reporting.
- Policy gates for high-risk credential access.
- Strong separation between platform credentials, runner credentials, integration credentials, and target credentials.

This is a production blocker because a real runner without a credential model either cannot do useful work or will leak powerful credentials.

### 5. Real Artifact And Evidence Storage

The artifact model is useful, but storage is currently local. Real deployments need durable object storage.

Needed additions:

- S3-backed artifact storage or equivalent object storage.
- KMS encryption and bucket policies.
- Private download flow with short-lived signed URLs or streamed Django responses.
- Large artifact handling with multipart upload where needed.
- Retention cleanup that works against object storage.
- Legal hold protection for evidence bundles and source artifacts.
- Checksums verified on upload and download.
- Object lifecycle policies aligned with evidence retention.
- Storage cost controls by organization and project.

Phase 11.5 evidence bundles depend on stable artifact bytes. Local filesystem storage is not enough for a real deployment.

### 6. Production Deployment And Operations

Phase 10.10 is still blueprint-only. The repo needs an actual deployment substrate before real projects can use it.

Needed additions:

- Infrastructure as code under `infra/aws/` or an explicitly chosen alternative.
- Separate staging and production environments.
- ECS/Fargate, RDS PostgreSQL, S3 artifacts, ECR images, ALB, ACM, Route 53, Secrets Manager or SSM, CloudWatch logs and alarms.
- Private network path for runner-to-Django internal APIs.
- Public exposure only for browser/API surfaces that should be public.
- Database migration workflow with preflight, rollback plan, and manual production gate.
- Image build and deploy workflows in GitHub Actions with OIDC, not long-lived AWS keys.
- Backups, restore drills, point-in-time recovery, and runbook evidence.
- Centralized logs, metrics, dashboards, and alerts.
- Error reporting and support diagnostics.
- Load tests that include real execution pressure, not only API list endpoints.

Until this exists, the platform is local-development capable, not production deployable.

### 7. Stronger Authorization And Enterprise Identity

The current permission model is useful but coarse. Phase 11.6 adds scoped auditor grants, but real customers usually need more.

Needed additions:

- SSO/SAML or OIDC enterprise login.
- Optional SCIM or directory-driven user provisioning.
- Team/group mapping to organization roles.
- Fine-grained permissions by project, service, environment, operation profile, action type, and target.
- Separation-of-duties rules: requester cannot approve, executor cannot verify, breakglass activator cannot retro-review.
- Auditor read-only role with export constraints and legal-hold visibility rules.
- Service accounts and API tokens with narrow scopes.
- Session management, device/session revocation, and admin audit views.

For real production operations, "operator/admin/viewer" is not enough.

### 8. Workflow Authoring, Testing, And Promotion

Real projects need a way to prove a workflow is safe before it reaches production.

Needed additions:

- Workflow schema versioning and migration tools.
- Draft, review, test, promote, and deprecate flows.
- Non-production test executions against safe runner pools.
- Static validation for action specs, required secrets, target compatibility, and unsupported step types.
- Linting for dangerous shell patterns.
- Dry-run execution mode where actions support it.
- Golden test cases for workflow outputs.
- Human review UI that shows command/action diffs between workflow versions.
- Rollback workflow association.
- Template library for common operation patterns.

The platform currently has workflow draft/publish basics, but not enough validation around real operational content.

### 9. AI Parsing That Produces Usable Workflows

The AI boundary is correctly advisory, but the parser is not enough for real runbook conversion.

Needed additions:

- Provider-backed parsing enabled and evaluated for target customer runbooks.
- Structured extraction of commands, preconditions, rollback steps, risks, secrets, artifacts, verification checks, and target types.
- Confidence scores and mandatory human review for executable steps.
- Prompt and schema eval suites using representative runbooks.
- Cost controls, input size controls, PII/secret detection, and tenant data governance.
- Versioned parse models and reproducible parse records.
- UI that makes AI output reviewable and correctable.

AI should accelerate workflow drafting, not create executable production operations without review.

### 10. Integration Depth

Current integrations are mostly outbound delivery attempts. Phase 11.6 external references are persisted snapshots, not workflow orchestration.

Needed additions for real projects:

- Optional inbound linking/import from ServiceNow, Jira, and PagerDuty.
- Explicit mapping between external change fields and platform `ChangeRecord` fields.
- Reconciliation views that show stale or mismatched external references.
- Webhook signature verification for inbound events, if inbound sync is added.
- Delivery outbox or durable retry mechanism if integration delivery becomes business-critical.
- Clear product boundary: external systems can mirror and reference; Django remains the authority for platform execution decisions.

This should be implemented carefully so the repo does not become an ITSM workflow clone.

### 11. Real-Time Execution UX

The current UI has execution detail views and live event work, but real execution needs richer operator controls.

Needed additions:

- Live stdout/stderr tail with redaction and truncation.
- Step timeline with retries, approvals, artifacts, policy decisions, and target facts in one view.
- Cancel execution and cancel step flows.
- Retry failed step or rerun execution with policy checks.
- Manual intervention state for recoverable failures.
- Runner diagnostics visible from execution pages.
- Clear distinction between platform failure, target failure, policy block, approval timeout, sandbox failure, and user cancellation.
- Evidence completeness status during and after execution.

Operators need to understand what is happening while production work is underway, not only after evidence is sealed.

### 12. Reliability Guarantees And Failure Semantics

The platform needs explicit behavior for real failure modes.

Needed additions:

- Durable idempotency keys for all mutating public and internal APIs.
- More complete retry contracts for runner state callbacks.
- Execution cancellation state machine.
- Step retry state machine.
- Runner crash recovery that distinguishes before-start, during-step, after-artifact-upload, and after-terminal-callback windows.
- Handling for Django unavailable while runner is executing.
- Handling for object storage unavailable during artifact upload.
- Dispatch rollback if target locks are acquired but execution reservation fails.
- Operational repair commands for stranded changes, locks, approvals, and evidence bundles.

Some watchdog and stuck recovery logic exists, but real execution will create more edge cases than simulated execution.

### 13. Real Project Onboarding Model

The repo needs first-class concepts that let a team actually onboard a project.

Needed additions:

- Project or workspace entity, if organization alone is too broad.
- Environment definitions: development, staging, production.
- Service catalog ownership and target mapping populated through UI/API.
- Runner pool setup workflow.
- Secret setup workflow.
- Operation profile templates.
- Freeze calendar setup.
- Policy bootstrap templates.
- First workflow import/test/publish guide.
- Sample real-world runbooks and expected workflows.
- Admin onboarding checklist.

Without this, every new project requires hand-built data and internal knowledge of the platform.

## Minimum Viable Real-World Pilot

A credible first real-world pilot should not attempt every feature above. It should pick one narrow operation type and make that operation genuinely safe.

Recommended pilot scope:

1. One deployment target type, for example a staging service restart or a non-critical production maintenance operation.
2. One runner pool inside the target network.
3. Container-backed sandbox with strict timeouts and output capture.
4. One or two typed action kinds, not arbitrary shell for everything.
5. Secrets through a real secret manager.
6. S3 artifact storage.
7. AWS or equivalent staging deployment of the platform.
8. SSO or tightly controlled internal auth.
9. Approval, policy, audit, artifact, change, verification, and evidence flows enabled.
10. A manual rollback procedure documented and tested.
11. A restore drill for database and artifact storage.
12. A pilot runbook with dry-run, success, failure, cancellation, and runner-crash tests.

The first pilot should optimize for proving safety and recoverability, not broad workflow coverage.

## Suggested Implementation Sequence After Phase 11.6

### Phase A: Execution Substrate

- Implement `SandboxProvider`.
- Add real process/container execution.
- Capture stdout/stderr and file artifacts.
- Add step timeout, cancellation, and resource limits.
- Fail closed for unsupported step types.

Exit gate: a real command can run in an isolated workspace, produce artifacts, be canceled, time out, fail, and recover from runner restart without corrupting Django state.

### Phase B: Typed Actions And Workflow Schema v2

- Add action specs to workflow definitions.
- Add validation and compatibility checks.
- Add one safe action adapter for the pilot operation.
- Add workflow test/dry-run flow.

Exit gate: a workflow can describe a real operation without embedding uncontrolled free-form behavior as the only contract.

### Phase C: Secrets And Target Access

- Add secret references and secret manager backend.
- Add runner-pool-to-environment mapping.
- Add per-step credential injection.
- Add masking and audit scrubbing tests.

Exit gate: a real step can use a scoped credential without storing or leaking it.

### Phase D: Durable Storage And Deployment

- Implement object storage for artifacts/evidence.
- Implement Phase 10.10 infrastructure and deploy workflows.
- Add staging/prod separation, backups, alarms, logs, and restore drills.

Exit gate: the platform is running in a real environment with durable storage and repeatable deployment.

### Phase E: Project Onboarding And Pilot UX

- Add runner pool administration UI.
- Add environment/target/secret setup UI.
- Add operation profile templates.
- Add execution diagnostics, cancellation, retry, and live logs.

Exit gate: a new internal team can onboard a pilot project using documented workflows rather than direct database setup or developer assistance.

## Bottom Line

After Phase 11.6, the repo would be close to a serious governed change-control and evidence product. It would not yet be a serious automation runner.

The critical missing implementation is not another audit surface. It is the operational substrate that turns approved steps into safe, isolated, observable, credentialed, recoverable work against real targets. Build that next, narrowly, with one real pilot operation, and keep the current Django-control-plane boundary intact.
