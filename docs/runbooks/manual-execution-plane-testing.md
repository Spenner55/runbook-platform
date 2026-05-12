# Manual Execution Plane Testing Guide

Step-by-step instructions for testing the real execution plane end-to-end using the seeded smoke test workflows.

---

## Purpose

Prove that the runner sandbox actually executes commands, captures stdout/stderr, handles failures, enforces timeouts, supports cancellation, and triggers the approval gate — all using real local processes, not simulation.

---

## Prerequisites

1. Docker and Docker Compose running.
2. A valid `.env` file at the repo root (copy from `.env.example` if needed).
3. **Sandboxed execution enabled** — add or update these lines in `.env`:

   ```
   RUNNER_EXECUTION_MODE=sandboxed
   RUNNER_SANDBOX_PROVIDER=local_process
   RUNNER_SANDBOX_CLEANUP_POLICY=always
   RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS=300
   ```

   Without `RUNNER_EXECUTION_MODE=sandboxed`, the runner uses simulation mode and does not execute real commands. Smoke test scenarios (especially timeout and failure) will not work correctly in simulated mode.

4. All services started and migrations applied:

   ```bash
   docker compose up --build -d
   docker compose exec api python manage.py migrate
   ```

---

## Seed the smoke test data

Run the full seed (idempotent):

```bash
make seed-dev
# or:
docker compose exec api python manage.py seed_dev
```

To re-queue smoke executions after they've been picked up by the runner (fast reset):

```bash
make seed-execution-smoke
# or:
docker compose exec api python manage.py seed_dev --execution-smoke
```

Expected output includes six new `QUEUED/smoke-*` executions at the end of the seed summary.

---

## Open the UI

Navigate to `http://localhost:5173` and log in:

| Email | Password | Role |
|---|---|---|
| `admin@acme.test` | `Admin1234!` | Owner |
| `operator@acme.test` | `Operator1!` | Operator |
| `viewer@acme.test` | `Viewer1234!` | Viewer |

Open the **Execution Plane Smoke Tests** runbook from the Runbooks list.

---

## Watch the runner

In a separate terminal:

```bash
make logs-runner
# or:
docker compose logs -f runner
```

The runner polls every 5 seconds and will claim and execute queued smoke executions automatically.

---

## Smoke Test Scenarios

### 1. `sandbox-success-release-check` — Happy path

**Expected result:** All 4 steps succeed. Each step produces real stdout output.

Steps:
1. Print release context — prints date, pwd, user.
2. Write and verify release metadata — creates `output/release-metadata.json` in the workspace, cats it, asserts it's non-empty.
3. Run quick system checks — verifies filesystem is writable.
4. Print success banner — prints a timestamped success message.

**What to verify in the UI:**
- Execution status: `succeeded`
- All 4 steps show `succeeded`
- Each step has a stdout artifact with real command output
- `sandbox_provider=local_process` visible on steps
- Step durations are realistic (not instant)

**What to verify in runner logs:**
```
Step 0/... 'Print release context': succeeded
Step 1/... 'Write and verify release metadata': succeeded
...
Execution ... completed with outcome: succeeded
```

---

### 2. `sandbox-failure-diagnostics` — Non-zero exit and failure capture

**Expected result:** Step 2 exits with code 1. Step 3 is skipped. Execution fails.

Steps:
1. Preparation — succeeds, prints OK.
2. Validate required config — echoes an error message to **stderr** and calls `exit 1`.
3. Post-failure cleanup — should **not** run after step 2 fails.

**What to verify in the UI:**
- Execution status: `failed`
- Step 1: `succeeded`
- Step 2: `failed` with `exit_code=1`, stderr artifact contains the error message
- Step 3: `skipped`
- Failure banner visible on the execution detail page

**What to verify in runner logs:**
```
Step 1/... 'Validate required config (fails intentionally)': failed (failure_kind=, exit_code=1)
```

---

### 3. `sandbox-timeout-check` — Real sandbox timeout

**Expected result:** Step 2 sleeps for 30 seconds but has `timeoutSeconds: 5` in its definition. The runner kills it after 5 seconds and reports `timed_out=true`, `failure_kind="timeout"`.

Steps:
1. Quick pre-check — succeeds immediately.
2. Timeout probe — sleeps 30s; killed by the 5-second limit.

**What to verify in the UI:**
- Execution status: `failed`
- Step 1: `succeeded`
- Step 2: `failed` with `timed_out=true`, `failure_kind=timeout`
- Timeout banner visible on the execution detail page
- Step 2 duration is approximately 5 seconds (not 30)

**What to verify in runner logs:**
```
Step 1/... 'Timeout probe step (sleep 30 with 5s limit)': failed (failure_kind=timeout, ...)
```

**Note:** `timeoutSeconds: 5` is in the step definition and propagates through the workflow snapshot. The executor clamps it to `min(5, RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS)`.

---

### 4. `sandbox-generated-artifacts` — Workspace file generation

**Expected result:** Step creates three files in its workspace `output/` directory, verifies them, and prints their sizes to stdout.

Generated files:
- `output/health-report.txt`
- `output/checks.json`
- `output/summary.md`

**What to verify in the UI:**
- Execution status: `succeeded`
- Step stdout artifact contains the file listing and size output
- Stdout includes all three `PASS:` verification lines

**Current limitation:** The runner uploads stdout/stderr artifacts but does not yet automatically upload arbitrary workspace files as separate artifacts. The files are created and verified inside the sandbox, and their content appears in stdout. Generated-file artifact upload (from `output/`) requires a future workspace collection phase. See the `ArtifactSpec` / `artifact_specs` field in `SandboxExecutionSpec` for the intended extension point.

---

### 5. `sandbox-cancellation-long-running` — Cancellation during execution

**Expected result:** The step runs a 60-tick loop (1 second per tick). After a few ticks, cancel the execution from the UI. The runner observes the cancellation signal from the next heartbeat and kills the subprocess.

Steps:
1. 60-tick countdown — prints `tick=1`, `tick=2`, ... every second.

**How to test:**
1. Seed and start the runner.
2. Watch the runner pick up the execution and start printing ticks.
3. In the UI, open the execution detail page and click **Cancel**.
4. Wait for the next heartbeat cycle (up to 10 seconds).

**What to verify in the UI:**
- Execution transitions to `cancelled`
- Step status: `cancelled` or `failed` with `failure_kind=cancelled`
- Stdout artifact shows the ticks that ran before cancellation

**What to verify in runner logs:**
```
Cancellation requested for execution ...: <reason>
Step 0/... '60-tick countdown...': failed (failure_kind=cancelled, ...)
Execution ... completed with outcome: cancelled
```

---

### 6. `sandbox-policy-approval-gate` — Approval required for high-risk step

**Expected result:** Step 2 has `risk=high`. The seeded policy requires approval for all high-risk steps. The runner pauses and polls until a human approves via the UI.

Steps:
1. Pre-deploy check — low risk, auto-approved, runs immediately.
2. Simulated production deploy — **high risk**, requires approval; runner waits.
3. Post-deploy verification — low risk, runs after approval.

**How to test:**
1. Seed and start the runner.
2. Watch the runner claim the execution and complete step 1.
3. At step 2, the runner transitions to `wait_for_approval` and polls every 5 seconds.
4. In the UI, navigate to the execution detail page and approve the pending approval request.
5. The runner receives `runner_action=run` and executes step 2.
6. Step 3 runs automatically after step 2 succeeds.

**What to verify in the UI:**
- After step 1: execution status `running`, step 2 status `waiting_for_approval`
- Approval banner visible on execution detail
- After approval: step 2 transitions to `running` then `succeeded`
- Final execution status: `succeeded`

---

## Expected artifact behavior

For each completed step (in sandboxed mode):

- **stdout artifact** — uploaded if the command produced any stdout output.
- **stderr artifact** — uploaded if the command produced any stderr output.
- Both are accessible from the execution detail page under each step.
- Content is truncated at `RUNNER_SANDBOX_STDOUT_MAX_BYTES` (default 5 MB).
- Artifacts are stored locally at `ARTIFACT_MEDIA_ROOT` (default `/app/media/artifacts`).

Workspace files created by commands (e.g. `output/checks.json`) are visible in stdout but are **not** separately uploaded as file artifacts in the current implementation. See "Current limitation" in Scenario 4 above.

---

## Reset and re-run

After the runner has processed the smoke executions, re-queue fresh ones:

```bash
make seed-execution-smoke
```

This creates new `QUEUED` executions for any smoke workflow that has no active (queued/claimed/running) execution. Already-queued executions are not duplicated.

To wipe all data and start completely fresh:

```bash
make reset
# WARNING: destroys all local data and volumes
```

---

## Inspect via API

View all executions for the org:

```bash
curl -s -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/executions/ | python3 -m json.tool
```

View a specific execution:

```bash
curl -s -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/executions/<execution-id>/ | python3 -m json.tool
```

List artifacts for an execution:

```bash
curl -s -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/executions/<execution-id>/artifacts/ | python3 -m json.tool
```

---

## Known limitations

1. **Simulated mode does not run real commands.** Timeout, real stderr capture, and exit-code failures only work with `RUNNER_EXECUTION_MODE=sandboxed`.

2. **Generated workspace files are not auto-uploaded as artifacts.** Only stdout/stderr are captured. Future work: add `artifact_specs` to step definitions and implement collection in the runner.

3. **Approval notifications are not pushed.** The runner polls `/approval-status/` every 5 seconds. There is no push notification to the runner when an approval is granted.

4. **Cancellation has a heartbeat lag.** The runner checks for cancellation on the heartbeat interval (default 10 seconds). After clicking Cancel, expect up to 10 seconds before the runner observes it.

5. **`sandbox_allow_shell` defaults to false.** The commands in the smoke test workflows use bash directly (the sandbox invokes `/bin/bash -c`). They do not require `RUNNER_SANDBOX_ALLOW_SHELL=true`.
