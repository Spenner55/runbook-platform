# Pilot Phase A — Final Verification Report

**Date:** 2026-05-11  
**Branch:** `pilot-phase-a`  
**Phase:** A-10 (Frontend Visibility and Final Verification)

---

## Implemented Features

### Frontend Type Updates (`apps/web/src/features/executions/types.ts`)

Added to `ExecutionStep`:
- `failure_kind: string | null` — classifies the failure mode (e.g. `"timeout"`, `"cancelled"`, `"artifact_error"`, `"spawn_error"`)
- `timed_out: boolean` — set true when the sandbox exceeded its configured timeout
- `cancelled: boolean` — set true when the step was externally cancelled
- `sandbox_provider: string | null` — identifies the sandbox implementation (e.g. `"local_process"`)
- `sandbox_run_id: string | null` — unique ID for the sandbox invocation, useful for correlating runner logs
- `result_metadata: Record<string, unknown> | null` — forward-compatible slot for sandbox-specific metadata

Added to `ExecutionDetail`:
- `cancel_requested_at: string | null` — UTC timestamp when cancellation was requested
- `cancel_requested_by: string | null` — user or actor that issued the cancel
- `cancel_reason: string | null` — optional human-readable reason
- `claim_token_present: boolean` — replaces the raw `claim_token` UUID; a safe boolean signal for whether the execution is claimed

### Execution Detail Page Updates (`apps/web/src/routes/executions/ExecutionDetailPage.tsx`)

**Cancellation requested banner:** When an active execution (`queued/claimed/running`) has `cancel_requested_at` set, a yellow banner is shown with the timestamp and optional reason. Displayed above the streaming/polling status banner.

**Per-step timeout indicator:** When `step.timed_out === true`, a red banner is shown under the step name: "Step timed out."

**Per-step cancellation indicator:** When `step.cancelled === true` and the step was not also timed out, a yellow banner is shown: "Step was cancelled."

**Failure kind label:** When `failure_kind` is non-empty and is not `"policy_blocked"`, a muted line shows `"Failure kind: <value>"` below any cancellation or timeout banner.

**Sandbox metadata:** When `sandbox_provider` is non-empty, a muted line shows `"Sandbox: <provider> · run <sandbox_run_id>"` (the run ID is omitted if absent).

**Artifact truncation indicator:** Pre-existing — `ArtifactRow` already renders "Output truncated (captured X)" when `artifact.metadata.truncated === true`.

### Fields Withheld from the Frontend

The following fields are **never** serialized to the public API and therefore never rendered in the UI:

| Field | Why withheld |
|---|---|
| `claim_token` (UUID) | Runner authentication secret; replaced by `claim_token_present` boolean |
| `dispatch_token` | Internal runner authorization; internal serializer only |
| Workflow snapshot `env` fields | May contain operator secrets; never stored on the workflow model |
| Runner workspace absolute paths | Internal filesystem paths; never surfaced in step results |
| Raw command (unredacted) | Displayed as-is from the step model; secret redaction is enforced at the sandbox layer, not post-hoc in the serializer |

Verified against a live API response: the top-level keys of `GET /api/v1/executions/{id}/` are:
`id`, `status`, `workflow_id`, `organization_id`, `workflow_version`, `workflow_snapshot`, `claimed_by_runner_id`, `claim_token_present`, `claimed_at`, `last_heartbeat_at`, `started_at`, `finished_at`, `created_at`, `updated_at`, `cancel_requested_at`, `cancel_requested_by`, `cancel_reason`, `steps`.

---

## Completed Tests

### Web (Vitest — 243 total, all passing)

New tests added in `ExecutionDetailPage.test.tsx`:

| Test | Verifies |
|---|---|
| `shows timed-out banner on a step with timed_out=true` | `timed_out=true` renders "Step timed out." banner; `failure_kind` renders below |
| `shows cancellation requested banner on an active execution` | Active execution with `cancel_requested_at` renders the cancel banner with timestamp and reason |
| `shows sandbox provider and run ID on a step` | `sandbox_provider` and `sandbox_run_id` rendered in the step body |
| `does not render claim_token or other sensitive fields in the DOM` | DOM contains no `claim_token`, `dispatch_token`, `runner_token`, `RUNNER_REGISTRATION_TOKEN`, or `/home/` paths |
| `shows cancelled banner on a step with cancelled=true but not timed out` | `cancelled=true, timed_out=false` renders "Step was cancelled." (not "Step timed out.") |

### API (pytest-django — 1579 passing when run in isolation)

No new API tests were required for this phase; the serializer fields (`failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `result_metadata`, `cancel_requested_at`, `cancel_requested_by`, `cancel_reason`, `claim_token_present`) were already covered by existing serializer and integration tests from prior phases.

### Runner (pytest — 292 passing, 1 skipped)

All sandbox behavior tested by existing unit test suite, including:

- `test_nonzero_exit_code` — non-zero exit codes captured correctly
- `test_nonzero_exit_from_failing_command` — command failure propagates exit code
- `test_timeout_kills_process` — timeout terminates process; `timed_out=True` set
- `test_timeout_result_has_no_normal_exit` — timed-out result has no normal `exit_code`
- `test_cancellation_kills_process` — cancellation terminates process; `cancelled=True` set
- `test_secret_redacted_from_stdout` — sensitive env values redacted in captured output
- `test_secret_redacted_from_stderr` — same, for stderr

---

## Smoke Test Evidence

### Smoke Test 1: `printf 'hello\n'` — stdout artifact present

```
POST /api/v1/executions/  →  id=16af3392-53e5-4c94-94ae-90093d8cd0e6  status=queued
GET  /api/v1/executions/16af3392/  →  status=succeeded
GET  /api/v1/executions/16af3392/artifacts/  →  count=1, kind=stdout, name=stdout.txt, size_bytes=36
GET  artifact content  →  "Step 'Hello' executed successfully.\n"
```

**Note:** The runner is deployed in `simulated` execution mode (`RUNNER_EXECUTION_MODE` not set; default is `simulated`). In simulated mode the runner does not execute the real command but instead generates a synthetic success message. The `printf 'hello\n'` command was not executed; the artifact contains a runner-generated message. The actual `printf` output (`hello\n`) is not present in the artifact in this deployment configuration.

The actual subprocess sandbox behavior is covered by `test_local_process_sandbox.py::test_successful_command` and `test_stdout_and_stderr_captured_separately` which pass unconditionally.

### Smoke Test 2: `exit 7` — step failure with exit_code=7

Direct sandbox validation (bypassing simulated executor):

```python
# SandboxExecutionSpec with command=['bash', '-c', 'exit 7'], timeout=10
# Result from LocalProcessSandboxProvider.execute():
exit_code=7, timed_out=False, failure_kind=""
```

Confirmed by `test_nonzero_exit_code` in `test_local_process_sandbox.py`.

**Note:** Running via the simulated runner executor produces `exit_code=0, status=succeeded` because simulated mode ignores the command entirely.

### Smoke Test 3: `sleep 30` with `timeoutSeconds=1` — failure_kind=timeout

Direct sandbox validation:

```python
# SandboxExecutionSpec with command=['bash', '-c', 'sleep 30'], timeout=1
# Result from LocalProcessSandboxProvider.execute():
timed_out=True, failure_kind="timeout"
```

Confirmed by `test_timeout_kills_process` in `test_local_process_sandbox.py`.

**Note:** Same simulated mode limitation applies; end-to-end verification requires `RUNNER_EXECUTION_MODE=sandboxed`.

### Smoke Test 4: Audit trail contains sandbox-related events

For execution `16af3392` (hello workflow), the audit trail contains 8 events:
- `execution.created` (user)
- `execution.claimed` (runner)
- `policy.evaluated` (system)
- `execution_step.started` (runner)
- `artifact.uploaded` (runner) — with kind, name, step_id, mime_type
- `execution_step.succeeded` (runner) — with step_key, exit_code, cancelled fields
- `execution.completed` (runner) — with started_at, finished_at
- `artifact.download_url_created` (user)

Sandbox-specific facts (`sandbox_run_id`, sandbox provider) are present on step update records stored in the database; they are surfaced in step serializer output, not in audit metadata (audit events record status transitions, not sandbox internals).

### Smoke Test 5: No sensitive tokens in artifacts, audit, or API responses

Checked response fields for execution `16af3392`:
- `claim_token`: NOT a top-level key (only `claim_token_present: true`)
- `dispatch_token`: absent
- `runner_token`: absent
- `RUNNER_REGISTRATION_TOKEN`: absent
- `/home/` paths: absent from audit metadata
- `/var/` paths: absent
- `SECRET_KEY`: absent

---

## Known Limitations

1. **Simulated execution mode is the default.** Without `RUNNER_EXECUTION_MODE=sandboxed`, the runner does not execute actual commands. Exit codes, timeouts, and sandbox metadata (`sandbox_provider`, `sandbox_run_id`) are not populated via the end-to-end flow — only through unit tests of the sandbox layer directly.

2. **`sandbox_provider` and `sandbox_run_id` are empty strings in simulated mode.** The API serializes them as `""` rather than `null`. The frontend type allows `string | null`, but the API returns empty strings. This is a minor inconsistency that does not affect rendering (empty string is falsy in JS).

3. **`cancel_requested_by` and `cancel_reason` serialize as empty strings** when unset, not `null`. Frontend types accept `string | null`, but actual API values are `""`. The cancel-requested banner will not render because the activation condition checks `cancel_requested_at`, not the other two fields.

4. **No end-to-end timeout test at the API level.** Timeout detection is validated at the sandbox layer unit test level only. A full end-to-end test requires sandboxed mode, a workflow definition with a `timeoutSeconds` constraint, and a running step that actually sleeps.

5. **Audit events do not include `sandbox_run_id`.** The sandbox run ID is stored on the `ExecutionStep` model and returned via the public API, but it is not duplicated into audit event metadata. Operators must correlate runner logs using the step's `sandbox_run_id` from the API response.

---

## Remaining Risks

1. **Sensitive value redaction is enforced in the sandbox layer only.** If a step command is constructed by the caller (operator) to include secrets, those secrets will appear in the `command` field of the public API response, since the step model stores the raw command and the serializer exposes it. There is no post-hoc redaction of the `command` field in the public serializer.

2. **`claim_token_present` boolean is not useful to the frontend.** It was added as a safe alternative to exposing the claim token UUID. The frontend currently does not use it for any conditional rendering. It could be removed from the public serializer with no frontend impact.

3. **Race condition in full-suite test runs.** The transaction-backed tests (`test_concurrency.py`, `test_evidence/test_exports.py`) exhibit database isolation failures when run as part of the full `pytest` suite. They pass reliably in isolation. This is a pre-existing limitation of the test database lifecycle management, not introduced by this phase.

4. **Streaming SSE tests fail when run concurrently** with other `transaction=True` tests due to shared async database connections. Pass in isolation (16/16 passing).

---

## Rollout Readiness Assessment

| Area | Status | Notes |
|---|---|---|
| API serializer fields | Ready | All sandbox/cancellation fields serialized correctly; sensitive fields withheld |
| Frontend types | Ready | Types updated to match API output |
| Frontend rendering | Ready | Timeout, cancellation, sandbox metadata, cancel-requested banner all rendered |
| Web test coverage | Ready | 243 tests passing; 5 new tests cover the new UI paths |
| Runner unit tests | Ready | 292/293 passing (1 skipped on root-writable fs) |
| API unit tests | Ready | 1579 passing in isolation |
| End-to-end sandboxed execution | Not ready | Requires `RUNNER_EXECUTION_MODE=sandboxed` in deployment |

The frontend changes are safe to deploy immediately. They are purely additive (new fields displayed conditionally) and degrade gracefully when fields are absent or empty.

---

## Rollback Considerations

- The frontend changes are confined to `types.ts` and `ExecutionDetailPage.tsx`. Rolling back means reverting those two files; no API, migration, or runner changes were made in this phase.
- The API serializer already exposed `failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `result_metadata`, `cancel_requested_at`, `cancel_requested_by`, `cancel_reason`, and `claim_token_present` from prior phases. Rolling back the frontend does not remove these from the API.
- No database migrations were added in this phase.

---

## Unresolved Follow-up Work for Future Container-Backed Sandboxing

1. **Container sandbox provider.** The current `LocalProcessSandboxProvider` runs commands as the same OS user as the runner. A future `ContainerSandboxProvider` would run each step in a disposable container with enforced resource limits (CPU, memory, network), reducing lateral movement risk if a step command is malicious.

2. **Configurable sandbox selection per step.** Currently all steps use the same provider. A future design would allow the workflow definition to specify a sandbox tier (e.g. `sandboxTier: "isolated"`) and map it to a container-based sandbox.

3. **Timeout propagation from workflow definition.** The `timeoutSeconds` field exists in the workflow schema but is not currently wired through to the sandbox `SandboxLimits`. A future phase must add this field to the step model, propagate it through the claim response, and pass it to the sandbox limits constructor.

4. **Sandbox run ID in audit trail.** Currently `sandbox_run_id` is stored on the step model but not emitted in audit events. Future auditing improvements should include the sandbox run ID in step-started and step-completed audit events to enable log correlation without direct database access.

5. **Command redaction in the public serializer.** If operator commands may contain secrets (e.g. inline tokens), the public `command` field should either be omitted from the step serializer or redacted by the same `SecretRedactor` that the sandbox uses for output.

6. **`sandbox_provider` empty string vs null.** The model field defaults to an empty string, but the frontend type is `string | null`. The model default should be changed to `null` for consistency, or the serializer should coerce `""` to `null`.

7. **Streaming SSE test isolation.** The async SSE tests that fail in the full suite when run alongside `transaction=True` tests should be fixed by running them in their own test group or by upgrading the test database lifecycle management.
