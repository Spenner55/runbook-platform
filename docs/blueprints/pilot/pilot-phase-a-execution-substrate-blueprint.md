# Pilot Phase A: Real Sandboxed Execution Substrate Blueprint

| Field | Value |
|---|---|
| Blueprint ID | `pilot-phase-a-execution-substrate` |
| Objective | Replace simulated runner step execution with a fail-closed, auditable, locally sandboxed execution substrate suitable for a narrow pilot. |
| Status | Blueprint only |
| Authored | 2026-05-08 |
| Primary gap | `apps/runner/runner/executor.py` simulates commands; `apps/runner/runner/sandbox.py` is a stub; no safe isolated command execution exists. |

## 1. Architecture Goals

The Phase A execution substrate must make runner execution real without changing the platform boundary:

- Django remains the control plane and state authority.
- The runner talks only to Django internal APIs.
- React talks only to Django public APIs.
- No queue, broker, worker framework, or new service boundary is introduced.
- Every step must call Django's step-start gate before local execution.
- Every terminal step fact must be reported back to Django through existing internal ownership checks.
- Failure must be explicit, observable, and conservative.

Pilot scope is intentionally narrow:

- Execute only `shell_command` / existing command-backed steps on private, trusted runner hosts.
- Isolate each step in a new workspace under a configured runner root.
- Capture stdout, stderr, exit code, start time, finish time, timeout, and sandbox metadata.
- Upload stdout/stderr and declared file artifacts through Django's artifact API.
- Enforce local process-group cleanup, wall-clock timeout, output caps, environment allowlists, file path validation, and best-effort POSIX resource limits.
- Fail closed for unsupported step types, invalid command specs, sandbox setup failures, artifact path escapes, cancellation, policy denial, and timeout.

Phase A is not a full hostile-code sandbox. The local-process provider is acceptable only when the runner host itself is isolated at the VM/container/network level and the pilot workflows are controlled. The design must leave a clean provider boundary for a later container-backed implementation.

## 2. Threat Model

Assume these threats exist:

- A workflow author accidentally or intentionally submits a destructive shell command.
- A command tries to read files outside its step workspace.
- A command tries to write huge files, produce unbounded logs, fork excessively, or run forever.
- A command prints secrets to stdout/stderr or embeds secrets in generated artifacts.
- A command exits non-zero, is killed by timeout, or is killed by cancellation.
- A runner crashes after executing a command but before reporting final status.
- A runner loses API connectivity while a step is running or uploading artifacts.
- A stale runner claim attempts to update or upload after ownership has moved.
- Artifact names or paths attempt traversal.
- A user expects a cancelled execution to stop real local processes, not just update UI state.
- A step's declared behavior differs from what was actually executed.

Trust boundaries:

- Django database is authoritative for workflow snapshots, step state, audit events, ownership, claim tokens, approvals, change binding, and terminal execution state.
- Runner host is trusted infrastructure but not trusted to mutate Django state directly.
- Step subprocess is untrusted relative to the runner process.
- Local-process sandbox is a containment layer, not a complete security boundary.
- Artifacts are untrusted bytes and must be treated as evidence, not as trusted input.

Out-of-scope threats for Phase A:

- Running hostile third-party code on a shared multi-tenant runner.
- Kernel escape prevention.
- Strong network egress policy enforced by the runner process.
- Secret brokering from production vaults.
- Container image provenance and runtime hardening.

## 3. SandboxProvider Abstraction

Create a provider interface in the runner so `Executor` does not know whether a step runs as a local process, in a container, or through a future remote runtime.

Proposed files:

- `apps/runner/runner/sandbox.py` or `apps/runner/runner/sandbox/base.py`
- `apps/runner/runner/sandbox/local_process.py`
- `apps/runner/runner/sandbox/factory.py`
- `apps/runner/runner/sandbox/redaction.py`
- `apps/runner/runner/sandbox/workspace.py`

Expected interface:

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Mapping, Protocol
from uuid import UUID

@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: int
    stdout_max_bytes: int
    stderr_max_bytes: int
    artifact_max_bytes: int
    max_artifacts: int
    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    file_size_bytes: int | None = None
    process_limit: int | None = None

@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    path: str
    kind: str = "file"
    mime_type: str = ""
    required: bool = False

@dataclass(frozen=True)
class SandboxExecutionSpec:
    execution_id: UUID
    step_id: UUID
    step_key: str
    step_type: str
    command: list[str]
    display_command: str
    workspace_root: Path
    environment: Mapping[str, str]
    limits: SandboxLimits
    artifact_specs: list[ArtifactSpec] = field(default_factory=list)
    cancellation_check_interval_seconds: float = 1.0

@dataclass(frozen=True)
class CapturedStream:
    content: bytes
    truncated: bool
    original_size_bytes: int
    captured_size_bytes: int

@dataclass(frozen=True)
class CollectedArtifact:
    spec: ArtifactSpec
    absolute_path: Path
    size_bytes: int
    checksum_sha256: str

@dataclass(frozen=True)
class SandboxResult:
    provider: str
    sandbox_run_id: str
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    failure_kind: str
    error_message: str
    stdout: CapturedStream
    stderr: CapturedStream
    artifacts: list[CollectedArtifact]
    metadata: dict

class SandboxProvider(Protocol):
    name: str

    def validate(self, spec: SandboxExecutionSpec) -> None:
        ...

    def execute(self, spec: SandboxExecutionSpec, cancellation_token) -> SandboxResult:
        ...

    def cleanup(self, spec: SandboxExecutionSpec, result: SandboxResult | None) -> None:
        ...
```

Contracts:

- `validate()` raises a typed runner exception before any subprocess starts.
- `execute()` always returns `SandboxResult` for started subprocesses, including non-zero exit, timeout, and cancellation.
- Provider setup failures are reported as step failures with `failure_kind="sandbox_setup_failed"`.
- Provider cleanup failures are logged and reported in sandbox metadata, but must not hide the actual command result.
- `stdout` and `stderr` in `SandboxResult` must already be redacted and capped.
- Artifact collection must reject absolute paths, `..`, symlinks escaping workspace, device files, sockets, and paths exceeding configured size/count limits.

## 4. Local-Process Sandbox Design

Implement `LocalProcessSandboxProvider` as the first provider.

Proposed class:

- `apps/runner/runner/sandbox/local_process.py::LocalProcessSandboxProvider`

Configuration fields in `RunnerSettings`:

- `sandbox_provider: str = "local_process"`
- `sandbox_workspace_root: str = "/tmp/runbook-runner/workspaces"`
- `sandbox_cleanup_policy: Literal["always", "on_success", "never"] = "always"`
- `sandbox_default_timeout_seconds: int = 300`
- `sandbox_stdout_max_bytes: int = 5_242_880`
- `sandbox_stderr_max_bytes: int = 5_242_880`
- `sandbox_artifact_max_bytes: int = 52_428_800`
- `sandbox_max_artifacts_per_step: int = 20`
- `sandbox_allowed_env_prefixes: list[str] = []`
- `sandbox_allowed_env_names: list[str] = []`
- `sandbox_shell_path: str = "/bin/bash"`
- `sandbox_allow_shell: bool = true`

Execution mechanics:

- Create a per-step workspace:
  - root: `{sandbox_workspace_root}/{execution_id}/{step_position}-{step_key}-{step_id}/`
  - subdirs: `work/`, `artifacts/`, `tmp/`
  - permissions: `0700`
- Run the command with `cwd=workspace/work`.
- Default command mode for existing schema is shell mode:
  - `["/bin/bash", "-euo", "pipefail", "-c", step.command]` is not valid because `bash -c` does not accept `pipefail` as a direct option.
  - Use `["/bin/bash", "-c", "set -euo pipefail\n" + step.command]`.
- Future typed schema should prefer argv mode:
  - `command: ["terraform", "plan", "-out", "../artifacts/tfplan"]`
  - no shell interpolation unless `shell: true` is explicitly declared.
- Start subprocess in a new process group/session.
- Stream stdout/stderr concurrently to bounded buffers.
- Enforce wall-clock timeout in the runner even when POSIX `resource` limits are unavailable.
- On timeout or cancellation:
  - send `SIGTERM` to the process group;
  - wait a short grace period, default 5 seconds;
  - send `SIGKILL` to the process group if still alive;
  - mark result as `timed_out=True` or `cancelled=True`.
- On Linux, apply best-effort `resource.setrlimit` in `preexec_fn`:
  - `RLIMIT_CPU`
  - `RLIMIT_FSIZE`
  - `RLIMIT_NPROC` when supported and meaningful for the runner user
  - `RLIMIT_AS` only if validated against Python/subprocess behavior in the target environment
- Set environment to an allowlisted map:
  - include safe baseline: `PATH`, `HOME` pointing inside workspace, `TMPDIR`, `LANG`, `LC_ALL`
  - do not inherit full `os.environ`
  - inject no secrets in Phase A unless a future secret-reference contract is implemented
- Set file creation mask to avoid world-readable files.

Fail-closed cases:

- Empty command.
- Unsupported `step_type`.
- Workspace path escapes configured root.
- Workspace creation fails.
- Shell disabled but command requires shell mode.
- Command exceeds timeout.
- Output reader crashes.
- Artifact collection finds an unsafe path.
- Required artifact is missing.
- Provider is unavailable on the current platform.

## 5. Future Container-Backed Sandbox Direction

Phase B should add `ContainerSandboxProvider` without changing `Executor`.

Proposed file:

- `apps/runner/runner/sandbox/container.py`

Expected direction:

- Runtime: Docker for local/staging, then a hardened production runtime chosen during infrastructure work.
- One container per step.
- Read-only root filesystem.
- Writable workspace mounted at `/workspace`.
- Artifact directory mounted at `/workspace/artifacts`.
- Drop Linux capabilities by default.
- No privileged mode.
- User namespace or non-root user.
- CPU/memory/pids limits enforced by runtime.
- Network mode configurable by runner pool and environment, default deny for high-risk steps.
- Image allowlist configured in Django and enforced by the runner.
- Container image digest captured in result metadata.

Container contract additions:

- `sandbox_image`
- `image_digest`
- `network_policy_key`
- `mounts`
- `runtime_resource_limits`
- `container_id`

Do not implement container support in Phase A unless the local-process provider is already complete and tested. The abstraction must make container support additive.

## 6. Step Execution Lifecycle

The runner lifecycle must remain sequential and state-authoritative through Django:

1. `Poller` calls `ApiClient.claim_next()`.
2. Django atomically claims one queued execution and returns execution snapshot, steps, and claim token.
3. `Executor.run()` starts heartbeat.
4. For each non-terminal step:
   - call `ApiClient.start_step()`;
   - if Django returns `wait_for_approval`, poll approval status;
   - if Django returns `blocked`, do not execute;
   - if Django returns `run`, build `SandboxExecutionSpec`.
5. Runner validates and executes through `SandboxProvider`.
6. Runner uploads stdout/stderr artifacts before terminal step update.
7. Runner uploads declared file artifacts before terminal step update.
8. Runner calls `ApiClient.update_step()` with:
   - `status`
   - `started_at`
   - `finished_at`
   - `exit_code`
   - `error_message`
   - future sandbox result fields after API/schema changes are added
9. If step failed, stop subsequent steps and complete execution as failed.
10. If all runnable steps succeeded or were skipped, complete execution as succeeded.
11. For change-bound executions, preserve existing bind, execution-started, execution-finished, breakglass heartbeat, and verification-result callbacks.

Important sequencing rule:

- Artifacts must be uploaded before terminal step update, matching existing `Executor._upload_step_outputs()` behavior. If artifact upload fails, the step outcome may still be reported, but the failure must appear in step result metadata and audit/log events.

## 7. Workspace Isolation Model

Workspace service:

- `apps/runner/runner/sandbox/workspace.py::WorkspaceManager`

Responsibilities:

- Build workspace paths from execution and step IDs.
- Create directories with `0700`.
- Resolve all paths under the configured root.
- Provide helper methods:
  - `create_workspace(spec) -> Workspace`
  - `resolve_workspace_path(workspace, relative_path) -> Path`
  - `collect_artifacts(workspace, artifact_specs, limits) -> list[CollectedArtifact]`
  - `cleanup_workspace(workspace, policy) -> None`

Workspace layout:

```text
{RUNNER_SANDBOX_WORKSPACE_ROOT}/
  {execution_id}/
    {step_position}-{step_key}-{step_id}/
      work/
      artifacts/
      tmp/
      meta/
```

Rules:

- Commands run only from `work/`.
- Declared file artifacts must be relative to either `work/` or `artifacts/`.
- `HOME` and `TMPDIR` must point inside the step workspace.
- Symlinks are allowed only if their final resolved target remains inside the workspace.
- Cleanup default is `always`; `never` is for debugging only and must be clearly marked unsafe in config docs.
- Workspace path and cleanup policy should be included in runner logs, but never exposed as a public API absolute host path.

## 8. stdout/stderr Capture Model

Current runner uploads synthetic stdout/stderr through `ArtifactUploader`. Phase A keeps the same upload path but replaces content with real captured streams.

Capture requirements:

- Capture stdout and stderr separately.
- Read streams concurrently to avoid deadlock.
- Enforce per-stream byte caps before upload.
- Mark truncation in artifact metadata:
  - `truncated`
  - `original_size_bytes`
  - `captured_size_bytes`
  - `truncation_reason`
- Redact before storing in memory beyond the bounded buffer where feasible.
- Preserve binary-safe bytes but upload as `text/plain; charset=utf-8` for stdout/stderr using current artifact normalization.

Recommended implementation:

- Add `StreamCapture` helper under `apps/runner/runner/sandbox/streams.py`.
- Read from pipes in fixed-size chunks.
- Keep a bounded `bytearray`.
- Track total bytes seen separately from bytes retained.
- Do not log raw command output through runner logs.

## 9. Artifact Upload Flow

Existing Django upload path remains the canonical flow:

- `apps/runner/runner/artifact_uploader.py`
- `apps/runner/runner/client.py::ApiClient.upload_artifact`
- `apps/api/apps/artifacts/internal_views.py`
- `apps/api/apps/artifacts/services.py::create_from_runner_upload`
- `apps/api/apps/artifacts/storage.py`

Required runner additions:

- Add `ArtifactUploader.upload_file(step_id, path, kind="file", name=None, mime_type="", metadata=None)`.
- Add declared artifact collection from `step.step_snapshot`.
- Continue uploading stdout/stderr with `upload_stdout()` / `upload_stderr()`.
- Attach metadata:
  - `sandbox_provider`
  - `sandbox_run_id`
  - `step_key`
  - `artifact_source_path`
  - `truncated`
  - `redaction_applied`
  - `collection_status`

Expected workflow artifact declaration in existing `step_snapshot`:

```json
{
  "id": "plan",
  "name": "Terraform plan",
  "type": "shell_command",
  "command": "terraform plan -out ../artifacts/tfplan",
  "artifacts": [
    {
      "name": "tfplan",
      "path": "artifacts/tfplan",
      "kind": "file",
      "mimeType": "application/octet-stream",
      "required": true
    }
  ]
}
```

Django service behavior remains:

- Validate runner ownership and change binding.
- Reject uploads after terminal execution state.
- Enforce upload size, total execution quota, count quota, MIME type, checksum, and path-safe storage key.
- Emit `artifact.uploaded`.

## 10. Cancellation and Timeout Semantics

Current public cancellation only supports queued executions in `apps/api/apps/executions/services.py::cancel_execution`. Phase A needs active cancellation because real processes may be running.

Required Django changes:

- Add cancellation intent fields on `Execution`:
  - `cancel_requested_at`
  - `cancel_requested_by`
  - `cancel_reason`
- Allow public cancellation for:
  - `queued`: transition immediately to `cancelled` as today.
  - `claimed` / `running`: persist cancellation intent and emit `execution.cancel_requested`; do not directly mark terminal unless no runner heartbeat is active.
- Add internal heartbeat response field:
  - `cancel_requested: bool`
  - `cancel_reason: str`
- Add internal optional endpoint:
  - `POST /api/v1/internal/executions/{execution_id}/cancel-status/`
  - Use only if heartbeat payload should stay minimal; heartbeat is preferred for fewer moving parts.

Required runner behavior:

- Heartbeat thread observes `cancel_requested`.
- `Executor` shares a cancellation token with the current `SandboxProvider`.
- Before starting each step, check cancellation token and fail/stop without running more commands.
- During local execution, provider kills process group on cancellation.
- Report cancelled step as failed unless/until Django adds a `cancelled` step status.
- Complete execution with final status `failed` or `cancelled` depending on schema migration below.

Recommended schema direction:

- Add `ExecutionStep.Status.CANCELLED`.
- Add `CompleteExecutionRequest.final_status` support for `"cancelled"`.
- Extend status constraints and frontend status pills.

Timeout semantics:

- Step timeout is distinct from user cancellation.
- Timeout produces:
  - step status: `failed`
  - `exit_code`: `None` if killed before process exit is available
  - `error_message`: `"Step timed out after {n} seconds."`
  - `failure_kind`: `timeout`
  - execution final status: `failed`
- Timeout should not retry automatically.

## 11. Resource-Limiting Strategy

Phase A resource limits are layered:

- Django/workflow declares requested limits in `step_snapshot`.
- Runner applies defaults and caps from local configuration.
- Local process provider enforces wall-clock timeout, output caps, artifact caps, process-group cleanup, and best-effort POSIX limits.
- Host-level isolation remains mandatory for pilot runners.

Proposed step fields inside `step_snapshot`:

```json
{
  "timeoutSeconds": 300,
  "limits": {
    "stdoutBytes": 5242880,
    "stderrBytes": 5242880,
    "artifactBytes": 52428800,
    "maxArtifacts": 20,
    "cpuSeconds": 300,
    "memoryBytes": 1073741824,
    "fileSizeBytes": 104857600,
    "processLimit": 64
  }
}
```

Hard caps:

- Runner must clamp workflow-specified limits to configured maximums.
- If a workflow requests above cap, fail validation before step execution or reduce to cap only if the policy is explicitly documented. Prefer failing closed for pilot.
- If POSIX limits cannot be applied, include `resource_limits_applied=false` in metadata and rely on wall-clock/output/artifact caps.

Operational pilot requirement:

- Run Phase A runner under a dedicated OS user.
- Run runner host inside a disposable VM/container with minimal filesystem access.
- Use host firewall/security groups for egress restrictions.
- Do not mount production secrets or host project repositories into the runner process.

## 12. Secret Masking and Redaction Strategy

Phase A must not add real secret brokerage. It must still prevent accidental leakage of known runner/API secrets and future injected values.

Proposed class:

- `apps/runner/runner/sandbox/redaction.py::SecretRedactor`

Inputs:

- Runner registration token.
- Claim token.
- Dispatch token for change-bound execution.
- Any future step-scoped secret values.
- Optional configured mask patterns from environment, such as `RUNNER_REDACTION_PATTERNS`.

Behavior:

- Replace exact secret values with `[REDACTED]`.
- Avoid masking very short values, default minimum length 8.
- Apply to:
  - stdout bytes before upload
  - stderr bytes before upload
  - error messages
  - runner exception strings that may be reported to Django
  - artifact metadata
  - verification observed values
- Do not log raw environment values.
- Do not include full command in public audit metadata if it may contain inline secrets; store `command_sha256` and redacted display command.

Required Django hardening:

- Add a shared redaction helper for audit metadata if one does not already exist.
- Ensure `error_message` truncation in `apps/api/apps/executions/services.py::_emit_step_transition_audit` continues to apply after richer failure messages are introduced.
- Add tests proving dispatch tokens and runner tokens do not appear in stdout/stderr artifacts, audit events, or API responses.

## 13. Failure Semantics and Retry Boundaries

Failure kinds:

- `unsupported_step_type`
- `invalid_execution_spec`
- `sandbox_setup_failed`
- `sandbox_runtime_failed`
- `command_failed`
- `timeout`
- `cancelled`
- `artifact_upload_failed`
- `artifact_collection_failed`
- `api_update_failed`
- `runner_internal_error`

Status mapping:

| Condition | Step status | Execution status | Retry |
|---|---|---|---|
| Command exit code `0` | `succeeded` | continue | no retry |
| Command exit code non-zero | `failed` | `failed` | manual only |
| Timeout | `failed` | `failed` | manual only |
| User cancellation | `cancelled` if added, otherwise `failed` | `cancelled` if added, otherwise `failed` | no automatic retry |
| Unsupported step type | `failed` | `failed` | after workflow fix |
| Sandbox setup failure | `failed` | `failed` | after runner fix |
| Artifact upload rejected with 4xx | keep command result, mark metadata | depends on command result | no automatic retry |
| Artifact upload 5xx/network failure | bounded retry, then mark metadata | depends on command result | no step re-execution |
| Runner crash mid-step | watchdog marks failed | `failed` | manual only |

Retry boundary:

- Do not automatically re-run a command after it has started. The platform cannot assume commands are idempotent.
- API calls that report facts may retry because they do not re-execute the command.
- Artifact upload may use bounded retry because it uploads already-produced evidence.
- Reclaiming an execution may only continue steps that have not started running or that are waiting for approval, preserving current conservative behavior in `claim_next_execution`.

## 14. State-Machine Interactions With Django

Existing relevant files:

- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/client.py`

Preserve:

- `Execution`: `queued -> claimed -> running -> succeeded|failed|cancelled`
- `ExecutionStep`: `pending -> running -> succeeded|failed`, plus approval path
- Runner ownership validation through `claimed_by_runner_id` and `claim_token`
- Change-bound execution binding guard before start/update/upload/complete
- Policy evaluation before `pending -> running`
- Watchdog recovery for stale heartbeats

Required state-machine additions:

- Add active cancellation intent as described in section 10.
- Add optional `ExecutionStep.Status.CANCELLED`.
- Add result metadata fields without bypassing service functions.

Recommended `ExecutionStep` fields:

- `failure_kind = models.CharField(max_length=64, blank=True, default="")`
- `timed_out = models.BooleanField(default=False)`
- `cancelled = models.BooleanField(default=False)`
- `sandbox_provider = models.CharField(max_length=64, blank=True, default="")`
- `sandbox_run_id = models.CharField(max_length=128, blank=True, default="")`
- `command_sha256 = models.CharField(max_length=64, blank=True, default="")`
- `result_metadata = models.JSONField(default=dict)`

Alternative if avoiding column growth:

- Create `ExecutionStepRun` with one row per started attempt. This is better for future retries, but more invasive.
- For Phase A, prefer direct fields plus `result_metadata` unless implementation discovery shows retry modeling is imminent.

Service contract:

- Extend `update_execution_step(...)` to accept optional sandbox/result fields.
- Validate terminal result metadata sizes.
- Redact before audit emission.
- Emit stream events with enough fields for frontend visibility.
- Never let runner set arbitrary execution status outside allowed transitions.

## 15. Audit and Event Expectations

Audit events must answer: what was authorized, what ran, where it ran, what evidence was captured, and why it failed.

Required events:

- Existing `execution.claimed`
- Existing `execution_step.started`
- Existing `execution_step.succeeded`
- Existing `execution_step.failed`
- Existing `artifact.uploaded`
- Existing `execution.completed` / `execution.failed`
- New `execution.cancel_requested`
- New `execution_step.cancelled` if step cancellation status is added
- New `execution_step.sandbox_started`
- New `execution_step.sandbox_finished`
- New `execution_step.artifact_collection_failed` when applicable

Audit metadata rules:

- Include:
  - `execution_id`
  - `step_id`
  - `step_key`
  - `step_type`
  - `risk_level`
  - `sandbox_provider`
  - `sandbox_run_id`
  - `command_sha256`
  - `exit_code`
  - `failure_kind`
  - `timed_out`
  - `cancelled`
  - `duration_ms`
  - `stdout_artifact_id`
  - `stderr_artifact_id`
  - `artifact_ids`
- Exclude:
  - raw claim token
  - dispatch token
  - full unredacted command
  - raw environment
  - absolute host workspace paths
  - raw stdout/stderr

Stream/SSE expectations:

- Existing `step.status_changed` should include new result fields when available.
- Existing execution detail stream should continue to close on terminal state.
- Frontend should show failed sandbox setup, timeout, cancellation, truncation, and artifact collection warnings without exposing secrets.

## 16. Required Database/API/Schema Changes

Django migrations:

- `apps/api/apps/executions/migrations/0008_execution_cancellation_and_step_result.py`
  - Add execution cancellation intent fields.
  - Add step result metadata fields.
  - Optionally add `cancelled` step status and update check constraints.
- Update any status check constraints introduced in prior migrations.

Internal serializers:

- `apps/api/apps/executions/internal_serializers.py::HeartbeatSerializer`
  - Keep request compatible.
- `HeartbeatResponse`
  - Include `cancel_requested` and `cancel_reason`.
- `StepUpdateSerializer`
  - Add optional fields:
    - `failure_kind`
    - `timed_out`
    - `cancelled`
    - `sandbox_provider`
    - `sandbox_run_id`
    - `command_sha256`
    - `result_metadata`
    - `stdout_artifact_id`
    - `stderr_artifact_id`
    - `artifact_ids`
- `ExecutionCompleteSerializer`
  - Add `cancelled` if execution cancellation is modeled as terminal status through runner completion.

Runner schemas:

- `apps/runner/runner/schemas.py::ClaimedStep`
  - include `step_snapshot`
- `StepUpdateRequest`
  - mirror new optional result fields
- `HeartbeatResponse`
  - include cancellation fields

Public API serializers:

- `apps/api/apps/executions/serializers.py::ExecutionStepSerializer`
  - expose:
    - `failure_kind`
    - `timed_out`
    - `cancelled`
    - `sandbox_provider`
    - `sandbox_run_id`
    - `result_metadata` with redacted/safe fields only
- `ExecutionDetailSerializer`
  - expose cancellation intent fields.

Workflow schema:

- Continue accepting current thin workflow schema.
- Add optional `timeoutSeconds`, `limits`, and `artifacts` fields to step snapshots.
- Validate these fields in `apps/api/apps/executions/services.py::_validate_workflow_definition`.
- Fail closed for invalid types, negative limits, absolute artifact paths, and artifact count above cap.

## 17. Required Runner Changes

Files:

- `apps/runner/runner/executor.py`
- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/sandbox/local_process.py`
- `apps/runner/runner/sandbox/factory.py`
- `apps/runner/runner/sandbox/workspace.py`
- `apps/runner/runner/sandbox/redaction.py`
- `apps/runner/runner/sandbox/streams.py`
- `apps/runner/runner/artifact_uploader.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/schemas.py`

Executor changes:

- Replace simulated `_execute_command()` body with:
  - build execution spec from `ClaimedExecution` and `ClaimedStep`;
  - validate through provider;
  - execute through provider;
  - upload stdout/stderr;
  - upload collected file artifacts;
  - report terminal step update;
  - emit verification facts using real exit status and artifacts.
- Preserve existing `FAIL_STEP` marker only in tests if needed; do not leave it as production behavior.
- Unsupported steps fail explicitly.

Client changes:

- Parse new heartbeat cancellation response.
- Send new result fields in step update payload.
- Keep upload retry behavior bounded.

Settings changes:

- Add sandbox provider, workspace, timeout, output, artifact, cleanup, and redaction config.
- Validate startup:
  - workspace root must be writable.
  - provider must be known.
  - shell path must exist when shell mode is enabled.
  - timeout/output/artifact caps must be positive.

## 18. Required Frontend Visibility Changes

Files:

- `apps/web/src/features/executions/types.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- `apps/web/src/features/artifacts/types.ts`

Execution detail should show:

- Step timeout state.
- Step cancellation state.
- Failure kind.
- Sandbox provider and run ID.
- Exit code.
- Redacted error message.
- stdout/stderr artifact rows as today.
- Artifact truncation and redaction indicators.
- Cancellation requested banner for active executions.

Do not expose:

- Claim token.
- Dispatch token.
- Raw environment.
- Absolute runner workspace path.
- Unredacted command if command redaction is applied.

UX constraints:

- Keep existing execution detail layout.
- Do not add a new service connection from the frontend.
- Use existing artifact list and audit trail panels.

## 19. Required Tests

Runner unit tests:

- `apps/runner/tests/test_local_process_sandbox.py`
  - executes a successful command;
  - captures stdout/stderr separately;
  - returns non-zero exit code;
  - enforces timeout and kills process group;
  - handles cancellation;
  - caps stdout/stderr and marks truncation;
  - rejects path traversal artifact specs;
  - rejects symlink artifact escape;
  - applies redaction.
- `apps/runner/tests/test_executor_real_execution.py`
  - start-step gate is called before execution;
  - blocked step is not executed;
  - approval path still works;
  - stdout/stderr upload before terminal update;
  - artifact upload failure does not re-run command;
  - unsupported step type fails closed.
- `apps/runner/tests/test_runner_settings.py`
  - invalid provider fails startup;
  - unwritable workspace fails startup;
  - invalid limits fail startup.

Django API tests:

- `apps/api/apps/executions/tests/test_runner_api.py`
  - step update accepts sandbox result fields;
  - invalid result metadata rejected;
  - stale claim token rejected;
  - cancellation intent returned by heartbeat.
- `apps/api/apps/executions/tests/test_services.py`
  - active cancellation request state transition;
  - terminal cancellation state if added;
  - audit events emitted with safe metadata.
- `apps/api/apps/artifacts/tests/test_internal_api.py`
  - upload file artifact from runner;
  - checksum mismatch rejected;
  - quota exceeded rejected;
  - terminal execution upload rejected.

Frontend tests:

- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
  - renders timeout/failure kind;
  - renders cancellation requested;
  - renders sandbox metadata;
  - hides unsafe fields.

Integration smoke tests:

- Create workflow with `command: "printf hello"`.
- Runner claims and executes real command.
- stdout artifact contains `hello`.
- Step succeeds with `exit_code=0`.
- Create workflow with `command: "exit 7"`.
- Step fails with `exit_code=7`.
- Create workflow with `command: "sleep 30"` and `timeoutSeconds: 1`.
- Step fails with `failure_kind=timeout`.

## 20. Rollout and Migration Strategy

Phase sequence:

1. Schema prep
   - Add Django fields and serializers.
   - Keep runner compatible with old response shape.
   - Add public read-only fields.
   - Verify existing simulated runner tests still pass.

2. Sandbox abstraction
   - Add provider interface and local-process provider.
   - Unit test provider independently.
   - Do not wire into `Executor` yet.

3. Runner wiring behind feature flag
   - Add `RUNNER_EXECUTION_MODE=simulated|sandboxed`.
   - Default to `simulated` for one compatibility pass.
   - Support `sandboxed` in local/dev.
   - Keep step-start gate unchanged.

4. Artifact collection
   - Add file artifact upload helper.
   - Add artifact spec validation and upload metadata.

5. Cancellation and timeout
   - Add active cancellation intent.
   - Wire heartbeat cancellation to runner token.
   - Add timeout tests and manual smoke tests.

6. Frontend visibility
   - Expose result fields.
   - Add timeout/cancellation/failure-kind UI.

7. Flip pilot runner
   - Set `RUNNER_EXECUTION_MODE=sandboxed` only on pilot runner.
   - Run smoke workflows in staging.
   - Confirm audit, artifacts, streaming, watchdog, and change-bound execution still work.

8. Remove or quarantine simulation
   - Once pilot passes, make `sandboxed` the default.
   - Keep simulation only as explicit test fixture, not production mode.

Migration rules:

- Existing executions remain readable.
- Existing steps have blank result metadata fields.
- Old runners must continue to work until pilot runner is deployed, or Django must reject old runner versions for sandbox-required workflows.
- Add runner version checks only if a mixed fleet creates unsafe behavior.

Rollback:

- Set `RUNNER_EXECUTION_MODE=simulated` only if the deployment must stop real execution immediately during early rollout.
- Drain/stop pilot runner before rollback if a real command may be active.
- Revert frontend display changes independently if needed; they are read-only.
- Database fields are additive and should not require rollback migrations.
- If cancellation status enum causes issues, feature-flag active cancellation while leaving fields in place.

## 21. Risks and Failure Modes

Key risks:

- Local process sandbox is not strong enough for untrusted code.
- Commands may perform destructive actions on reachable systems.
- Long-running child processes may survive if process-group cleanup is incomplete.
- Output or artifacts may leak secrets before redaction catches them.
- Artifact upload may fail after command success, producing incomplete evidence.
- Runner crash after command side effects but before terminal update may leave Django to mark failure by watchdog.
- Resource limits vary by OS and may not behave consistently in Docker/WSL.
- Active cancellation semantics may confuse users if step status cannot represent `cancelled`.
- Shell mode preserves compatibility but increases injection risk.

Mitigations:

- Pilot only on isolated runner hosts.
- Require workflow review and policy gates for real command steps.
- Default to short timeouts and small output/artifact caps.
- Kill process groups on timeout/cancellation.
- Redact known secrets in all runner-produced text.
- Never auto-retry started commands.
- Emit explicit failure kinds and audit events.
- Document local-process provider as limited containment.
- Move to container provider before broader customer or hostile-workload use.

## 22. Explicit Non-Goals

Phase A does not:

- Add Celery, Redis, Kafka, SQS, or any queue/broker.
- Add a new runner scheduling service.
- Implement container-backed execution.
- Implement typed action catalog beyond optional step metadata used by shell commands.
- Implement production secret brokerage.
- Implement cloud credential minting.
- Implement strong network egress controls in code.
- Make local-process execution safe for hostile arbitrary code.
- Add multi-tenant runner isolation on a shared host.
- Rewrite the Django execution state machine.
- Bypass approvals, policies, change binding, breakglass checks, target locks, verification, or audit services.
- Upload artifacts directly from runner to object storage.

## Acceptance Criteria

Pilot Phase A is complete when:

- `apps/runner/runner/executor.py` no longer simulates production step execution.
- `apps/runner/runner/sandbox.py` or its package replacement exposes a tested `SandboxProvider` contract.
- A real command can execute in an isolated workspace and produce real stdout/stderr artifacts.
- Non-zero exit, timeout, cancellation, unsupported step type, and sandbox setup failure all fail closed with clear failure kinds.
- Artifact uploads still flow only through Django internal APIs.
- Django remains authoritative for step start, step terminal update, execution completion, cancellation intent, audit, and streaming.
- No raw claim token, dispatch token, runner token, or secret value appears in logs, audit metadata, API responses, stdout/stderr artifacts, or frontend views in tests.
- Existing approval and policy tests remain green.
- Existing artifact ownership/quota/checksum tests remain green.
- Change-bound execution callbacks remain compatible.
- Frontend execution detail displays real execution outcomes clearly.

## Verification Commands

Run after each implementation milestone:

```bash
make test-api
make test-runner
make test-web
make lint
make check-migrations
```

If `make lint` is unavailable in the current branch, use:

```bash
docker compose exec api python manage.py check
docker compose exec api pytest apps/executions apps/artifacts
cd apps/runner && pytest
cd apps/web && npm run lint && npm run build
```

Manual smoke verification:

```bash
docker compose up api runner web
```

Then create and execute three workflows:

- success: `printf 'hello\n'`
- failure: `exit 7`
- timeout: `sleep 30` with `timeoutSeconds: 1`

Verify:

- Step status and exit code are correct.
- stdout/stderr artifacts are real.
- timeout is marked as timeout, not generic failure.
- audit trail contains sandbox start/finish facts.
- execution stream closes only after terminal state.
- no secret-like configured token appears in artifacts or audit metadata.
