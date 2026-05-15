# Pilot Phase D: Secrets and Credential Brokerage Blueprint

| Field | Value |
|---|---|
| Blueprint ID | `pilot-phase-d-secrets-credential-brokerage` |
| Objective | Add a production-safe credential reference, brokering, injection, masking, and audit-scrubbing model for narrow pilot execution. |
| Status | Blueprint only |
| Authored | 2026-05-08 |
| Primary gap | No production-safe credential model exists. Workflows, change requests, execution snapshots, logs, artifacts, and audit metadata do not yet have a shared secret-reference and redaction contract. |
| Depends on | Existing workflow, execution, audit, artifact, integration, policy, change, and runner scaffolding; Pilot Phase A execution substrate; Pilot Phase B typed actions and workflow schema v2; Pilot Phase C runner pools and target connectivity. |

## Current State Summary

Files inspected for this blueprint:

- `apps/api/apps/workflows/`
- `apps/api/apps/audit/`
- `apps/api/apps/artifacts/`
- `apps/runner/runner/`
- `apps/api/apps/executions/`
- `apps/api/apps/integrations/`
- `apps/api/apps/changes/`
- `apps/api/apps/policies/`
- `packages/workflow-schema/workflow.schema.json`
- `apps/web/src/features/*/types.ts`
- `docs/report/real-world-readiness-after-phase-11-6.md`
- `docs/blueprints/pilot-phase-a-execution-substrate-blueprint.md`
- `docs/blueprints/pilot-phase-b-typed-actions-workflow-schema-v2-blueprint.md`
- `docs/blueprints/pilot-phase-c-runner-pools-target-connectivity-blueprint.md`

Important current facts:

- Django is already the control plane and owns workflow definitions, execution snapshots, step state transitions, approvals, policy evaluation, audit events, artifact metadata, change binding, target locks, breakglass checks, and internal runner API responses.
- The runner only talks to Django internal APIs and calls the step-start gate before execution.
- React talks to Django public APIs only.
- `Workflow.definition` and `Execution.workflow_snapshot` are JSON snapshots. Workflow schema v1 has no secret declaration model.
- Pilot Phase B expects workflow schema v2 to declare secrets by reference only, but the concrete backend, namespace, brokering, masking, and audit requirements still need definition.
- `ExecutionStep.command`, `ExecutionStep.step_snapshot`, and runner claim payloads can currently carry command text. They must not carry raw secret values.
- `apps/api/apps/audit/services.py` already has metadata key scrubbing and reject-on-sensitive-key behavior. That scrubber is necessary but insufficient for runtime secret values because it is key-name based rather than value-aware.
- `apps/api/apps/artifacts/services.py` validates artifact metadata and writes artifacts through `ArtifactStorage`, but it does not inspect or redact artifact bytes.
- `ArtifactStorage` is local-only today. Production object storage is out of this phase except where secret redaction and metadata contracts affect artifact upload.
- `IntegrationConnection.encrypted_credentials` stores integration webhook credentials encrypted with a local Fernet key. That is a narrow integration-specific mechanism, not a general platform secret store.
- Runner authentication currently uses bearer tokens from settings. Pilot Phase C is expected to replace this with per-runner identities and tokens.
- `ChangeRecord.requested_inputs` is persisted JSON and immutable after submit. It must not become a path for raw target credentials.
- `ChangeTarget.environment` is currently constrained to `production`; Phase D must define the broader environment-scoped model while allowing the pilot to start with production only.

The central Phase D rule: raw secrets must never be persisted in Django database rows, workflow JSON, execution snapshots, requested inputs, policy evaluations, audit events, integration delivery previews, log streams, artifact metadata, or evidence metadata. Runtime exposure is allowed only inside the selected runner step process, for the shortest practical time, after Django authorizes it.

## 1. Secret Reference Architecture

Phase D introduces secret references as first-class control-plane objects. A secret reference is metadata about how a secret may be used; it is not the secret value.

The architecture has five layers:

| Layer | Owner | Responsibility |
|---|---|---|
| Secret reference registry | Django | Stores non-secret metadata: organization, environment, namespace, key, backend path, version selectors, owner, status, rotation facts, and policy tags. |
| Secret backend abstraction | Django service boundary plus runner helper | Resolves references against the configured backend without leaking values into persistent state. |
| Brokered access decision | Django | Checks workflow declaration, execution state, runner ownership, runner pool eligibility, target/environment scope, policy, approval, breakglass, and step-start status. |
| Step-scoped delivery | Django internal API to runner, or runner backend fetch with Django-issued grant | Delivers only the exact secrets authorized for the current step. |
| Runner injection and masking | Runner | Injects values into the sandbox, masks them in streams and errors, clears local material after step completion, and reports only non-secret facts. |

Reference shape in workflow schema v2:

```json
{
  "key": "aws_deploy_role",
  "scope": "environment",
  "namespace": "aws/prod",
  "name": "deploy-role",
  "required": true,
  "usage": "env",
  "envName": "AWS_ROLE_ARN"
}
```

Rules:

- `key` is a workflow-local alias used by steps.
- `namespace` and `name` identify a `SecretReference`, not a backend-specific raw path in user-authored workflow text unless Django has validated and registered it.
- `scope` must be explicit: `organization`, `project`, `environment`, `target`, `integration`, or `runner_pool`.
- `usage` must be explicit: `env`, `file`, `header`, `token_exchange`, or `provider_native`.
- Steps reference declared aliases; they cannot request arbitrary backend paths at runtime.
- Raw values never appear in `Workflow.definition`, `Execution.workflow_snapshot`, `ExecutionStep.step_snapshot`, `ChangeRecord.requested_inputs`, or runner claim payloads unless the dedicated step-secret broker endpoint has authorized delivery.
- A missing, disabled, expired, wrong-environment, or policy-blocked reference fails closed before the runner starts the step command.

## 2. Secret Namespace Model

Namespaces prevent ambiguous credential lookup and tenant leakage.

Canonical reference URI:

```text
secretref://org/{organization_id}/env/{environment_key}/ns/{namespace}/name/{name}
```

Human-facing key:

```text
{environment_key}/{namespace}/{name}
```

Pilot namespace rules:

- Organization is mandatory for every reference.
- Environment is mandatory for all target and integration execution secrets. The pilot may only allow `production` until the `ChangeTarget.environment` constraint expands.
- Namespace is a slash-separated logical grouping such as `aws/deploy`, `github/actions`, `kubernetes/cluster-a`, `database/reporting`, or `webhooks/slack`.
- Name is a stable slug inside the namespace.
- `(organization, environment, namespace, name)` must be unique for active references.
- Backend path is stored separately from the display namespace and can differ between dev and production.
- Namespace names are metadata and must not contain secret values, account passwords, tokens, private URLs with embedded credentials, or customer PII.
- The public API must never expose raw backend ARNs or parameter names unless the caller has a specific secret-admin permission. Normal workflow authors see only approved reference names and safe descriptions.

Recommended `SecretReference` fields:

| Field | Purpose |
|---|---|
| `id` | UUID primary key. |
| `organization` | Tenant boundary. |
| `environment` | FK or stable key for `production`, `staging`, `development`, etc. Pilot can store a string until an `Environment` model ships. |
| `namespace` | Logical grouping. |
| `name` | Stable reference name. |
| `display_name` | Human-readable label. |
| `description` | Non-secret purpose text. |
| `secret_type` | `opaque`, `api_token`, `ssh_private_key`, `aws_role`, `aws_static_key`, `kubeconfig`, `tls_cert`, `database_password`, `webhook_url`, etc. |
| `credential_class` | `platform`, `runner`, `integration`, or `target`. |
| `backend` | `local_dev`, `aws_secrets_manager`, `aws_ssm_parameter`, future `vault`. |
| `backend_ref` | Backend-specific pointer. Treat as sensitive metadata; expose only to admins. |
| `backend_region` | AWS region or backend location. |
| `version_selector` | Optional `AWSCURRENT`, SSM version, pinned version, or empty for current. |
| `status` | `draft`, `active`, `disabled`, `rotating`, `retired`. |
| `last_validated_at` | Last successful metadata or value check without storing value. |
| `last_used_at` | Last brokered use. |
| `last_rotated_at` | Operator-entered or backend-observed rotation time. |
| `rotation_due_at` | Next expected rotation. |
| `owner_label` | Team or service owner. |
| `allowed_action_types` | Optional list such as `shell_command`, `http_request`, `terraform_plan`. |
| `allowed_runner_pool_ids` | Optional placement restriction. |
| `allowed_target_selectors` | Optional target-type and normalized-identifier restrictions. |
| `policy_tags` | Tags consumed by policy rules, for example `privileged`, `prod-write`, `breakglass-required`. |
| `metadata` | Sanitized operational metadata only. |

## 3. Environment-Scoped Credential Model

Phase D needs environment scope because the same workflow can run against different trust domains.

Recommended model: `Environment`

| Field | Purpose |
|---|---|
| `organization` | Tenant boundary. |
| `key` | Stable key, for example `development`, `staging`, `production`. |
| `name` | Display label. |
| `risk_level` | `low`, `medium`, `high`, `critical`. |
| `requires_change_record` | Whether executions in this environment must be change-bound. |
| `default_runner_pool` | Optional pool for non-change execution. |
| `secret_backend_profile` | Backend configuration key, not credentials. |
| `is_active` | Disabled environments cannot dispatch. |

Pilot compatibility:

- Until `ChangeTarget.environment` allows more values, production target secrets should use `environment="production"`.
- Non-production environments may be introduced for workflow testing, but they must not be silently mapped to production secrets.
- A workflow or change request must declare the environment explicitly or derive it from `ChangeTarget.environment`. Defaulting to production is forbidden.

Environment scope rules:

- A production step cannot consume a staging or development secret.
- A non-production step cannot consume production secrets unless a dedicated breakglass-like exception exists. That exception is not in Phase D pilot scope.
- Environment must be part of policy evaluation context, audit events, secret access grants, and UI filtering.
- Environment values must be normalized and controlled by Django. The runner must not claim an environment locally.

## 4. Secret Backend Abstraction

Introduce a small backend interface. It must hide provider details from workflows and keep all persistent state reference-only.

Expected responsibilities:

- Validate that a configured reference exists.
- Fetch a value or provider token only for a step-scoped grant.
- Return metadata such as version id, created time, rotation time, and tags where supported.
- Support value fingerprinting without exposing value, for example HMAC with a Django-side key for masking correlation.
- Support backend-specific failure classification: not found, permission denied, throttled, disabled KMS key, invalid version, expired grant, backend unavailable.

Conceptual interface:

```text
SecretBackend.validate_reference(ref) -> SecretReferenceStatus
SecretBackend.resolve(ref, grant_context) -> SecretMaterial
SecretBackend.describe(ref) -> SecretBackendMetadata
SecretBackend.supports_rotation_events(ref) -> bool
```

`SecretMaterial` exists only in memory and must include:

- `value` or `file_bytes`, never both unless required by type.
- `version_id` or version label.
- `expires_at` if the material is short-lived.
- `mask_values`, including the value and useful derived forms such as URL-encoded token, basic-auth header, and selected multiline chunks for private keys.
- `injection_hint`, such as environment variable name or file mount name.

Abstraction rules:

- Backend code must never call `AuditService.emit()` with raw material.
- Backend code must never log raw provider responses.
- Backend exceptions must use safe error codes and safe messages.
- Persistent records store only references, version labels, fingerprints, and access outcomes.
- If backend resolution fails, the step is blocked or failed before command execution. There is no fallback to user-provided raw credentials.

## 5. Local/Dev Backend Expectations

Local development needs useful behavior without normalizing unsafe production habits.

Recommended backend: `local_dev`

- Enabled only when `DEBUG=True` or an explicit `SECRET_BACKEND=local_dev` non-production setting is present.
- Reads values from local environment variables or a gitignored file under a configured dev-only path.
- Requires a local registry entry in Django for every reference. Direct ad hoc lookup of arbitrary environment variable names is not allowed.
- Refuses to start under production settings.
- Emits clear startup/readiness errors if a referenced dev secret is missing.
- Supports deterministic fake secrets in tests, but tests must assert those values are redacted.
- Uses conspicuous placeholder values, for example `dev-redacted-token-...`, never copied production credentials.

Local/dev rules:

- `.env.example` may document variable names but must never include real-looking credentials.
- Seed data may create `SecretReference` rows but must not seed raw values.
- Developer docs must instruct users to place local values in ignored files or environment variables.
- Dev backend should still exercise masking, redaction, and fail-closed behavior so production-only code paths do not hide defects.

## 6. AWS Secrets Manager/SSM Integration Direction

The production direction should support both AWS Secrets Manager and SSM Parameter Store.

Use AWS Secrets Manager when:

- Values need managed rotation.
- Secret versions and staging labels matter.
- The secret is a structured JSON object with related fields.
- Audit and lifecycle metadata are important.

Use SSM Parameter Store when:

- Values are simple configuration parameters.
- Rotation is externally managed.
- Cost and simple hierarchy matter more than Secrets Manager features.

AWS integration requirements:

- Django and runners use IAM roles, not long-lived AWS keys stored in Django.
- AWS access for secret resolution is scoped by organization/environment/backend profile.
- Backend IAM policy must allow only the configured path prefixes or ARNs.
- KMS keys must be environment-scoped where practical.
- Cross-account access must use STS AssumeRole with external IDs or OIDC, not copied static credentials.
- Backend refs may be ARNs or parameter names, but normal UI should show logical references.
- CloudTrail should record backend access by the platform or runner role.
- The backend should prefer short-lived cloud credentials through OIDC or STS for target access where possible instead of storing static cloud keys.

Recommended AWS path layout:

```text
/runbook-platform/{org_slug}/{environment}/{credential_class}/{namespace}/{name}
```

Examples:

```text
/runbook-platform/acme/production/target/aws/deploy-role
/runbook-platform/acme/production/integration/pagerduty/routing-key
/runbook-platform/acme/staging/target/database/reporting-password
```

AWS fail-closed cases:

- Backend unavailable.
- IAM access denied.
- KMS decrypt denied.
- Secret pending deletion.
- Version selector not found.
- Secret environment tag does not match Django environment.
- Secret organization tag does not match Django organization.
- Secret type tag does not match `SecretReference.secret_type`.

## 7. Step-Scoped Injection Flow

Secret access must be gated at step start, not at execution claim.

Required flow:

1. Workflow schema v2 declares top-level secret references and per-step secret aliases.
2. Workflow publish validation confirms each declared reference exists, is active, matches the workflow organization, and is allowed for the declared environment/action type.
3. Execution creation snapshots only reference metadata: aliases, reference IDs, expected usage, and non-secret version selectors.
4. Runner claims an execution through the existing internal API. The claim payload includes no raw secrets.
5. Runner calls the step-start endpoint before every step.
6. Django evaluates ownership, change binding, target locks, windows, freezes, breakglass, approvals, and policies as it does today.
7. Django additionally evaluates secret eligibility for the step:
   - step declares the alias;
   - reference is active;
   - environment matches;
   - runner pool is eligible;
   - target selectors match;
   - action type and usage are allowed;
   - policy does not block;
   - rotation state permits use;
   - backend health is acceptable.
8. If eligible, Django creates a short-lived `SecretAccessGrant` for exactly one execution step, runner, and claim token.
9. Runner receives either:
   - `runner_action="run"` plus a list of opaque grant IDs to fetch through `POST /api/v1/internal/secrets/resolve-step/`; or
   - `runner_action="blocked"` with a safe reason if any secret check fails.
10. Runner resolves grants immediately before sandbox launch.
11. Runner injects material into the sandbox according to declared usage:
   - environment variable with a controlled name;
   - temporary file inside the step workspace with restrictive permissions;
   - HTTP header visible only to a typed `http_request` action handler;
   - provider-native token exchange handled by an action adapter.
12. Runner configures stream and artifact masking with the secret material and known derived forms.
13. Runner clears in-memory and file material after the step completes, times out, is cancelled, or fails setup.
14. Runner reports non-secret injection facts to Django: reference IDs, grant IDs, version IDs, injection modes, and success/failure codes.
15. Django records audit events and updates `last_used_at`; no raw values are stored.

`SecretAccessGrant` proposed fields:

| Field | Purpose |
|---|---|
| `organization` | Tenant boundary. |
| `execution` | Execution being run. |
| `step` | Exact step allowed to receive the secret. |
| `secret_reference` | Reference being accessed. |
| `runner_id` | Canonical runner identity. |
| `runner_pool_id` | Pool at grant time. |
| `claim_token_hash` | Hash of claim token, never raw token. |
| `grant_nonce` | Random nonce for grant token generation. |
| `grant_token_hash` | Hash of opaque resolve token. |
| `status` | `created`, `resolved`, `expired`, `revoked`, `failed`. |
| `expires_at` | Short TTL, for example 60 seconds. |
| `resolved_at` | Set once material is resolved. |
| `backend_version_id` | Safe version identifier returned by backend. |
| `injection_mode` | `env`, `file`, `header`, `token_exchange`, `provider_native`. |
| `safe_error_code` | Non-secret failure code. |

Grant rules:

- A grant can be resolved once.
- A grant expires quickly.
- A grant is bound to runner identity, execution, step, and claim token.
- A stale runner claim cannot resolve a grant.
- A grant is revoked when a step is blocked, cancelled, times out before start, or ownership changes.
- Breakglass can override some policy gates only through existing change-control mechanisms; it must not bypass secret environment or tenant scope.

## 8. Secret Masking and Redaction Expectations

Masking is defense in depth. It does not make it acceptable to persist raw secrets.

Runner masking requirements:

- Build a per-step redaction set before launching the sandbox.
- Include exact secret values and derived variants where practical:
  - trimmed value;
  - JSON-escaped value;
  - shell-escaped value;
  - URL-encoded value;
  - base64 form for short binary tokens where safe;
  - `Authorization: Bearer <token>`;
  - `Basic <base64(username:password)>` when credentials are structured;
  - PEM body chunks for private keys.
- Mask stdout, stderr, runner exception messages, sandbox error text, artifact metadata, integration callback context, and verification result metadata before upload or report.
- Use a consistent placeholder such as `[REDACTED_SECRET:<reference_id>]` or `[REDACTED_SECRET]`; do not leak secret names if that would reveal sensitive target topology.
- Track `redaction_applied=true` and `redaction_match_count` as metadata, but never include matched text.
- Enforce output caps before or during masking to avoid memory exhaustion.
- Treat multiline secrets carefully: match both full block and line fragments.
- If masking fails or redaction configuration cannot be built, fail closed before running the command.

Django masking requirements:

- Django must scrub every inbound runner field that may contain runtime text, including `error_message`, verification `observed_value`, verification `metadata`, artifact `metadata`, and future live log events.
- Django must have value-aware redaction for secrets used in that execution when processing runner-supplied text.
- Django must still keep key-name scrubbers because values may arrive without a known grant context.
- Public serializers must not expose backend refs, grant tokens, raw claim tokens, or raw material fingerprints.

Known limitation:

- Redaction cannot guarantee removal of transformed secrets that are hashed, chunked unusually, encrypted, or embedded in binary artifacts. That residual risk must be explicit in the UI and pilot runbooks, and risky artifacts should require manual review or typed parsers.

## 9. Audit Scrubber Requirements

The existing audit scrubber in `apps/api/apps/audit/services.py` should become a shared hardening point, not just a convenience.

Required changes when implemented:

- Expand forbidden and rejected metadata keys for secret references, access grants, backend refs, credential payloads, and injection records.
- Keep reject-on-key behavior for fields that should never be emitted, such as raw grant tokens, raw claim tokens, raw backend responses, raw requested inputs, raw workflow snapshots with material, and raw secret values.
- Add value-aware scrubber support where the caller supplies a redaction context for an execution or step.
- Make audit emission fail closed when metadata contains rejected secret material.
- Add object types for `secret_reference`, `secret_access_grant`, `secret_rotation`, and `environment` if these models are introduced.
- Audit events must record decisions and outcomes, not values.

Recommended audit events:

| Event | Object | Required safe metadata |
|---|---|---|
| `secret_reference.created` | SecretReference | environment, namespace, name, secret_type, credential_class, backend, status |
| `secret_reference.updated` | SecretReference | changed fields, no backend secret values |
| `secret_reference.disabled` | SecretReference | reason, prior status |
| `secret_reference.validated` | SecretReference | backend, version id, validation status |
| `secret_access_grant.created` | SecretAccessGrant | execution_id, step_id, reference_id, runner_id, injection_mode, expires_at |
| `secret_access_grant.resolved` | SecretAccessGrant | backend version id, resolved_at |
| `secret_access_grant.failed` | SecretAccessGrant | safe error code |
| `secret_access_grant.expired` | SecretAccessGrant | no material facts |
| `secret_rotation.recorded` | SecretReference | previous version id, new version id, rotated_at |

Audit metadata must not include:

- raw secret values;
- decrypted credential JSON;
- backend provider response bodies;
- grant token values;
- claim tokens;
- dispatch tokens;
- full backend paths for non-admin-visible logs;
- command text after secret interpolation;
- generated temporary file paths that include secret names or values.

## 10. Artifact and Log Redaction Expectations

Artifacts and logs are a high-risk leak path because they are designed for retention.

Live logs:

- Runner must redact stdout/stderr before streaming or uploading.
- If a live event stream is added for logs, Django must treat it as untrusted text and apply server-side redaction again.
- The UI must show redaction markers and truncation markers distinctly.
- Operators must not be able to request "raw unredacted logs" from the platform.

Stdout/stderr artifacts:

- Uploaded stdout and stderr artifacts must contain redacted content only.
- Artifact metadata must include non-secret redaction facts:
  - `redaction_applied`;
  - `redaction_match_count`;
  - `stdout_truncated` or `stderr_truncated`;
  - `secret_reference_ids` only if safe for the viewer's permission.
- Checksums are computed over redacted bytes, not raw bytes.

File artifacts:

- Pilot Phase D should avoid attempting generic binary redaction.
- Declared text artifacts may be scanned and redacted by runner before upload.
- Binary artifacts that may contain secrets should be blocked unless the action contract marks them safe or routes them to a quarantined review flow.
- Artifact upload should fail closed if a required text artifact scan finds unredactable secret material.
- Artifact names and paths must not include secret values or backend reference paths.

Evidence:

- Evidence bundles should include only redacted artifacts and safe metadata.
- Evidence manifests must record redaction policy version and redaction status, not raw findings.
- Legal hold and retention must not make raw secret leakage permanent. The platform should prefer rejecting suspect artifacts over sealing them.

## 11. Secret Rotation Expectations

Phase D must make rotation visible and safe even if it does not fully automate every backend.

Rotation model:

- `SecretReference` tracks `last_rotated_at`, `rotation_due_at`, `last_validated_at`, and backend version id.
- `SecretRotationRecord` tracks operator-entered or backend-detected rotation events.
- New step grants should use current backend version unless a workflow has explicitly pinned a version for a validated reason.
- Pinned versions must be rare, visible, and policy-controllable.
- Disabled or retired references cannot create new grants.
- References with overdue rotation can be warned, require approval, or be blocked by policy.

Recommended `SecretRotationRecord` fields:

| Field | Purpose |
|---|---|
| `secret_reference` | Reference rotated. |
| `rotation_type` | `manual`, `backend_detected`, `scheduled`, `emergency`. |
| `previous_version_id` | Safe version id if known. |
| `new_version_id` | Safe version id if known. |
| `rotated_at` | Rotation timestamp. |
| `rotated_by` | User or system actor. |
| `validation_status` | `pending`, `passed`, `failed`. |
| `notes` | Sanitized text only. |

Rotation failure behavior:

- If a secret is in `rotating` and no validated current version exists, fail closed.
- If backend version changes during a long execution, existing step grants may complete with the resolved version, but new steps must resolve according to the current reference state.
- If a backend reports a compromised or disabled version, active grants for that reference should be revoked where possible and future steps blocked.

## 12. Policy Integration Points

Policies must be able to reason about credential access before the runner sees values.

New policy context fields:

- `environment`
- `runner_pool_key`
- `runner_capabilities`
- `target_types`
- `target_identifiers`
- `action_type`
- `secret_reference_ids`
- `secret_namespaces`
- `secret_types`
- `credential_classes`
- `secret_policy_tags`
- `secret_rotation_overdue`
- `secret_access_count_for_step`

Policy rules should support these outcomes:

- `auto_approve`
- `approval_required`
- `block`

Policy use cases:

- Block production target credentials outside production runner pools.
- Require approval for `credential_class=target` and `policy_tags` containing `prod-write`.
- Block static AWS keys for production where STS role assumption is available.
- Require independent approval for SSH private key injection.
- Block secrets with overdue rotation.
- Block secrets from namespaces not allowed by the operation profile.
- Require breakglass review for emergency access to high-privilege credentials.

Important boundary:

- Policy can authorize, require approval, or block access.
- Policy must not return raw secrets, modify secret values, rewrite backend refs, or decide runner-local injection details.
- The final broker decision remains a Django service decision combining policy with tenant, environment, runner, target, workflow, and backend checks.

## 13. Credential Class Separation

Phase D must keep credential classes separate because they have different lifecycles and blast radii.

### Platform Credentials

Examples:

- `DJANGO_SECRET_KEY`
- database password
- Redis password
- artifact object-storage credentials
- OpenAI API key
- metrics bearer token
- change dispatch token signing secret
- integration Fernet key

Rules:

- Managed by deployment infrastructure and platform operators.
- Not visible in product UI.
- Not available to workflows or runner steps.
- Not stored in `SecretReference` unless a future platform-ops module explicitly models them.
- Loaded through environment/IAM/secrets manager into Django or infrastructure services.

### Runner Credentials

Examples:

- runner registration token;
- per-runner bearer token;
- runner's IAM role credentials;
- sandbox provider credentials;
- object storage upload credentials if direct upload is added.

Rules:

- Used only for runner authentication and platform API access.
- Not usable as target credentials.
- Stored locally on the runner only as needed, with rotation and revocation.
- Django stores hashes or metadata, not raw runner tokens.
- Runner credentials cannot grant access to all target secrets by themselves; each target secret still requires a step grant.

### Integration Credentials

Examples:

- Slack webhook URL;
- generic webhook URL;
- PagerDuty routing key;
- ServiceNow API token;
- Jira API token.

Rules:

- Used by Django integration dispatch or inbound sync, not by arbitrary workflow steps.
- Existing `IntegrationConnection.encrypted_credentials` may remain for the current webhook implementation, but Phase D should prefer migrating integration secrets into the common `SecretReference` model over time.
- Integration delivery previews must redact URLs, tokens, headers, and payload secrets.
- Integration credentials have their own permission and rotation UX.

### Target Credentials

Examples:

- AWS deployment role;
- Kubernetes kubeconfig or exec credential;
- database password;
- SSH private key;
- service API token used by an action against a target;
- GitHub deploy token used by a target operation.

Rules:

- Usable only through declared workflow steps and Django-created access grants.
- Environment-scoped and target-scoped.
- Strongly prefer short-lived provider-native credentials such as OIDC or STS over static secrets.
- Never stored in change requested inputs.
- Never exposed to frontend.
- Never embedded into workflow command text.

## 14. Required API, Model, and Schema Changes

This section defines required API, model, and schema changes for a later implementation. Do not implement them from this blueprint without rereading current source.

Backend apps:

- Add a new Django app, likely `apps/api/apps/secrets/`.
- Add `SecretReference`, `SecretAccessGrant`, `SecretRotationRecord`, and optionally `Environment` models.
- Add admin classes that hide backend-sensitive fields by default.
- Add service layer functions for reference CRUD, validation, grant creation, grant resolution, rotation records, and redaction context lookup.
- Add public APIs for secret reference management and safe lookup.
- Add internal runner APIs for grant resolution and secret-use reporting.
- Add audit object types and event emitters.
- Add policy context and rule support.

Suggested public endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/environments/` | List active environments visible to the organization. |
| `GET /api/v1/secrets/references/` | List safe secret reference summaries. |
| `POST /api/v1/secrets/references/` | Create a reference to an existing backend secret. No raw value in request for production backends. |
| `GET /api/v1/secrets/references/{id}/` | Detail view with safe metadata. |
| `PATCH /api/v1/secrets/references/{id}/` | Update metadata, status, allowed scopes, and rotation expectations. |
| `POST /api/v1/secrets/references/{id}/validate/` | Validate backend reachability without exposing value. |
| `POST /api/v1/secrets/references/{id}/disable/` | Disable future grants. |
| `POST /api/v1/secrets/references/{id}/rotation-records/` | Record or validate a rotation event. |
| `GET /api/v1/secrets/references/resolve-options/` | Safe picker data for workflow authors. |

Suggested internal endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/internal/secrets/resolve-step/` | Resolve one or more step grants for the authenticated runner and claim token. |
| `POST /api/v1/internal/secrets/grants/{id}/used/` | Optional runner callback with safe injection facts. |
| `POST /api/v1/internal/secrets/grants/{id}/failed/` | Optional runner callback with safe failure code. |

Workflow schema v2:

- Add top-level `secrets` declarations.
- Add per-step `secrets` alias references.
- Validate alias uniqueness.
- Validate that `envName` and file mount names are safe identifiers.
- Reject inline `value`, `password`, `token`, `secret`, `privateKey`, or similar fields in workflow JSON.
- Reject secret interpolation into `command`, for example `${{ secrets.foo }}` in command text for pilot shell actions. Prefer environment or file injection.
- Include secret declarations in publish-time compatibility checks.

Execution models:

- Keep `Execution.workflow_snapshot` and `ExecutionStep.step_snapshot` reference-only.
- Add optional denormalized non-secret fields if needed, such as `declared_secret_reference_ids`.
- Do not add raw secret fields to `Execution`, `ExecutionStep`, or `ChangeRecord`.

Runner schemas:

- Extend step-start response with grant summaries, not values.
- Add Pydantic models using secret-safe representations. `SecretStr` is not enough if serializers still send values to logs; use explicit no-`repr` discipline and safe model dumps.
- Add internal client methods for grant resolution.

Settings:

- `SECRET_BACKEND`
- `SECRET_LOCAL_DEV_ROOT` or `SECRET_LOCAL_DEV_ENV_PREFIX`
- `SECRET_AWS_REGION`
- `SECRET_AWS_SECRETS_MANAGER_PREFIX`
- `SECRET_AWS_SSM_PREFIX`
- `SECRET_GRANT_TTL_SECONDS`
- `SECRET_MAX_PER_STEP`
- `SECRET_MASKING_REQUIRED`
- `SECRET_ROTATION_WARNING_DAYS`

Production settings must fail closed if `SECRET_BACKEND` is unset or set to `local_dev`.

## 15. Required Frontend UX

The UI must make secret references usable without exposing values.

Required screens:

- Environment list and detail, if an environment model ships in this phase.
- Secret reference list filtered by organization, environment, namespace, status, type, owner, and rotation state.
- Secret reference create/edit form for metadata and backend pointer. Production UI should not accept raw secret values; it should link to external backend setup instructions.
- Secret reference validation action that shows pass/fail and safe error codes.
- Rotation status view with last rotated, due date, current backend version label, and validation status.
- Workflow editor secret picker that inserts references by alias, not values.
- Workflow review page that shows which steps require which references, their environments, credential classes, and policy tags.
- Change create/detail views that show required secret references and readiness status without values.
- Execution detail view that shows per-step secret access outcomes: grant created, resolved, blocked, expired, redacted, with safe reference labels.
- Audit views that include secret events while preserving secret-admin permission boundaries.

UX rules:

- Never render raw secret values.
- Never render masked values that preserve length or partial suffixes by default.
- Do not provide "copy secret" behavior.
- Backend refs and provider ARNs should be hidden from non-admin workflow authors.
- Make environment mismatch and rotation overdue states obvious before dispatch.
- Show fail-closed blocks as operationally actionable safe reasons, for example `secret_rotation_overdue` or `runner_pool_not_allowed`.
- Make credential class visible so users understand whether they are configuring platform, runner, integration, or target credentials.

Permissions:

- `secret_admin`: create/update/disable references and backend refs.
- `secret_viewer`: view safe metadata only.
- `workflow_author`: select allowed references for workflows.
- `operator`: view secret access outcomes for executions.
- `auditor`: view access decisions and evidence metadata, not backend refs or values.

## 16. Required Tests

Backend model tests:

- Unique active `(organization, environment, namespace, name)`.
- Invalid namespace/name rejected.
- Credential class and secret type constraints.
- Disabled references cannot create grants.
- Environment mismatch fails closed.
- Backend refs not serialized in non-admin responses.
- Raw values cannot be stored in reference metadata.

Workflow/schema tests:

- v2 secret aliases validate.
- Duplicate aliases rejected.
- Inline secret values rejected by schema and semantic validation.
- Per-step undeclared aliases rejected.
- Unsafe env var names and file mount paths rejected.
- Existing v1 workflows remain compatible.

Broker/service tests:

- Step grant created only after runner ownership and step-start gate pass.
- Grant cannot be resolved by wrong runner, wrong claim token, wrong step, expired token, disabled reference, wrong pool, wrong environment, or wrong target.
- Grant is one-time use.
- Backend failure blocks before command execution.
- Policy block prevents grant creation.
- Approval-required flow creates grants only after approval is granted.
- Breakglass cannot bypass tenant or environment mismatch.

Runner tests:

- Runner claim payload contains no raw secrets.
- Runner resolves grants only after `runner_action="run"`.
- Environment variable injection uses controlled names.
- File injection writes inside workspace only with restrictive permissions.
- Cleanup removes injected files after success, failure, timeout, and setup error.
- Redaction masks stdout, stderr, exception text, and artifact metadata.
- Redaction setup failure fails closed before process launch.
- Unsupported secret usage mode fails closed.

Audit tests:

- Secret management events emit safe metadata.
- Grant created/resolved/failed events emit safe metadata.
- AuditService rejects raw grant tokens and suspicious secret keys.
- Value-aware scrubber removes known step secret values from nested metadata.
- Audit rollback behavior remains correct if scrubber rejects metadata.

Artifact/log tests:

- Stdout/stderr uploaded after redaction.
- Checksums are for redacted bytes.
- Artifact metadata includes redaction facts but no matched values.
- Text file artifacts containing injected secrets are redacted or rejected according to action policy.
- Binary artifacts that are not declared safe are blocked or quarantined.

API tests:

- Public secret endpoints enforce organization scoping and permissions.
- Internal resolve endpoint rejects user JWTs and accepts only authenticated runners.
- Internal resolve endpoint rejects stale claim tokens.
- Public serializers never expose `backend_ref`, token hashes, grant tokens, or values to unauthorized roles.

Frontend tests:

- Secret lists never render raw values or backend refs for normal users.
- Workflow secret picker submits reference IDs/aliases only.
- Execution detail shows safe access status.
- Rotation overdue and validation failure states are visible.
- Permission-gated controls hide admin actions.

Operational tests:

- Production settings fail closed without a real secret backend.
- Local dev backend is rejected under production settings.
- AWS backend access denied, KMS denied, missing secret, invalid version, and throttling map to safe failure codes.
- Rotation state change blocks new grants when required.

## 17. Operational Risks

Major risks:

- Secret leakage through logs, artifacts, audit metadata, integration payloads, live stream events, exception text, or browser-visible JSON.
- Overbroad AWS IAM allowing the platform or runner to read unrelated secrets.
- Confused environment mapping where staging workflows receive production credentials.
- Runner compromise after a step receives target credentials.
- Workflow authors using shell interpolation patterns that print secrets.
- Long-lived static cloud keys persisting because they are easier than STS/OIDC.
- Redaction bypass through transformed, encoded, chunked, or binary secret content.
- Backend outage blocking production operations.
- Rotation changes breaking workflows without preflight validation.
- Credential class confusion, especially integration webhook URLs reused as target secrets or runner IAM roles reused for target access.
- Excessively detailed UI/audit metadata revealing sensitive target topology.

Mitigations:

- Default to no secret access.
- Prefer short-lived provider-native credentials.
- Keep grants step-scoped and short-lived.
- Require declarations in workflow schema v2.
- Enforce environment and runner pool eligibility in Django.
- Redact on runner and Django.
- Reject suspect artifacts rather than retaining them.
- Validate references at workflow publish and dispatch preflight.
- Add policy gates for privileged and overdue credentials.
- Keep platform, runner, integration, and target credentials separate in model, UI, permissions, and documentation.

## 18. Rollout Strategy

Phase D should roll out in controlled increments.

1. Add secret reference registry and local/dev backend.
   - Create reference metadata, validation, safe serializers, and audit events.
   - Prove zero raw persistence with unit tests.

2. Add workflow schema v2 secret declarations.
   - Validate aliases and per-step references.
   - Keep v1 compatibility.
   - Block inline secret values.

3. Add brokered grant lifecycle.
   - Create grants during step-start after existing Django gates.
   - Add one-time internal resolve endpoint.
   - Keep claim payload secret-free.

4. Add runner injection and masking.
   - Support env and file modes only for pilot.
   - Redact stdout/stderr before artifact upload.
   - Fail closed when masking cannot be configured.

5. Add AWS backend.
   - Start with one environment and one narrow namespace.
   - Use IAM roles and path-scoped access.
   - Validate CloudTrail and KMS behavior.

6. Add UI and policy integration.
   - Secret reference management, workflow picker, execution access status, and policy conditions.
   - Add rotation visibility before enforcing rotation blocks.

7. Pilot one target credential.
   - One organization.
   - One production environment.
   - One runner pool.
   - One action type.
   - One or two target secrets.
   - Run success, denied, missing secret, backend unavailable, redaction, artifact leak, rotation, cancellation, and runner crash scenarios.

Exit gate:

- A real pilot step can use a scoped target credential without raw secret persistence and without leaking it into logs, artifacts, audit events, public APIs, execution snapshots, or workflow definitions.
- Any missing permission, backend failure, environment mismatch, runner mismatch, policy block, or redaction failure prevents command execution.

## 19. Explicit Non-Goals

Out of scope for Phase D:

- Building a full enterprise vault product.
- Replacing AWS Secrets Manager, SSM Parameter Store, HashiCorp Vault, or cloud-native identity systems.
- Storing raw production secrets encrypted in the Django database as the primary production mechanism.
- Letting workflow authors paste raw credentials into workflow definitions, change requested inputs, or UI forms for production use.
- Frontend retrieval or display of secret values.
- Runner-local unrestricted access to all organization secrets.
- Direct runner-to-database secret lookup.
- Secret access outside the Django-authorized step-start and grant flow.
- Generic binary artifact redaction guarantees.
- Automated rotation for every backend and credential type.
- Customer-managed external vault integrations beyond the initial abstraction direction.
- Cross-organization secret sharing.
- Environment inheritance where production secrets can be implicitly used by staging or development.
- Bypassing policy, approval, target lock, window, freeze, change binding, or runner pool checks in the name of credential access.

## Architecture Invariants

These invariants are non-negotiable:

- Django remains the control-plane authority for references, eligibility, grants, state transitions, policy decisions, audit events, and public/internal API contracts.
- Runner talks only to Django internal APIs.
- React talks only to Django public APIs.
- The AI service may suggest references but must never resolve, store, or broker secrets.
- Zero raw secret persistence: raw secrets are never persisted in platform-controlled storage.
- Fail-closed behavior: secret access fails closed whenever authorization, backend resolution, masking, environment matching, or runner ownership is uncertain.
- Secret access is step-scoped, environment-scoped, runner-bound, and auditable.
- The platform distinguishes platform credentials, runner credentials, integration credentials, and target credentials at every layer.
