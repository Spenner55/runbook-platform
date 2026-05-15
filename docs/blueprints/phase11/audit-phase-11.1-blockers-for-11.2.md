# Phase 11.1 Blocker Fixes Required Before Phase 11.2 Implementation

## 1. Document Purpose

This document captures the exact code changes required to close the five critical gaps that prevent Phase 11.2 from being built safely on Phase 11.1. It is an implementation guide, not a design document.

Each section names the exact files to change, the exact lines to change them at, the exact replacement code to write, and the exact tests to add or convert. Do not implement Phase 11.2 until all five blockers are closed and all three test suites pass clean.

**Audit performed:** 2026-05-03  
**Test baseline:** 970 API tests pass / 122 runner tests pass / 135 web tests pass  
**Verdict: NO-GO**

---

## 2. Blocker Summary

| ID | Title | Root Gap | Phase 11.2 Consequence |
|---|---|---|---|
| B1 | Step-update endpoint accepts `running` | `StepUpdateSerializer` allows `pending → running` bypass of `ExecutionStepStartView` | `policy_pass_ok` preflight check is worthless if execution can be started without policy evaluation |
| B2 | Workflow definition is not hashed at submit | `build_request_snapshot` captures `workflow.name/version` but not `workflow.definition` content; `WorkflowAdmin` leaves published definitions editable | `approved_status_ok` preflight passes even if the workflow definition was mutated after approval |
| B3 | ChangeRecord approval/policy fields and ChangeExecutionBinding identity fields are admin-editable after creation | Admin readonly and permission guards are incomplete | Approval-invalidation logic and target-lock evidence in Phase 11.2 depend on the integrity of these links |
| B4 | Approval-change divergence is silently allowed | `handle_change_approval_decision()` returns instead of raising when change is missing or in wrong state | `approved_status_ok` can pass for a change whose approval and status have diverged |
| B5 | Execution completion hook is swallowed | `complete_execution()` catches all exceptions from `handle_bound_execution_completed()` | Phase 11.2 lock release and window close happen inside this hook; a swallowed failure leaves `TargetLock` permanently active |

---

## 3. B1 — Step-Update Endpoint Accepts `running`

### What is wrong

`ExecutionStepStartView` is the only endpoint that runs policy evaluation before authorizing command execution. `ExecutionStepUpdateView` bypasses it.

Three objects all accept `running` as a valid step status through the update path:

**`apps/api/apps/executions/internal_serializers.py` line 144:**
```python
status = serializers.ChoiceField(
    choices=["running", "succeeded", "failed", "skipped"]
)
```

**`apps/api/apps/executions/services.py` lines 741–748 (`_VALID_STEP_TRANSITIONS`):**
```python
_VALID_STEP_TRANSITIONS: dict[str, set[str]] = {
    ExecutionStep.Status.PENDING: {
        ExecutionStep.Status.RUNNING,   # ← bypass
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.WAITING_FOR_APPROVAL: {
        ExecutionStep.Status.RUNNING,   # ← bypass
        ExecutionStep.Status.FAILED,
    },
    ...
```

**`apps/runner/runner/schemas.py` line 194 (`StepUpdateRequest`):**
```python
status: Literal["running", "succeeded", "failed", "skipped"]
```

`ExecutionStepUpdateView` calls `update_execution_step()` directly with no policy gate. Any runner with valid credentials can POST `status=running` to the update endpoint for any pending step, bypassing `ExecutionStepStartView` entirely.

The first-party runner never sends `running` via `update_step()` — it uses `start_step()` instead. The protocol invariant must now be enforced in the backend, not assumed from runner behavior.

### What to change

#### `apps/api/apps/executions/internal_serializers.py`

Remove `"running"` from `StepUpdateSerializer.status` choices. The update endpoint is for terminal runner reports only.

```python
# Before (line 143–145):
status = serializers.ChoiceField(
    choices=["running", "succeeded", "failed", "skipped"]
)

# After:
status = serializers.ChoiceField(
    choices=["succeeded", "failed", "skipped"]
)
```

#### `apps/api/apps/executions/services.py`

Remove `RUNNING` from both allowed-transition sets in `_VALID_STEP_TRANSITIONS`. The `pending → running` and `waiting_for_approval → running` transitions are only valid when initiated by `ExecutionStepStartView` which calls `update_execution_step()` internally after policy evaluation. The update endpoint must not be able to produce the same transition.

The cleanest fix is to keep a single `update_execution_step()` function but add a `_allow_running: bool = False` guard parameter. `ExecutionStepStartView` passes `True`; the update endpoint does not pass it, so its call cannot reach the `RUNNING` branch.

```python
# Updated _VALID_STEP_TRANSITIONS — remove RUNNING entries:
_VALID_STEP_TRANSITIONS: dict[str, set[str]] = {
    ExecutionStep.Status.PENDING: {
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.WAITING_FOR_APPROVAL: {
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.RUNNING: {
        ExecutionStep.Status.SUCCEEDED,
        ExecutionStep.Status.FAILED,
    },
}

# Add a separate set used only by ExecutionStepStartView:
_VALID_STEP_START_TRANSITIONS: dict[str, set[str]] = {
    ExecutionStep.Status.PENDING: {
        ExecutionStep.Status.RUNNING,
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.WAITING_FOR_APPROVAL: {
        ExecutionStep.Status.RUNNING,
        ExecutionStep.Status.FAILED,
    },
}
```

Then update `update_execution_step()` signature and transition lookup:

```python
def update_execution_step(
    *,
    execution: Execution,
    step_id: str,
    runner_id: str,
    claim_token: str,
    new_status: str,
    started_at=None,
    finished_at=None,
    exit_code=None,
    error_message: str = "",
    _allow_running: bool = False,   # only ExecutionStepStartView passes True
) -> ExecutionStep:
```

Inside the function, update the transition lookup:

```python
# Replace:
allowed = _VALID_STEP_TRANSITIONS.get(step.status, set())

# With:
if _allow_running:
    allowed = _VALID_STEP_START_TRANSITIONS.get(step.status, set())
else:
    allowed = _VALID_STEP_TRANSITIONS.get(step.status, set())
```

All six call sites in `ExecutionStepStartView` that set `new_status=ExecutionStep.Status.RUNNING` must pass `_allow_running=True`. All call sites in `ExecutionStepUpdateView`, watchdog, timeout, and approval paths that produce `FAILED` transitions do not pass it (they remain safe).

Grep for all call sites before editing:
```bash
grep -n "update_execution_step" apps/api/apps/executions/internal_views.py
```

#### `apps/runner/runner/schemas.py`

Remove `"running"` from `StepUpdateRequest.status`:

```python
# Before (line 194):
status: Literal["running", "succeeded", "failed", "skipped"]

# After:
status: Literal["succeeded", "failed", "skipped"]
```

The runner never sends `running` via `update_step()` in practice. This change locks the schema to match actual runner behavior.

#### `apps/runner/runner/tests/test_client.py`

Delete or convert `test_update_step_running_sends_correct_payload` (line 480). The test currently asserts that `status="running"` is sent successfully. After the schema fix, the `StepUpdateRequest` Pydantic model will reject `"running"` as an invalid literal. Convert to a negative test:

```python
def test_update_step_running_is_rejected_by_schema():
    """StepUpdateRequest must not accept running — start_step is the only running path."""
    with pytest.raises(ValidationError):
        StepUpdateRequest(
            runner_id="runner-1",
            claim_token=uuid4(),
            status="running",
        )
```

### Tests to add

Add to `apps/api/apps/executions/tests/test_runner_api.py`:

```python
@pytest.mark.django_db
def test_step_update_rejects_running_status(queued_execution):
    """Update endpoint must reject status=running; only /start/ can authorize running."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={"runner_id": "runner-1", "claim_token": claim_token, "status": "running"},
        content_type="application/json",
    )
    assert response.status_code == 400

@pytest.mark.django_db
def test_step_update_accepts_succeeded_without_start(queued_execution):
    """Confirm the update endpoint still works for terminal statuses after the running restriction."""
    # First, use /start/ to put the step into running
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    # Then use /update/ to mark it succeeded — this must work
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={"runner_id": "runner-1", "claim_token": claim_token, "status": "succeeded"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["step"]["status"] == "succeeded"
```

Convert the existing `test_step_update_transitions_pending_to_running` (line 203) — delete it and replace with `test_step_update_rejects_running_status` above.

Also add to `apps/api/apps/executions/tests/test_policy_integration.py`:

```python
@pytest.mark.django_db
def test_step_update_cannot_bypass_policy_to_set_running(org, claimed):
    """Even with valid runner credentials, update/ cannot put a step into running."""
    execution, claim_token = claimed
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={"runner_id": "runner-1", "claim_token": str(claim_token), "status": "running"},
        content_type="application/json",
    )
    assert response.status_code == 400
    step.refresh_from_db()
    assert step.status == "pending"
```

### Validation

```bash
docker compose exec api pytest apps/executions/tests/test_runner_api.py apps/executions/tests/test_policy_integration.py -x -q
docker compose exec runner pytest runner/tests/test_client.py -x -q
```

---

## 4. B2 — Workflow Definition Is Not Hashed at Submit

### What is wrong

`build_request_snapshot()` in `apps/api/apps/changes/services.py` (lines 119–140) builds the `workflow_snapshot` sub-dict with `id`, `name`, `version`, and `status` only. It does not include a hash of `workflow.definition`. The snapshot therefore does not detect if the workflow's step commands, risk levels, or schema are changed after the change is submitted and approved.

`WorkflowAdmin` in `apps/api/apps/workflows/admin.py` has no `readonly_fields` and no `has_change_permission` restriction for published or superseded workflows. An admin user can change `definition`, `name`, `version`, `status`, or `runbook` on any workflow at any time.

`validate_request_integrity()` re-builds the live snapshot and compares it to the frozen one. Because the definition hash is absent from both, a definition mutation silently passes the integrity check.

### What to change

#### `apps/api/apps/changes/models.py`

Add one field to `ChangeRecord`:

```python
workflow_definition_sha256 = models.CharField(max_length=64, blank=True)
```

Place it directly after `workflow_version_snapshot` (current line 124). Add it to `_CHANGE_RECORD_ALWAYS_READONLY` in `admin.py` and to the `update_fields` list in every service path that writes snapshot fields.

#### `apps/api/apps/changes/services.py`

**In `build_request_snapshot()` (lines 119–130):** add the definition hash to `workflow_snapshot`:

```python
workflow_snapshot: dict = {}
if workflow is not None:
    workflow_snapshot = {
        "id": str(workflow.id),
        "name": workflow.name,
        "version": workflow.version,
        "status": workflow.status,
        "definition_sha256": sha256_canonical_json(workflow.definition or {}),
    }
```

`sha256_canonical_json` is already imported at the top of `services.py`.

**In `submit_change_record()` (around line 916–925):** after computing `snapshot`, also set `workflow_definition_sha256`:

```python
change.request_snapshot = snapshot
change.request_snapshot_sha256 = snapshot_hash
change.operation_profile_key_snapshot = profile.key
change.workflow_version_snapshot = workflow.version
change.workflow_definition_sha256 = sha256_canonical_json(workflow.definition or {})
```

Add `"workflow_definition_sha256"` to the `update_fields` list in the same block.

**In `build_live_submitted_request_snapshot()` (lines 485–506):** the snapshot is rebuilt from live data. It calls `build_request_snapshot()` which now includes the definition hash from the live workflow row. No additional change is needed here — the live snapshot will automatically include the live definition hash, and if the definition changed, it will differ from the stored snapshot.

**In `validate_request_integrity()` (around line 443–473):** no structural change needed. The existing comparison already fails if the live snapshot differs from the frozen one, which now catches definition mutations.

#### `apps/api/apps/workflows/admin.py`

Add immutability protection for published and superseded workflows:

```python
from django.contrib import admin

from .models import Workflow


_WORKFLOW_ALWAYS_READONLY = ["id", "created_at", "updated_at", "version"]

_WORKFLOW_PUBLISHED_READONLY = [
    "definition",
    "name",
    "status",
    "runbook",
    "organization",
    "definition_schema_version",
]


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization",
        "runbook",
        "version",
        "status",
        "definition_schema_version",
        "created_at",
    )
    list_filter = ("status", "organization", "created_at")
    search_fields = ("name", "runbook__title", "runbook__slug")
    list_select_related = ("organization", "runbook")
    ordering = ("name", "-version")
    readonly_fields = _WORKFLOW_ALWAYS_READONLY

    def get_readonly_fields(self, request, obj=None):
        fields = list(_WORKFLOW_ALWAYS_READONLY)
        if obj is not None and obj.status in ("published", "superseded"):
            fields.extend(_WORKFLOW_PUBLISHED_READONLY)
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status in ("published", "superseded"):
            return False
        return super().has_delete_permission(request, obj)
```

#### Migration

Generate and apply:

```bash
docker compose exec api python manage.py makemigrations changes --name add_workflow_definition_sha256
docker compose exec api python manage.py migrate
```

The migration adds a single `CharField(max_length=64, blank=True)` to `changes_changerecord`. No backfill is required for existing rows because `validate_request_integrity()` skips rows in `draft` status, and any non-draft submitted changes will fail integrity on the next service call if their stored snapshot is missing the hash — which is acceptable; they would need to be resubmitted or handled as pre-migration legacy records.

### Tests to add

Add to `apps/api/apps/changes/tests/test_immutability.py`:

```python
def test_snapshot_includes_workflow_definition_sha256(self, submitted_change):
    snapshot = submitted_change.request_snapshot
    workflow_snap = snapshot.get("workflow_snapshot", {})
    assert "definition_sha256" in workflow_snap
    assert len(workflow_snap["definition_sha256"]) == 64

def test_dispatch_refuses_when_workflow_definition_mutated(self, submitted_change):
    """If workflow.definition changes after submit, integrity check must fail."""
    submitted_change.workflow.definition = {"steps": [{"id": "injected"}]}
    submitted_change.workflow.save(update_fields=["definition"])
    with pytest.raises(Exception, match="no longer matches"):
        validate_request_integrity(submitted_change)

def test_workflow_definition_sha256_set_on_submit(self, draft_change):
    from apps.changes.services import submit_change_record
    from apps.audit.services import system_actor
    actor = system_actor("test")
    change = submit_change_record(change=draft_change, actor=actor)
    assert change.workflow_definition_sha256 != ""
    assert len(change.workflow_definition_sha256) == 64
```

Add `apps/api/apps/workflows/tests/test_admin.py` (create if it does not exist):

```python
import pytest
from django.test import RequestFactory
from apps.workflows.admin import WorkflowAdmin
from django.contrib.admin.sites import AdminSite


@pytest.mark.django_db
def test_published_workflow_definition_is_readonly(published_workflow, rf):
    admin = WorkflowAdmin(published_workflow.__class__, AdminSite())
    request = rf.get("/")
    request.user = None
    readonly = admin.get_readonly_fields(request, obj=published_workflow)
    assert "definition" in readonly
    assert "name" in readonly

@pytest.mark.django_db
def test_draft_workflow_definition_is_editable(draft_workflow, rf):
    admin = WorkflowAdmin(draft_workflow.__class__, AdminSite())
    request = rf.get("/")
    request.user = None
    readonly = admin.get_readonly_fields(request, obj=draft_workflow)
    assert "definition" not in readonly

@pytest.mark.django_db
def test_published_workflow_cannot_be_deleted(published_workflow, rf):
    admin = WorkflowAdmin(published_workflow.__class__, AdminSite())
    request = rf.get("/")
    request.user = None
    assert not admin.has_delete_permission(request, obj=published_workflow)
```

### Validation

```bash
docker compose exec api python manage.py check
docker compose exec api python manage.py showmigrations changes
docker compose exec api pytest apps/changes/tests/test_immutability.py apps/workflows/tests/ -x -q
```

---

## 5. B3 — Admin-Editable Fields on ChangeRecord and ChangeExecutionBinding

### What is wrong

**`ChangeRecordAdmin`**: `approval_request`, `policy_evaluation`, `policy_decision_snapshot`, and `terminal_reason` are not in either `_CHANGE_RECORD_ALWAYS_READONLY` or `_CHANGE_RECORD_SUBMITTED_READONLY`. After submit, an admin user can reassign the approval request FK, replace the policy evaluation FK, overwrite the policy decision snapshot JSON, and change the terminal reason — all without any service or audit involvement.

**`ChangeExecutionBindingAdmin`**: `readonly_fields` covers token/timing fields but leaves `change_record`, `execution`, `organization`, `operation_profile_key`, `requested_inputs_sha256`, and `bound_by_runner_id` editable. There is no `has_add_permission`, `has_change_permission`, or `has_delete_permission` restriction. Bindings are service-owned records that must never be created or modified through admin.

**`ChangeExecutionBinding.save()`**: The model-level guard only blocks `bound_by_runner_id` rebinding after `bound_at` is set. It does not freeze the creation-time identity fields (`change_record`, `execution`, `organization`, `operation_profile_key`, `requested_inputs_sha256`, `dispatch_token_hash`, `dispatch_token_nonce`) after first save.

### What to change

#### `apps/api/apps/changes/admin.py`

**Extend `_CHANGE_RECORD_ALWAYS_READONLY`** to include approval and policy linkage fields. These are always set by service code and must never be changed through admin regardless of status:

```python
_CHANGE_RECORD_ALWAYS_READONLY = [
    "id",
    "status",
    "approval_request",            # ← add
    "policy_evaluation",           # ← add
    "policy_decision_snapshot",    # ← add
    "terminal_reason",             # ← add
    "requested_inputs_sha256",
    "request_snapshot",
    "request_snapshot_sha256",
    "operation_profile_key_snapshot",
    "workflow_version_snapshot",
    "workflow_definition_sha256",  # ← add after B2 is implemented
    "submitted_at",
    "approved_at",
    "dispatchable_at",
    "running_at",
    "verification_pending_at",
    "closed_at",
    "rejected_at",
    "canceled_at",
    "expired_at",
    "created_at",
    "updated_at",
]
```

**Replace `ChangeExecutionBindingAdmin`** with a fully read-only admin that blocks add, change, and delete:

```python
@admin.register(ChangeExecutionBinding)
class ChangeExecutionBindingAdmin(admin.ModelAdmin):
    list_display = ["id", "change_record", "execution", "reserved_at", "bound_at"]
    readonly_fields = [
        "id",
        "change_record",
        "execution",
        "organization",
        "operation_profile_key",
        "requested_inputs_sha256",
        "dispatch_token_nonce",
        "dispatch_token_hash",
        "dispatch_token_expires_at",
        "reserved_at",
        "bound_at",
        "bound_by_runner_id",
        "runner_payload_snapshot",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

#### `apps/api/apps/changes/models.py`

**Harden `ChangeExecutionBinding.save()`** to freeze all creation-time identity fields, not just `bound_by_runner_id`:

```python
_BINDING_IMMUTABLE_AFTER_CREATION = frozenset([
    "change_record_id",
    "execution_id",
    "organization_id",
    "operation_profile_key",
    "requested_inputs_sha256",
    "dispatch_token_nonce",
    "dispatch_token_hash",
])

def save(self, *args, **kwargs):
    if self.pk:
        previous = type(self).objects.filter(pk=self.pk).first()
        if previous is not None:
            for field in _BINDING_IMMUTABLE_AFTER_CREATION:
                if getattr(previous, field) != getattr(self, field):
                    raise ValidationError(
                        f"ChangeExecutionBinding.{field} is immutable after creation."
                    )
            if (
                previous.bound_at is not None
                and previous.bound_by_runner_id != self.bound_by_runner_id
            ):
                raise ValidationError("Bound change executions cannot be rebound.")
    self.clean()
    return super().save(*args, **kwargs)
```

### Tests to add

Add to `apps/api/apps/changes/tests/test_immutability.py`:

```python
class TestChangeRecordAdminReadOnly:
    def test_approval_request_always_readonly(self, submitted_change, rf):
        admin_instance = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        readonly = admin_instance.get_readonly_fields(request, obj=submitted_change)
        assert "approval_request" in readonly

    def test_policy_evaluation_always_readonly(self, submitted_change, rf):
        admin_instance = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        readonly = admin_instance.get_readonly_fields(request, obj=submitted_change)
        assert "policy_evaluation" in readonly

    def test_terminal_reason_always_readonly(self, submitted_change, rf):
        admin_instance = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        readonly = admin_instance.get_readonly_fields(request, obj=submitted_change)
        assert "terminal_reason" in readonly

    def test_policy_decision_snapshot_always_readonly(self, submitted_change, rf):
        admin_instance = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        readonly = admin_instance.get_readonly_fields(request, obj=submitted_change)
        assert "policy_decision_snapshot" in readonly


class TestChangeExecutionBindingAdmin:
    def test_add_is_blocked(self, rf):
        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        request = rf.get("/")
        assert not admin_instance.has_add_permission(request)

    def test_change_is_blocked(self, rf, submitted_change):
        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        request = rf.get("/")
        assert not admin_instance.has_change_permission(request)
        assert not admin_instance.has_change_permission(request, obj=None)

    def test_delete_is_blocked(self, rf):
        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        request = rf.get("/")
        assert not admin_instance.has_delete_permission(request)

    def test_identity_fields_immutable_after_creation(self, bound_binding):
        """change_record_id must not change after first save."""
        with pytest.raises(ValidationError, match="immutable"):
            bound_binding.change_record_id = uuid.uuid4()
            bound_binding.save()
```

### Validation

```bash
docker compose exec api pytest apps/changes/tests/test_immutability.py -x -q -k "Admin"
```

---

## 6. B4 — Approval-Change Divergence Is Silently Allowed

### What is wrong

`handle_change_approval_decision()` in `apps/api/apps/changes/services.py` (lines 1016–1080) is called from inside `approvals.services.decide_approval()` which runs inside a `transaction.atomic()` block.

When the change is not found or is in the wrong status, the function logs and **returns**. Because it returns instead of raising, the outer transaction commits: the approval request transitions to its terminal status while the linked change record does not. The two records then have diverged state with no recovery path and no audit event.

```python
# Current behavior — divergence silently allowed:
if change is None:
    logger.error("... audit divergence ...")
    return   # ← outer transaction commits; approval terminal, change unchanged

if change.status != ChangeRecord.Status.PENDING_APPROVAL:
    logger.warning("... approval/change state may have diverged ...")
    return   # ← same problem
```

### What to change

#### `apps/api/apps/changes/services.py`

Replace the two `return` statements with `raise`. Import the project's domain exception class at the top of the function block. The raised exception must propagate out of `decide_approval()`'s transaction, rolling back the approval terminal status along with the change non-transition.

```python
def handle_change_approval_decision(
    *,
    approval_request_id,
    decision: str,
    actor: AuditActor | None = None,
) -> None:
    change = (
        ChangeRecord.objects.select_for_update()
        .filter(approval_request_id=approval_request_id)
        .first()
    )
    if change is None:
        raise DomainValidationError(
            code="change_approval_decision_orphaned",
            detail=(
                f"No ChangeRecord found for approval_request_id={approval_request_id} "
                f"(decision={decision}). Approval decision rolled back to preserve consistency."
            ),
        )

    if change.status != ChangeRecord.Status.PENDING_APPROVAL:
        raise InvalidStateTransitionError(
            code="change_approval_state_conflict",
            detail=(
                f"ChangeRecord {change.id} is in status '{change.status}', expected "
                f"'pending_approval' (decision={decision}). "
                "Approval decision rolled back to prevent approval/change divergence."
            ),
        )

    # ... rest of the function unchanged
```

`DomainValidationError` and `InvalidStateTransitionError` are already imported at the top of `services.py`. Do not add new imports.

The caller (`approvals.services.decide_approval()`) must be verified to let these exceptions propagate. Do not add a try/except around the `handle_change_approval_decision()` call in the approvals service.

**Verify the call site in `apps/api/apps/approvals/services.py`:**

```bash
grep -n "handle_change_approval_decision\|except\|try" apps/api/apps/approvals/services.py
```

If the call is inside a try/except that would swallow the exception, remove the exception catch for these specific error types or restructure so the raise propagates.

### Tests to add

Add to `apps/api/apps/changes/tests/test_services.py`:

```python
@pytest.mark.django_db
def test_approval_decision_raises_when_change_not_found():
    """Missing change must roll back the approval transaction, not silently diverge."""
    import uuid
    from apps.changes.services import handle_change_approval_decision
    from apps.common.exceptions import DomainValidationError

    with pytest.raises(DomainValidationError, match="change_approval_decision_orphaned"):
        handle_change_approval_decision(
            approval_request_id=uuid.uuid4(),
            decision="approved",
        )

@pytest.mark.django_db
def test_approval_decision_raises_when_change_not_pending(submitted_change):
    """Change in wrong state must roll back the approval, not leave records diverged."""
    from apps.changes.services import handle_change_approval_decision
    from apps.common.exceptions import InvalidStateTransitionError

    # submitted_change is in 'pending_approval'; transition it to something else
    from apps.changes.transitions import transition_change
    from apps.changes.models import ChangeRecord
    from apps.audit.services import system_actor
    transition_change(
        change=submitted_change,
        new_status=ChangeRecord.Status.REJECTED,
        actor=system_actor("test"),
        terminal_reason="test",
    )

    with pytest.raises(InvalidStateTransitionError, match="change_approval_state_conflict"):
        handle_change_approval_decision(
            approval_request_id=submitted_change.approval_request_id,
            decision="approved",
        )

@pytest.mark.django_db
def test_approval_decision_divergence_does_not_commit(submitted_change):
    """When handle_change_approval_decision raises, the approval decision must not persist."""
    from django.db import transaction
    from apps.approvals.models import ApprovalRequest
    from apps.changes.models import ChangeRecord

    original_approval_status = submitted_change.approval_request.status

    # Force a divergence scenario inside a transaction
    try:
        with transaction.atomic():
            # Corrupt the change state inside the transaction before the callback
            ChangeRecord.objects.filter(pk=submitted_change.pk).update(status="closed")
            from apps.changes.services import handle_change_approval_decision
            handle_change_approval_decision(
                approval_request_id=submitted_change.approval_request_id,
                decision="approved",
            )
    except Exception:
        pass

    # The approval request status must be unchanged (transaction rolled back)
    submitted_change.approval_request.refresh_from_db()
    assert submitted_change.approval_request.status == original_approval_status
```

### Validation

```bash
docker compose exec api pytest apps/changes/tests/test_services.py -x -q -k "approval_decision"
docker compose exec api pytest apps/approvals/tests/ -x -q
```

---

## 7. B5 — Execution Completion Hook Is Swallowed

### What is wrong

`complete_execution()` in `apps/api/apps/executions/services.py` (lines 1025–1031) commits the execution terminal status inside a transaction and then calls `handle_bound_execution_completed()` outside it. The call is wrapped in a bare `except Exception` that logs and continues:

```python
# Current — swallows all failures:
try:
    from apps.changes import services as change_services
    change_services.handle_bound_execution_completed(execution=execution)
except Exception:
    logger.exception(
        "handle_bound_execution_completed failed for execution %s", execution.id
    )
```

If `handle_bound_execution_completed()` raises for any reason, the execution is terminal but the linked `ChangeRecord` remains in `running`. Phase 11.2 adds `TargetLock` release and `ChangeWindow` close inside `handle_bound_execution_completed()`. A swallowed failure permanently locks every target the change touched.

The same swallow pattern appears in the watchdog path (line 329) and the approval-timeout path (line 511). Both should be hardened consistently.

### What to change

#### `apps/api/apps/executions/services.py`

**In `complete_execution()` (around line 1025):**

For change-bound executions, the hook failure must not be silently swallowed. The best fix without a distributed transaction is to:
1. Re-raise for change-bound executions so the runner gets a 500 and will retry.
2. Continue swallowing for non-change executions where no lock/window is at risk.

```python
# Replace the existing bare except block:
try:
    from apps.changes import services as change_services
    change_services.handle_bound_execution_completed(execution=execution)
except Exception:
    # For change-bound executions the completion hook manages TargetLock release
    # and ChangeWindow close. Swallowing the failure leaves those records permanently
    # stuck. Re-raise so the runner gets a 5xx and can retry.
    if execution.change_binding_id is not None:
        raise
    logger.exception(
        "handle_bound_execution_completed failed for execution %s", execution.id
    )
```

`execution.change_binding_id` is the reverse FK accessor name. Verify the actual attribute name by running:
```bash
grep -n "change_binding\|execution_binding\|related_name" apps/api/apps/changes/models.py | grep -i binding
```

The `OneToOneField` on `ChangeExecutionBinding` uses `related_name="change_binding"`, so use `hasattr(execution, 'change_binding')` or check the cached `_state` to avoid a DB round-trip. Alternatively, add a lightweight helper:

```python
def _execution_is_change_bound(execution: Execution) -> bool:
    """Return True if a ChangeExecutionBinding row exists for this execution."""
    return ChangeExecutionBinding.objects.filter(execution_id=execution.pk).exists()
```

Then:

```python
except Exception:
    if _execution_is_change_bound(execution):
        raise
    logger.exception(
        "handle_bound_execution_completed failed for execution %s", execution.id
    )
```

**For the watchdog path (line 329) and approval-timeout path (line 511):** apply the same conditional re-raise. These paths are called outside a request cycle so there is no HTTP response to propagate to. Instead of re-raising, emit an audit event for the failure and do not suppress it silently. A future sweep can detect the stuck change. At minimum, change the log level to `logger.error` with `exc_info=True` and emit an `AuditService.emit` event with `event_type="change.completion_hook_failed"` so the state is visible. This is a secondary concern — the runner-facing `complete_execution()` path is the critical fix.

### Tests to add

Add to `apps/api/apps/executions/tests/test_services.py`:

```python
@pytest.mark.django_db
def test_complete_execution_reraises_hook_failure_for_change_bound(
    monkeypatch, change_bound_claimed_execution
):
    """If the change completion hook fails, complete_execution must re-raise for change-bound executions."""
    execution, claim_token = change_bound_claimed_execution

    def failing_hook(*args, **kwargs):
        raise RuntimeError("simulated completion hook failure")

    monkeypatch.setattr(
        "apps.changes.services.handle_bound_execution_completed",
        failing_hook,
    )

    with pytest.raises(RuntimeError, match="simulated completion hook failure"):
        from apps.executions.services import complete_execution
        complete_execution(
            execution=execution,
            runner_id="runner-1",
            claim_token=str(claim_token),
            outcome="succeeded",
        )

@pytest.mark.django_db
def test_complete_execution_swallows_hook_failure_for_non_change_execution(
    monkeypatch, claimed_execution
):
    """For non-change executions, a hook failure must still be swallowed (no TargetLock risk)."""
    execution, claim_token = claimed_execution

    def failing_hook(*args, **kwargs):
        raise RuntimeError("simulated hook failure — non-change execution")

    monkeypatch.setattr(
        "apps.changes.services.handle_bound_execution_completed",
        failing_hook,
    )

    from apps.executions.services import complete_execution
    result = complete_execution(
        execution=execution,
        runner_id="runner-1",
        claim_token=str(claim_token),
        outcome="succeeded",
    )
    assert result.status == "succeeded"
```

### Validation

```bash
docker compose exec api pytest apps/executions/tests/test_services.py -x -q -k "hook"
```

---

## 8. Implementation Order

Implement blockers in this order. Each must pass its targeted tests before starting the next.

| Step | Blocker | Why this order |
|---|---|---|
| 1 | B1 — Remove running from step-update | Self-contained; touches only serializer, service, and tests. No migration. Breaks `test_step_update_transitions_pending_to_running` intentionally. |
| 2 | B4 — Fail approval handler closed | Self-contained; one function change. No migration. Must be done before B2 because B2 tests use submit which calls the approval path. |
| 3 | B3 — Admin and binding immutability | No migration for admin changes. Migration needed only for the `workflow_definition_sha256` field (added in B2). Add admin changes now, model-level binding freeze now. |
| 4 | B2 — Workflow definition hash | Requires migration. Depends on B3 admin being done (so the field appears in readonly list). |
| 5 | B5 — Re-raise hook failure for change-bound | Last because the `_execution_is_change_bound` helper may reference models. Verify no circular import after B2 migration. |
| 6 | Full test suite | `make test-api` / `make test-runner` / `make test-web` / `make check-migrations` |

---

## 9. Verification Gates

Run these commands after all five blockers are closed:

```bash
docker compose exec api python manage.py check
docker compose exec api python manage.py showmigrations
docker compose exec api pytest apps/ -x -q
docker compose exec runner pytest -x -q
cd apps/web && npm run test -- --run
```

Expected: all three suites pass. No new teardown warnings beyond the existing DB session collision. Migration check returns clean.

After these pass, this document is superseded and the Phase 11.2 Batch 1 implementation prompt from the readiness report may be used.

---

## 10. What Must Not Change

These items are correct and must not drift while fixing the blockers:

- `ExecutionStepStartView` policy evaluation logic — do not alter; only protect it by removing the bypass.
- `validate_request_integrity()` comparison logic — it already works; B2 only adds what it compares.
- `transition_change()` centralization — all status transitions already route through it; do not bypass it while fixing B3/B4.
- Runner `start_step()` / `ExecutionStepStartView` flow — this is the correct path; B1 protects it, not modifies it.
- `ChangeRecord.Status` choices — do not add, remove, or rename statuses. Phase 11.2 adds none of its own statuses to `ChangeRecord`.
- Internal route prefix — all runner-facing routes use `/api/v1/internal/...`; do not introduce `/internal/v1/...`.
- `BaseModel` UUID PK convention — all new Phase 11.2 models must inherit from it.
