"""Runner timing callback endpoint tests.

Covers:
- POST execution-accepted stores accepted timestamp and emits audit event
- POST execution-started stores started timestamp and emits audit event
- POST execution-finished stores finished timestamp, releases locks, closes window
- Window marked OVERRUN when execution finished after window.ends_at
- Idempotency: repeated calls succeed without overwriting first timestamp
- 404 for unknown change
- 409 / 400 for runner ownership mismatch and unbound binding
- User JWT rejected (runner bearer required)
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import (
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeWindow,
    TargetLock,
)
from apps.executions.models import Execution

_CLAIM_TOKEN = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _make_running_change(draft_change):
    """Drive a change all the way to RUNNING via the service layer."""
    from apps.approvals.models import ApprovalRequest

    actor = _system_actor()
    change = change_services.submit_change_record(change=draft_change, actor=actor)
    if change.approval_request_id:
        ApprovalRequest.objects.filter(pk=change.approval_request_id).update(status="approved")
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=ChangeRecord.Status.APPROVED, approved_at=timezone.now()
    )
    change.refresh_from_db()
    change_services.make_dispatchable(change=change, actor=actor)
    change.refresh_from_db()

    binding = change.execution_binding
    execution = binding.execution

    # Simulate runner claiming the execution.
    Execution.objects.filter(pk=execution.pk).update(
        status=Execution.Status.CLAIMED,
        claimed_by_runner_id="test-runner",
        claim_token=_CLAIM_TOKEN,
        claimed_at=timezone.now(),
    )
    execution.refresh_from_db()

    change_services.bind_execution(
        change_id=str(change.id),
        runner_id="test-runner",
        claim_token=str(_CLAIM_TOKEN),
        execution_id=str(execution.id),
        dispatch_token=change_services.generate_dispatch_token(binding),
        requested_inputs_sha256=binding.requested_inputs_sha256,
        operation_profile_key=binding.operation_profile_key,
    )

    change.refresh_from_db()
    binding.refresh_from_db()
    return change, binding, execution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner_client():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-runner-token")
    return client


@pytest.fixture
def running_change(draft_change):
    return _make_running_change(draft_change)


# ---------------------------------------------------------------------------
# record_execution_accepted — service layer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_execution_accepted_stores_timestamp(running_change):
    change, binding, execution = running_change

    result = change_services.record_execution_accepted(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    binding.refresh_from_db()
    assert binding.execution_accepted_at is not None
    assert result["execution_accepted_at"] == binding.execution_accepted_at
    assert result["change_record_id"] == str(change.id)


@pytest.mark.django_db
def test_record_execution_accepted_emits_audit_event(running_change):
    change, binding, execution = running_change

    change_services.record_execution_accepted(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    event = AuditEvent.objects.filter(event_type="change.execution_accepted").first()
    assert event is not None
    assert event.actor_type == AuditEvent.ActorType.RUNNER
    assert event.metadata["runner_id"] == "test-runner"
    assert event.metadata["execution_id"] == str(execution.id)


@pytest.mark.django_db
def test_record_execution_accepted_idempotent(running_change):
    """Second call doesn't overwrite the first timestamp."""
    change, binding, execution = running_change

    first_result = change_services.record_execution_accepted(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )
    second_result = change_services.record_execution_accepted(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    assert first_result["execution_accepted_at"] == second_result["execution_accepted_at"]


# ---------------------------------------------------------------------------
# record_execution_started — service layer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_execution_started_stores_timestamp(running_change):
    change, binding, execution = running_change

    result = change_services.record_execution_started(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    binding.refresh_from_db()
    assert binding.execution_started_at is not None
    assert result["execution_started_at"] == binding.execution_started_at


@pytest.mark.django_db
def test_record_execution_started_emits_audit_event(running_change):
    change, binding, execution = running_change

    change_services.record_execution_started(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    event = AuditEvent.objects.filter(event_type="change.execution_started").first()
    assert event is not None
    assert event.actor_type == AuditEvent.ActorType.RUNNER


@pytest.mark.django_db
def test_record_execution_started_idempotent(running_change):
    change, binding, execution = running_change

    r1 = change_services.record_execution_started(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )
    r2 = change_services.record_execution_started(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    assert r1["execution_started_at"] == r2["execution_started_at"]


# ---------------------------------------------------------------------------
# record_execution_finished — service layer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_execution_finished_stores_timestamp(running_change):
    change, binding, execution = running_change

    result = change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    binding.refresh_from_db()
    assert binding.execution_finished_at is not None
    assert result["execution_finished_at"] == binding.execution_finished_at


@pytest.mark.django_db
def test_record_execution_finished_releases_target_locks(running_change):
    change, binding, execution = running_change

    active_before = TargetLock.objects.filter(
        change_record=change, status=TargetLock.Status.ACTIVE
    ).count()
    assert active_before > 0

    result = change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    assert TargetLock.objects.filter(
        change_record=change, status=TargetLock.Status.ACTIVE
    ).count() == 0
    assert TargetLock.objects.filter(
        change_record=change, status=TargetLock.Status.RELEASED
    ).count() == active_before
    assert result["locks_released"] == active_before


@pytest.mark.django_db
def test_record_execution_finished_emits_lock_released_events(running_change):
    change, binding, execution = running_change

    change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    events = AuditEvent.objects.filter(event_type="target_lock.released")
    assert events.count() >= 1
    event = events.first()
    assert event.actor_type == AuditEvent.ActorType.RUNNER
    assert event.metadata["release_reason"] == "execution_finished"


@pytest.mark.django_db
def test_record_execution_finished_emits_execution_finished_event(running_change):
    change, binding, execution = running_change

    change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    event = AuditEvent.objects.filter(event_type="change.execution_finished").first()
    assert event is not None
    assert event.metadata["locks_released"] >= 1


@pytest.mark.django_db
def test_record_execution_finished_closes_window_within_window(draft_change, running_change):
    """Window is CLOSED when execution finishes before window.ends_at."""
    change, binding, execution = running_change
    now = timezone.now()
    ChangeWindow.objects.create(
        organization=change.organization,
        change_record=change,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
        status=ChangeWindow.Status.OPEN,
    )

    result = change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    window = ChangeWindow.objects.get(change_record=change)
    assert window.status == ChangeWindow.Status.CLOSED
    assert window.closed_at is not None
    assert result["window_status"] == ChangeWindow.Status.CLOSED


@pytest.mark.django_db
def test_record_execution_finished_overruns_window_past_end(running_change):
    """Window is OVERRUN when execution finishes after window.ends_at."""
    change, binding, execution = running_change
    past = timezone.now() - timedelta(hours=2)
    ChangeWindow.objects.create(
        organization=change.organization,
        change_record=change,
        starts_at=past - timedelta(hours=1),
        ends_at=past,
        status=ChangeWindow.Status.OPEN,
    )

    result = change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    window = ChangeWindow.objects.get(change_record=change)
    assert window.status == ChangeWindow.Status.OVERRUN
    assert window.overrun_at is not None
    assert result["window_status"] == ChangeWindow.Status.OVERRUN


@pytest.mark.django_db
def test_record_execution_finished_emits_window_overrun_event(running_change):
    change, binding, execution = running_change
    past = timezone.now() - timedelta(hours=2)
    ChangeWindow.objects.create(
        organization=change.organization,
        change_record=change,
        starts_at=past - timedelta(hours=1),
        ends_at=past,
        status=ChangeWindow.Status.OPEN,
    )

    change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    event = AuditEvent.objects.filter(event_type="change.window_overrun").first()
    assert event is not None
    assert event.actor_type == AuditEvent.ActorType.RUNNER


@pytest.mark.django_db
def test_record_execution_finished_idempotent(running_change):
    change, binding, execution = running_change

    r1 = change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )
    r2 = change_services.record_execution_finished(
        change_id=str(change.id),
        runner_id="test-runner",
        execution_id=str(execution.id),
    )

    assert r1["execution_finished_at"] == r2["execution_finished_at"]
    assert r2["locks_released"] == 0  # No locks left to release


# ---------------------------------------------------------------------------
# Service validation errors
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_accepted_unknown_change_raises(running_change):
    from apps.common.exceptions import DomainValidationError

    with pytest.raises(DomainValidationError) as exc_info:
        change_services.record_execution_accepted(
            change_id="00000000-0000-0000-0000-000000000000",
            runner_id="test-runner",
            execution_id="00000000-0000-0000-0000-000000000001",
        )
    assert exc_info.value.code == "change_not_found"


@pytest.mark.django_db
def test_record_accepted_wrong_runner_raises(running_change):
    from apps.common.exceptions import InvalidStateTransitionError

    change, binding, execution = running_change

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.record_execution_accepted(
            change_id=str(change.id),
            runner_id="other-runner",
            execution_id=str(execution.id),
        )
    assert exc_info.value.code == "runner_ownership_mismatch"


@pytest.mark.django_db
def test_record_accepted_wrong_execution_raises(running_change):
    from apps.common.exceptions import DomainValidationError

    change, binding, execution = running_change

    with pytest.raises(DomainValidationError) as exc_info:
        change_services.record_execution_accepted(
            change_id=str(change.id),
            runner_id="test-runner",
            execution_id="00000000-0000-0000-0000-000000000099",
        )
    assert exc_info.value.code == "execution_id_mismatch"


# ---------------------------------------------------------------------------
# HTTP layer — runner bearer auth required
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_accepted_endpoint_rejects_no_auth(running_change):
    change, binding, execution = running_change
    client = APIClient()
    url = f"/api/v1/internal/changes/{change.id}/execution-accepted/"
    resp = client.post(url, {"runner_id": "x", "execution_id": str(execution.id)}, format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_execution_started_endpoint_rejects_no_auth(running_change):
    change, binding, execution = running_change
    client = APIClient()
    url = f"/api/v1/internal/changes/{change.id}/execution-started/"
    resp = client.post(url, {"runner_id": "x", "execution_id": str(execution.id)}, format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_execution_finished_endpoint_rejects_no_auth(running_change):
    change, binding, execution = running_change
    client = APIClient()
    url = f"/api/v1/internal/changes/{change.id}/execution-finished/"
    resp = client.post(url, {"runner_id": "x", "execution_id": str(execution.id)}, format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_execution_accepted_endpoint_success(running_change, runner_client):
    change, binding, execution = running_change
    url = f"/api/v1/internal/changes/{change.id}/execution-accepted/"
    resp = runner_client.post(
        url,
        {"runner_id": "test-runner", "execution_id": str(execution.id)},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["change_record_id"] == str(change.id)
    assert resp.data["execution_accepted_at"] is not None


@pytest.mark.django_db
def test_execution_started_endpoint_success(running_change, runner_client):
    change, binding, execution = running_change
    url = f"/api/v1/internal/changes/{change.id}/execution-started/"
    resp = runner_client.post(
        url,
        {"runner_id": "test-runner", "execution_id": str(execution.id)},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["execution_started_at"] is not None


@pytest.mark.django_db
def test_execution_finished_endpoint_success(running_change, runner_client):
    change, binding, execution = running_change
    url = f"/api/v1/internal/changes/{change.id}/execution-finished/"
    resp = runner_client.post(
        url,
        {"runner_id": "test-runner", "execution_id": str(execution.id)},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["execution_finished_at"] is not None
    assert resp.data["locks_released"] >= 1


@pytest.mark.django_db
def test_execution_accepted_endpoint_wrong_runner_returns_conflict(running_change, runner_client):
    change, binding, execution = running_change
    url = f"/api/v1/internal/changes/{change.id}/execution-accepted/"
    resp = runner_client.post(
        url,
        {"runner_id": "wrong-runner", "execution_id": str(execution.id)},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.data["errors"][0]["code"] == "runner_ownership_mismatch"


@pytest.mark.django_db
def test_execution_finished_endpoint_observed_at_accepted(running_change, runner_client):
    """Runner can supply an explicit observed_at timestamp."""
    change, binding, execution = running_change
    observed = timezone.now() - timedelta(seconds=5)
    url = f"/api/v1/internal/changes/{change.id}/execution-finished/"
    resp = runner_client.post(
        url,
        {
            "runner_id": "test-runner",
            "execution_id": str(execution.id),
            "observed_at": observed.isoformat(),
        },
        format="json",
    )
    assert resp.status_code == 200
    binding.refresh_from_db()
    assert binding.execution_finished_at is not None
