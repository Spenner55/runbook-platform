# Pilot Phase A — Execution Substrate Implementation Audit

| Field | Value |
|---|---|
| Audit date | 2026-05-11 |
| Branch | `pilot-phase-a` |
| Blueprint | `docs/blueprints/pilot-phase-a-execution-substrate-blueprint.md` |
| Scope | Read-only; no source files modified |

---

## 1. Current Simulated Execution Behavior

### `apps/runner/runner/executor.py` — `_execute_command()` (lines 386–476)

The entire "execution" of a step command is simulated:

```python
# Line 404
should_fail = _FAIL_STEP_MARKER in (step.command or "")

# Lines 443–446 (happy path)
time.sleep(0.5)
finished_at = _utcnow()
stdout_content = f"Step '{step.name}' executed successfully.\n".encode()
stderr_content = b""
```

No subprocess is spawned. The only ways a step can "fail" are:
1. The literal string `FAIL_STEP` appears in `step.command`.
2. An `httpx.HTTPError` is raised by `update_step()`.

The `time.sleep(0.5)` is hardcoded regardless of `RunnerSettings.fake_step_delay_seconds` (which exists in `apps/runner/runner/schemas.py:24` but is never passed to `Executor`).

### `apps/runner/runner/sandbox.py` — Complete stub (line 1–2)

```python
class Sandbox:
    pass
```

This file is entirely empty of behavior. No interface, no methods, no protocol.

---

## 2. Exact Existing API Contracts

All internal runner endpoints are under `/api/v1/internal/`. Authentication is runner bearer token via `RunnerBearerTokenAuthentication`.

### Claim
**`POST /api/v1/internal/executions/claim-next/`**

Request (`ClaimNextRequestSerializer`, `internal_serializers.py:16`):
```json
{ "runner_id": "str", "runner_version": "str", "requested_at": "datetime|null" }
```

Response on work found (`ClaimedExecutionSerializer`):
```json
{
  "execution": {
    "id", "status", "workflow_id", "organization_id", "workflow_version",
    "workflow_snapshot", "claimed_by_runner_id", "claimed_at", "last_heartbeat_at",
    "steps": [
      { "id", "position", "step_key", "name", "step_type", "risk_level",
        "command", "requires_approval", "status" }
    ],
    "change_record_id", "dispatch_token", "requested_inputs_sha256",
    "operation_profile_key", "verification_plan_id", "verification_keys",
    "breakglass"
  },
  "claim_token": "uuid",
  "poll_after_seconds": 5
}
```

Response on empty queue:
```json
{ "execution": null, "poll_after_seconds": 5 }
```

**Critical gap:** `steps` in the claim response does **not** include `step_snapshot`. The blueprint requires `ClaimedStep.step_snapshot` to carry declared artifact specs, timeout, and resource limits to the runner (blueprint §16, schemas §3.9).

### Heartbeat
**`POST /api/v1/internal/executions/{execution_id}/heartbeat/`**

Request (`HeartbeatSerializer`, `internal_serializers.py:196`):
```json
{ "runner_id", "claim_token", "observed_status", "sent_at" }
```

Response (`internal_views.py:160`):
```json
{ "execution_id", "status", "last_heartbeat_at" }
```

**Critical gap:** Response does not include `cancel_requested` or `cancel_reason`. Blueprint §10 and §16 require the heartbeat response to carry cancellation intent.

### Step Start
**`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/start/`**

Request (`StepStartSerializer`, `internal_serializers.py:234`):
```json
{ "runner_id", "claim_token", "sent_at" }
```

Response when `runner_action=run`:
```json
{ "execution_id", "execution_status", "step": {"id", "status"}, "runner_action": "run", "poll_after_seconds": 0 }
```

Response when `runner_action=wait_for_approval`:
```json
{ ..., "runner_action": "wait_for_approval", "approval_request": {...}, "poll_after_seconds": 5 }
```

Response when `runner_action=blocked`:
```json
{ ..., "runner_action": "blocked", "policy_evaluation": {...}, "poll_after_seconds": 0 }
```

This endpoint is fully implemented and includes breakglass override logic (`internal_views.py:329–410`).

### Approval Status Poll
**`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/approval-status/`**

Request:
```json
{ "runner_id", "claim_token", "observed_step_status", "sent_at" }
```

Response:
```json
{ "execution_id", "execution_status", "step_id", "step_status",
  "approval_request", "runner_action": "wait|run|fail", "poll_after_seconds" }
```

Fully implemented.

### Step Update
**`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`**

Request (`StepUpdateSerializer`, `internal_serializers.py:205`):
```json
{
  "runner_id", "claim_token",
  "status": "succeeded|failed|skipped",
  "started_at", "finished_at", "exit_code", "error_message"
}
```

Response:
```json
{ "execution_id", "step": {...}, "execution_status" }
```

**Gap:** The serializer accepts no sandbox result fields (`failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `command_sha256`, `result_metadata`). Blueprint §16 requires these as optional fields.

### Artifact Upload (Step-scoped)
**`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/`**

Multipart form. Handled by `InternalStepArtifactUploadView` (`apps/api/apps/artifacts/internal_views.py:30`). Delegates to `artifact_services.create_from_runner_upload()` which validates:
- Runner ownership via claim token
- Change binding readiness
- Execution not terminal
- Kind is valid (`stdout`, `stderr`, `file`, `report`, `diagnostic`)
- File size ≤ `ARTIFACT_MAX_UPLOAD_BYTES`
- Runner daily quota
- Per-execution total quota
- Per-step artifact count
- Checksum verification (SHA-256)
- MIME type allowlist
- Metadata size

Also exists: **`POST /api/v1/internal/executions/{execution_id}/artifacts/`** (execution-scoped, step=None).

### Complete Execution
**`POST /api/v1/internal/executions/{execution_id}/complete/`**

Request (`ExecutionCompleteSerializer`, `internal_serializers.py:219`):
```json
{ "runner_id", "claim_token", "final_status": "succeeded|failed", "finished_at", "error_message" }
```

**Gap:** `final_status` does not accept `"cancelled"`. Blueprint §10 requires `CompleteExecutionRequest.final_status` to support `"cancelled"`.

---

## 3. Existing Artifact Upload Behavior

### Runner side (`apps/runner/runner/artifact_uploader.py`)

`ArtifactUploader` exposes:
- `upload_stdout(step_id, content: bytes) -> ArtifactUploadResponse | None`
- `upload_stderr(step_id, content: bytes) -> ArtifactUploadResponse | None`

Both delegate to `_upload_stream()` → `_upload_bytes()`. Capabilities:
- SHA-256 checksum computation (line 121)
- 5 MB cap for stdout/stderr; 50 MB cap for other kinds (lines 25–26)
- Truncation metadata (`truncated`, `original_size_bytes`, `captured_size_bytes`, `truncation_reason`) — already implemented at lines 37–44
- 2-attempt retry with 1-second backoff for 5xx/network errors (lines 130–216)
- Non-retryable on 4xx (line 153)

**Gap:** No `upload_file(step_id, path, kind, name, mime_type, metadata)` method. Blueprint §9 requires this for declared file artifact collection.

**Gap:** No sandbox metadata is currently attached (`sandbox_provider`, `sandbox_run_id`, `step_key`, `artifact_source_path`, `redaction_applied`, `collection_status`).

### Django side

- `create_from_runner_upload()` writes to local filesystem via `ArtifactStorage` (currently `ARTIFACT_STORAGE_BACKEND=local` only; S3 not implemented, `storage.py:24`).
- Emits `artifact.uploaded` audit event.
- Storage key format: `artifacts/org/{org_id}/execution/{exec_id}/step/{step_id}/artifact/{artifact_id}/{safe_name}`.

---

## 4. Existing Cancellation Support

### What exists (`apps/api/apps/executions/services.py:154`)

`cancel_execution()` transitions `queued → cancelled` only:
```python
if execution.status != Execution.Status.QUEUED:
    raise InvalidStateTransitionError(...)
```

`claimed` and `running` executions **cannot** be cancelled through the existing public API.

### What is missing for Phase A

The `Execution` model (`models.py`) has no cancellation intent fields:
- No `cancel_requested_at`
- No `cancel_requested_by`
- No `cancel_reason`

The heartbeat response does not carry `cancel_requested`. The runner has no cancellation token mechanism. The `_HeartbeatThread` (`executor.py:28`) has no path to signal the executor to stop a running subprocess.

Blueprint §10 requires all of the above. This is a complete gap — zero implementation exists for active cancellation.

---

## 5. Existing Test Coverage

### Runner tests (`apps/runner/runner/tests/`)

| File | Coverage |
|---|---|
| `test_executor.py` | 20 tests: happy path, step ordering, FAIL_STEP, approval flow, artifact ordering, verification callbacks, breakglass heartbeat. All test simulated execution only. |
| `test_artifact_uploader.py` | Covers truncation, retry, checksum, quota guard, size guard |
| `test_client.py` | Covers retry logic, per-endpoint contracts |
| `test_schemas.py` | Validates Pydantic model parsing/validation |
| `test_orchestration.py` | Integration-style tests for poller→executor wiring |
| `test_poller.py` | Covers poll interval, claim loop |
| `test_change_binding.py` | Covers change-bound execution binding path |
| `test_runner_breakglass_contract.py` | Covers breakglass facts in claimed execution |
| `test_timing_callbacks.py` | Covers execution-started/finished callbacks |
| `test_shutdown.py` | Covers SIGTERM / shutdown event |
| `test_settings.py` | Covers `RunnerSettings.from_env()` validation |

**Gap:** No test file exists for any sandbox functionality. `test_local_process_sandbox.py` and `test_executor_real_execution.py` are prescribed by the blueprint but absent.

### Django API tests (`apps/api/apps/executions/tests/`)

Well-covered: claim, heartbeat, step update, step start, approval flows, watchdog, concurrency, streaming, audit integration, policy integration. No tests for cancellation intent fields (don't exist yet).

### Artifact tests (`apps/api/apps/artifacts/tests/`)

`test_internal_api.py`, `test_services.py`, `test_public_api.py`, `test_models.py` — coverage for upload path, checksum validation, quota, ownership. These will remain green through Phase A changes as long as new fields are additive.

---

## 6. Drift from the Pilot Phase A Blueprint

This section lists every significant gap between the current codebase and what the blueprint requires.

### Highest-priority gaps (block real execution)

| # | Location | Gap |
|---|---|---|
| G1 | `executor.py:443–446` | `_execute_command()` uses `time.sleep(0.5)` + fake string instead of real subprocess. FAIL_STEP marker is production code. |
| G2 | `sandbox.py:1–2` | Stub class — no `SandboxProvider` protocol, no `SandboxExecutionSpec`, no `SandboxResult`, no `LocalProcessSandboxProvider`. |
| G3 | `executor.py` | No `SandboxExecutionSpec` construction. No call to a provider. No stdout/stderr capture from real pipes. |
| G4 | `schemas.py` | `ClaimedStep` has no `step_snapshot` field; artifact specs, timeout, and limits from the workflow definition never reach the runner. |

### Model / migration gaps

| # | Location | Gap |
|---|---|---|
| G5 | `executions/models.py` | `Execution` lacks: `cancel_requested_at`, `cancel_requested_by`, `cancel_reason`. |
| G6 | `executions/models.py` | `ExecutionStep` lacks: `failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `command_sha256`, `result_metadata`. |
| G7 | `executions/models.py` | `ExecutionStep.Status` has no `CANCELLED` variant. |
| G8 | No migration `0008_*` exists | The blueprint prescribes a specific migration for all of the above. |

### API contract gaps

| # | Location | Gap |
|---|---|---|
| G9 | `internal_serializers.py:196` | `HeartbeatSerializer` response (returned by `ExecutionHeartbeatView`) does not include `cancel_requested` or `cancel_reason`. |
| G10 | `internal_serializers.py:205` | `StepUpdateSerializer` has no optional fields for `failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `command_sha256`, `result_metadata`, `stdout_artifact_id`, `stderr_artifact_id`, `artifact_ids`. |
| G11 | `internal_serializers.py:219` | `ExecutionCompleteSerializer` `final_status` choice limited to `["succeeded", "failed"]`; `"cancelled"` not accepted. |
| G12 | `schemas.py` (runner) | `HeartbeatResponse` has no `cancel_requested`/`cancel_reason` fields. |
| G13 | `schemas.py` (runner) | `StepUpdateRequest` has no sandbox result fields to mirror Django's new optional fields. |
| G14 | `schemas.py` (runner) | `RunnerSettings` has no sandbox provider, workspace, timeout, output, artifact, cleanup, redaction config fields. |

### Runner missing files / modules

| # | File | Gap |
|---|---|---|
| G15 | `sandbox/base.py` or `sandbox.py` | No `SandboxProvider` Protocol definition. |
| G16 | `sandbox/local_process.py` | No `LocalProcessSandboxProvider` class. |
| G17 | `sandbox/workspace.py` | No `WorkspaceManager`. |
| G18 | `sandbox/streams.py` | No `StreamCapture` helper. |
| G19 | `sandbox/factory.py` | No provider factory. |
| G20 | `sandbox/redaction.py` | No `SecretRedactor`. |
| G21 | `artifact_uploader.py` | No `upload_file()` method. No sandbox metadata attached to uploads. |

### Cancellation gaps

| # | Location | Gap |
|---|---|---|
| G22 | `services.py:cancel_execution` | Only queued executions can be cancelled. No active cancellation path. |
| G23 | `executor.py:_HeartbeatThread` | Thread has no cancellation token output path. Cannot signal the executor to stop. |
| G24 | Entire runner | No cancellation token class/pattern shared between heartbeat thread and subprocess management. |

### Public API / frontend gaps

| # | Location | Gap |
|---|---|---|
| G25 | `serializers.py:ExecutionStepSerializer` | Does not expose `failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `result_metadata`. |
| G26 | `serializers.py:ExecutionDetailSerializer` | Does not expose cancellation intent fields. |
| G27 | `ExecutionDetailPage.tsx` | No step timeout indicator, no cancellation banner, no failure kind display, no sandbox metadata, no truncation/redaction warning. |

---

## 7. Recommended Implementation Sequence

The blueprint's §20 rollout sequence is sound. Below is a more granular step-by-step order with file-level specificity, optimized to keep existing tests green at each stage.

### Step 1 — Schema prep (Django + runner, no real execution yet)

Files to change:
- `apps/api/apps/executions/models.py`: add `cancel_requested_at`, `cancel_requested_by`, `cancel_reason` to `Execution`; add `failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `command_sha256`, `result_metadata` to `ExecutionStep`; optionally add `CANCELLED` status.
- `apps/api/apps/executions/migrations/0008_*.py`: generate migration.
- `apps/api/apps/executions/internal_serializers.py`: extend `StepUpdateSerializer`, `HeartbeatSerializer` (response field), `ExecutionCompleteSerializer`.
- `apps/api/apps/executions/serializers.py`: extend `ExecutionStepSerializer` and `ExecutionDetailSerializer` with new read-only fields.
- `apps/api/apps/executions/services.py`: extend `update_execution_step()` to accept and persist new optional fields; extend `cancel_execution()` to handle `claimed`/`running` with intent; add `cancel_requested` to heartbeat response.
- `apps/runner/runner/schemas.py`: add `step_snapshot` to `ClaimedStep`; add `cancel_requested`/`cancel_reason` to `HeartbeatResponse`; add sandbox result fields to `StepUpdateRequest`; add sandbox config fields to `RunnerSettings`.
- `apps/api/apps/executions/internal_serializers.py`: add `step_snapshot` to `InternalExecutionStepSerializer`.

Verification after step 1:
```bash
docker compose exec api python manage.py check
docker compose exec api python manage.py showmigrations
docker compose exec api pytest apps/executions apps/artifacts
cd apps/runner && pytest
```

### Step 2 — Sandbox abstraction (runner only, no executor wiring yet)

Files to create:
- `apps/runner/runner/sandbox/base.py`: `SandboxProvider` Protocol, `SandboxLimits`, `SandboxExecutionSpec`, `SandboxResult`, `CapturedStream`, `CollectedArtifact`, `ArtifactSpec`.
- `apps/runner/runner/sandbox/streams.py`: `StreamCapture` — bounded bytearray reader, truncation tracking.
- `apps/runner/runner/sandbox/workspace.py`: `WorkspaceManager` — create/cleanup/resolve/collect.
- `apps/runner/runner/sandbox/redaction.py`: `SecretRedactor` — mask known token values in bytes/strings.
- `apps/runner/runner/sandbox/local_process.py`: `LocalProcessSandboxProvider` implementing the Protocol.
- `apps/runner/runner/sandbox/factory.py`: `get_provider(settings) -> SandboxProvider`.
- Stub `apps/runner/runner/sandbox/__init__.py`.
- Delete body of `apps/runner/runner/sandbox.py` or redirect to package.

Tests to write (new files):
- `apps/runner/runner/tests/test_local_process_sandbox.py`
- `apps/runner/runner/tests/test_workspace.py`
- `apps/runner/runner/tests/test_streams.py`
- `apps/runner/runner/tests/test_redaction.py`

Verification: `cd apps/runner && pytest` — all existing tests still green, new sandbox tests pass.

### Step 3 — Artifact uploader extension

File to change:
- `apps/runner/runner/artifact_uploader.py`: add `upload_file(step_id, path, kind, name, mime_type, metadata)` method; attach sandbox metadata dict to all uploads.

Tests: extend `test_artifact_uploader.py` with file upload cases.

### Step 4 — Executor wiring behind feature flag

Files to change:
- `apps/runner/runner/executor.py`: replace `_execute_command()` body with provider call; introduce `RUNNER_EXECUTION_MODE=simulated|sandboxed`; keep `FAIL_STEP` marker only under `simulated` mode.
- `apps/runner/runner/main.py`: read `RUNNER_EXECUTION_MODE` from settings; pass provider to `Executor`.

New test file:
- `apps/runner/runner/tests/test_executor_real_execution.py`

Verification: existing `test_executor.py` continues to pass with `simulated` mode.

### Step 5 — Cancellation and timeout

Files to change:
- `apps/runner/runner/executor.py`: introduce `CancellationToken`; share between `_HeartbeatThread` and `_execute_command()`; check token before each step and during sandbox execution.
- `apps/runner/runner/sandbox/local_process.py`: accept cancellation token; kill process group on signal.
- `apps/api/apps/executions/services.py`: implement active cancellation intent for `claimed`/`running` executions; expose `cancel_requested` in heartbeat response.
- `apps/api/apps/executions/views.py`: allow cancellation of non-queued executions (with intent model).

Tests: extend `test_executor.py`, `test_services.py`, `test_runner_api.py` for cancellation scenarios.

### Step 6 — Frontend visibility

Files to change:
- `apps/web/src/features/executions/types.ts`: add `failure_kind`, `timed_out`, `cancelled`, `sandbox_provider`, `sandbox_run_id`, `result_metadata` to step type; add cancellation intent fields to execution type.
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`: render timeout indicator, cancellation banner, failure kind, sandbox metadata, truncation warning.
- `apps/web/src/features/artifacts/types.ts`: ensure `metadata.truncated`, `redaction_applied` are typed.

Verification: `cd apps/web && npm run lint && npm run build`; `ExecutionDetailPage.test.tsx`.

### Step 7 — Flip pilot runner, smoke test, remove simulation

- Set `RUNNER_EXECUTION_MODE=sandboxed` on pilot runner.
- Run smoke workflows (printf hello / exit 7 / sleep 30 with timeout).
- Make `sandboxed` the default once stable.
- Quarantine `FAIL_STEP` and `time.sleep` to explicit test fixtures.

---

## 8. Risks and Compatibility Concerns

### Risk 1 — `step_snapshot` absent from claim response
**Severity: High**

The `ClaimedStep` Pydantic model (`schemas.py:99`) has no `step_snapshot`. The `InternalExecutionStepSerializer` (`internal_serializers.py:26`) does not include `step_snapshot`. Artifact specs, timeout, and limits from the workflow definition are never delivered to the runner. Adding this field requires both a Django serializer change (add `step_snapshot` to `InternalExecutionStepSerializer`) and a runner schema change (`ClaimedStep`). The runner `model_config = ConfigDict(extra="ignore")` means adding the field on the Django side will silently be ignored by current runners until the schema is updated too — this allows a rolling deploy.

### Risk 2 — Cancellation of active executions is a state-machine extension
**Severity: High**

`cancel_execution()` in `services.py` raises `InvalidStateTransitionError` for non-queued executions. Adding active cancellation intent must not alter the terminal transition logic. Specifically, the watchdog (`recover_stuck_executions`) and the `complete_execution()` guard must remain authoritative. The heartbeat-carried `cancel_requested` flag should be advisory to the runner, not a direct state write. Django should store the intent but not auto-transition the execution; the runner reports the final terminal status.

### Risk 3 — FAIL_STEP marker is in production executor code
**Severity: Medium**

`_FAIL_STEP_MARKER = "FAIL_STEP"` (`executor.py:20`) and its check at line 404 run on every real step command in production. A workflow step with the string "FAIL_STEP" in its command would trigger the fake failure path even after sandboxed execution is added. This marker must be moved to test fixtures or gated behind `RUNNER_EXECUTION_MODE=simulated`.

### Risk 4 — `fake_step_delay_seconds` setting exists but is not wired
**Severity: Low**

`RunnerSettings.fake_step_delay_seconds` (`schemas.py:25`) is parsed from `RUNNER_FAKE_STEP_DELAY_SECONDS` but `Executor` always sleeps 0.5 seconds regardless. This is not a correctness issue for Phase A (simulation is being replaced) but represents a dead config value.

### Risk 5 — Artifact storage is local filesystem only
**Severity: Medium** (for pilot, acceptable)

`ArtifactStorage` raises `ImproperlyConfigured` if `ARTIFACT_STORAGE_BACKEND != "local"` (`storage.py:24`). Real subprocess output will flow to the same local filesystem. For a pilot on a single machine this is acceptable, but artifacts are not durable across runner restarts. Phase E (durable artifact evidence storage) is the designated resolution.

### Risk 6 — Process-group cleanup on WSL/Docker
**Severity: Medium**

The blueprint requires `os.setsid()` and `os.killpg()` for process-group cleanup. These are POSIX calls. The dev environment is WSL2 (`uname -r` shows `microsoft-standard-WSL2`) and services run in Docker. Behavior of `RLIMIT_NPROC`, `RLIMIT_AS`, and `SIGKILL` to process groups inside Docker may differ from bare Linux. Resource limit tests must explicitly skip or adapt on non-Linux or Docker-container environments. The blueprint acknowledges this at §11.

### Risk 7 — `HeartbeatResponse` schema divergence
**Severity: Low** (initially)

Adding `cancel_requested` to the Django heartbeat response will be silently ignored by running runners until `HeartbeatResponse` in `schemas.py` is updated. The runner `model_config = ConfigDict(extra="ignore")` ensures backward safety. However, this means cancellation is non-functional until both sides are deployed together or the runner is restarted.

### Risk 8 — `StepUpdateRequest` optional fields
**Severity: Low**

Django's `StepUpdateSerializer` uses `required=False` / `allow_null=True` patterns for timing fields. Adding sandbox result fields the same way is backward-safe — old runners sending no sandbox metadata will still succeed. The service `update_execution_step()` must default-blank these fields rather than failing validation.

### Risk 9 — `result_metadata` size / redaction in audit events
**Severity: Medium**

`_emit_step_transition_audit()` in `services.py:1130` currently caps `error_message` to 500 chars (`services.py:1149`). If `result_metadata` or longer error messages from real subprocess failures are included in audit metadata without similar caps, audit event rows could grow large. The blueprint requires explicit redaction and size limits before audit emission.

### Risk 10 — No `step_snapshot` on historical steps
**Severity: Low**

`ExecutionStep.step_snapshot` already exists on the model (`models.py:95`). The gap is only that the runner claim response omits it. Historical execution steps already have the snapshot in the database; adding it to `InternalExecutionStepSerializer` is a non-breaking additive change.

---

*Report generated by read-only audit on 2026-05-11. No source files were modified.*
