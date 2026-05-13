# Pilot Phase B Workflow Schema v2

Workflow schema v2 is the pilot execution contract for typed workflow actions. It is additive to v1: existing `workflow.schema.v1` workflows and historical execution snapshots remain valid and executable.

## Supported Action Catalog

Catalog version: `pilot.v1`

| Action | Runner behavior | Notes |
|---|---|---|
| `manual_task` | Acknowledges the already-approved control-plane step. | No shell, HTTP, or secret side effects. |
| `approval_gate` | Acknowledges after Django approval gates permit execution. | Approval state remains owned by Django. |
| `shell_command` | Executes through the configured sandbox provider. | Current schema accepts `params.command`; `params.commandMode`/`argv` is also understood by the runner. |
| `http_request` | Uses the runner HTTP client. | HTTPS only; response status must match `expected_status_codes` when supplied. |
| `artifact_assertion` | Checks declared artifact metadata on the claimed step. | Does not read arbitrary filesystem paths. |

## Failure Kinds

The pilot runner should use these stable failure kinds for v2 action failures:

- `unsupported_action_contract`
- `action_input_invalid`
- `secret_unavailable`
- `sandbox_setup_failed`
- `timeout`
- `action_failed`
- `http_status_unexpected`
- `assertion_failed`
- `required_artifact_missing`
- `policy_blocked`

Cancellation can still appear as `cancelled` from the execution substrate.

## Secret Handling

Workflow definitions may declare secret keys and provider refs, but must not contain raw secret values. Steps reference secret keys only. Until the credential broker phase exists, the runner uses a null secret provider and fails closed with `secret_unavailable` when a v2 step requires a secret.

Secret values must not be stored in workflow definitions, execution snapshots, policy context, audit metadata, artifact metadata, or runner logs. Audit and policy metadata may include secret keys for reviewability.

## Dry Run

Dry run is an execution mode. For v2 actions, `dry_run` validates dispatch inputs and avoids live shell or HTTP side effects. Steps declaring `dryRun.strategy: unsupported` are rejected before a dry-run execution is created. Dry-run results are validation evidence, not proof that a live operation occurred.

## Non-Goals

- No hostile-code sandbox guarantee.
- No real secret brokering or credential federation.
- No Terraform, Kubernetes, database migration, cloud provider, plugin, or arbitrary script action catalog.
- No runner pools or target scheduling.
- No runner-side replacement for Django policy evaluation.
- No AI-generated auto-publish or auto-execute path.
- No automatic migration of existing v1 workflows.
- No rewriting historical execution snapshots.
- No parallel step graphs or conditional branching.

## Known Limitations

- The implementation uses `schemaVersion: "2"` in stored v2 definitions while the Django model field identifies the schema as `workflow.schema.v2`.
- The current shell action schema uses `params.command`; the runner also accepts the blueprint-style `commandMode`/`argv` shape for forward compatibility.
- HTTP egress allowlists are not yet modeled by runner pools.
- Secret refs are validated and fail closed at runtime, but values are not resolved until the credential brokerage phase.
- Required artifact upload failures are limited to declared file artifacts and evidence completeness checks.

## Rollback Plan

1. Disable v2 workflow creation and migration in the API/UI by removing or hiding v2 draft and migration entry points.
2. Keep `workflow.schema.v1` execution enabled. The v1 execution path remains independent of v2 action dispatch.
3. Leave existing v2 execution snapshots immutable for audit history; do not rewrite historical rows.
4. Allow queued v2 executions to drain only if the runner version is known-good; otherwise cancel them and recreate as v1/manual workflows.
5. Re-enable v2 only after validation, runner dispatch, and audit/evidence checks pass in local and pilot environments.
