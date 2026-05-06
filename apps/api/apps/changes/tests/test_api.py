"""API endpoint tests for changes app."""

import pytest
from django.core.exceptions import ValidationError
from rest_framework import status

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes.models import ChangeRecord


RUNNER_ID = "verification-api-runner"


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _configure_manual_profile(operation_profile):
    operation_profile.verification_mode = "manual"
    operation_profile.verification_plan_template = {
        "checks": [
            {
                "key": "manual-review",
                "name": "Manual production review",
                "type": "manual_attestation",
                "required": True,
                "manual_attestation_config": {"requires_independent_reviewer": False},
            }
        ]
    }
    operation_profile.save(
        update_fields=["verification_mode", "verification_plan_template", "updated_at"]
    )


def _prepare_verification_pending_change(change):
    from apps.approvals import services as approval_services
    from apps.changes import services as change_services
    from apps.executions import services as execution_services
    from apps.executions.models import Execution

    change = change_services.submit_change_record(change=change, actor=_system_actor())
    approval_services.decide_approval(
        approval_request=change.approval_request,
        decision="approved",
        actor=_system_actor(),
    )
    change.refresh_from_db()
    binding = change.execution_binding
    claim = execution_services.claim_next_execution(runner_id=RUNNER_ID)
    change_services.bind_execution(
        change_id=str(change.id),
        runner_id=RUNNER_ID,
        claim_token=claim["claim_token"],
        execution_id=str(binding.execution_id),
        dispatch_token=change_services.generate_dispatch_token(binding),
        requested_inputs_sha256=binding.requested_inputs_sha256,
        operation_profile_key=binding.operation_profile_key,
    )
    execution_services.complete_execution(
        execution=binding.execution,
        runner_id=RUNNER_ID,
        claim_token=claim["claim_token"],
        outcome=Execution.Status.SUCCEEDED,
    )
    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.VERIFICATION_PENDING
    return change


@pytest.mark.django_db
class TestOperationProfileListView:
    def test_lists_active_profiles(self, org, operation_profile, api_client_for_org):
        client = api_client_for_org(org)
        response = client.get("/api/v1/changes/operation-profiles/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["results"]
        assert len(data) == 1
        assert data[0]["key"] == "prod-maintenance"

    def test_excludes_inactive_profiles(
        self, org, operation_profile, api_client_for_org
    ):
        operation_profile.is_active = False
        operation_profile.save()
        client = api_client_for_org(org)
        response = client.get("/api/v1/changes/operation-profiles/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_excludes_other_org_profiles(
        self, org, operation_profile, api_client_for_org
    ):
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(name="Other Org", slug="other-org")
        client = api_client_for_org(other_org)
        response = client.get("/api/v1/changes/operation-profiles/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_unauthenticated_rejected(self, api_client):
        response = api_client.get("/api/v1/changes/operation-profiles/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestChangeRecordListView:
    def test_lists_org_scoped_changes(self, org, draft_change, api_client_for_org):
        client = api_client_for_org(org)
        response = client.get("/api/v1/changes/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["results"]
        assert len(data) == 1
        assert data[0]["id"] == str(draft_change.id)
        assert data[0]["title"] == draft_change.title

    def test_excludes_other_org_changes(self, org, draft_change, api_client_for_org):
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(name="Other", slug="other-list")
        client = api_client_for_org(other_org)
        response = client.get("/api/v1/changes/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_unauthenticated_rejected(self, api_client):
        response = api_client.get("/api/v1/changes/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestChangeRecordCreateView:
    def test_creates_draft(
        self, org, operation_profile, published_workflow, api_client_for_org
    ):
        client = api_client_for_org(org)
        payload = {
            "operation_profile_key": "prod-maintenance",
            "workflow_id": str(published_workflow.id),
            "title": "API Created Change",
            "justification": "Needed for test",
            "targets": [
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "environment": "production",
                }
            ],
        }
        response = client.post("/api/v1/changes/", payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["status"] == ChangeRecord.Status.DRAFT
        assert data["title"] == "API Created Change"
        assert len(data["targets"]) == 1

    def test_invalid_profile_returns_400(
        self, org, operation_profile, published_workflow, api_client_for_org
    ):
        client = api_client_for_org(org)
        payload = {
            "operation_profile_key": "nonexistent",
            "workflow_id": str(published_workflow.id),
            "title": "T",
            "targets": [
                {
                    "target_type": "server",
                    "target_identifier": "x",
                    "environment": "production",
                }
            ],
        }
        response = client.post("/api/v1/changes/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_production_target_returns_400(
        self, org, operation_profile, published_workflow, api_client_for_org
    ):
        client = api_client_for_org(org)
        payload = {
            "operation_profile_key": "prod-maintenance",
            "workflow_id": str(published_workflow.id),
            "title": "T",
            "targets": [
                {
                    "target_type": "server",
                    "target_identifier": "x",
                    "environment": "staging",
                }
            ],
        }
        response = client.post("/api/v1/changes/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unauthenticated_rejected(self, api_client, published_workflow):
        payload = {
            "operation_profile_key": "prod-maintenance",
            "workflow_id": str(published_workflow.id),
            "title": "T",
            "targets": [
                {
                    "target_type": "server",
                    "target_identifier": "x",
                    "environment": "production",
                }
            ],
        }
        response = api_client.post("/api/v1/changes/", payload, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestChangeRecordDetailView:
    def test_returns_change_detail(self, org, draft_change, api_client_for_org):
        client = api_client_for_org(org)
        response = client.get(f"/api/v1/changes/{draft_change.id}/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(draft_change.id)
        assert data["status"] == ChangeRecord.Status.DRAFT
        assert "targets" in data
        assert "operation_profile" in data

    def test_other_org_returns_404(self, org, draft_change, api_client_for_org):
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(name="Other", slug="other2")
        client = api_client_for_org(other_org)
        response = client.get(f"/api/v1/changes/{draft_change.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_nonexistent_returns_404(self, org, api_client_for_org):
        import uuid

        client = api_client_for_org(org)
        response = client.get(f"/api/v1/changes/{uuid.uuid4()}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestChangeRecordSubmitView:
    def test_submit_moves_to_pending_approval(
        self, org, draft_change, operation_profile, api_client_for_org
    ):
        operation_profile.requires_approval = True
        operation_profile.save()
        client = api_client_for_org(org)
        response = client.post(f"/api/v1/changes/{draft_change.id}/submit/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == ChangeRecord.Status.PENDING_APPROVAL

    def test_submit_idempotent_on_already_submitted_returns_409(
        self, org, draft_change, api_client_for_org
    ):
        from apps.changes import services as change_services

        change_services.submit_change_record(change=draft_change)
        client = api_client_for_org(org)
        response = client.post(f"/api/v1/changes/{draft_change.id}/submit/")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_submit_other_org_returns_404(self, org, draft_change, api_client_for_org):
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(name="Other3", slug="other3")
        client = api_client_for_org(other_org)
        response = client.post(f"/api/v1/changes/{draft_change.id}/submit/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_submit_no_justification_returns_400(
        self, org, operation_profile, published_workflow, api_client_for_org
    ):
        from apps.audit.models import AuditEvent
        from apps.audit.services import AuditActor
        from apps.changes import services as change_services

        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="No Justification",
            justification="",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
            actor=actor,
        )
        client = api_client_for_org(org)
        response = client.post(f"/api/v1/changes/{change.id}/submit/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestChangeVerificationPublicApi:
    def test_fetches_verification_checklist(
        self, org, draft_change, api_client_for_org
    ):
        change = _prepare_verification_pending_change(draft_change)
        client = api_client_for_org(org)

        response = client.get(f"/api/v1/changes/{change.id}/verification-plan/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["change_record_id"] == str(change.id)
        assert data["required_check_count"] == 1
        assert data["checks"][0]["key"] == "runner-health-check"

    def test_verification_plan_is_org_scoped(
        self, org, draft_change, api_client_for_org
    ):
        from apps.changes import services as change_services
        from apps.organizations.models import Organization

        change = change_services.submit_change_record(
            change=draft_change, actor=_system_actor()
        )
        other_org = Organization.objects.create(name="Other", slug="other-verif")
        client = api_client_for_org(other_org)

        response = client.get(f"/api/v1/changes/{change.id}/verification-plan/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_verification_plan_requires_auth(self, draft_change, api_client):
        response = api_client.get(
            f"/api/v1/changes/{draft_change.id}/verification-plan/"
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_submits_manual_verification_result(
        self, org, operation_profile, draft_change, api_client_for_org
    ):
        _configure_manual_profile(operation_profile)
        change = _prepare_verification_pending_change(draft_change)
        client = api_client_for_org(org)

        response = client.post(
            f"/api/v1/changes/{change.id}/verification-results/",
            {
                "check_key": "manual-review",
                "outcome": "passed",
                "manual_attestation_text": "Production health was checked.",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["validation_status"] == "accepted"
        assert data["check_key"] == "manual-review"
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.VERIFIED

    def test_close_success_only_after_verified(
        self, org, operation_profile, draft_change, api_client_for_org
    ):
        _configure_manual_profile(operation_profile)
        change = _prepare_verification_pending_change(draft_change)
        client = api_client_for_org(org)
        result_response = client.post(
            f"/api/v1/changes/{change.id}/verification-results/",
            {
                "check_key": "manual-review",
                "outcome": "passed",
                "manual_attestation_text": "Production health was checked.",
            },
            format="json",
        )
        assert result_response.status_code == status.HTTP_201_CREATED

        response = client.post(
            f"/api/v1/changes/{change.id}/close/",
            {"outcome": "success", "summary": "Change verified and closed."},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["outcome"] == "success"
        assert data["verification_summary"]["unmet_required_check_keys"] == []
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.CLOSED
        assert change.closed_at is not None

    def test_close_success_rejected_while_verification_pending(
        self, org, operation_profile, draft_change, api_client_for_org
    ):
        _configure_manual_profile(operation_profile)
        change = _prepare_verification_pending_change(draft_change)
        client = api_client_for_org(org)

        response = client.post(
            f"/api/v1/changes/{change.id}/close/",
            {"outcome": "success", "summary": "Trying to close early."},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["errors"][0]["code"] == "change_not_verified"
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.VERIFICATION_PENDING

    def test_duplicate_closure_rejected(
        self, org, operation_profile, draft_change, api_client_for_org
    ):
        _configure_manual_profile(operation_profile)
        change = _prepare_verification_pending_change(draft_change)
        client = api_client_for_org(org)
        client.post(
            f"/api/v1/changes/{change.id}/verification-results/",
            {
                "check_key": "manual-review",
                "outcome": "passed",
                "manual_attestation_text": "Production health was checked.",
            },
            format="json",
        )
        first = client.post(
            f"/api/v1/changes/{change.id}/close/",
            {"outcome": "success", "summary": "Closed once."},
            format="json",
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = client.post(
            f"/api/v1/changes/{change.id}/close/",
            {"outcome": "success", "summary": "Closed twice."},
            format="json",
        )

        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["errors"][0]["code"] == "change_already_closed"

    def test_closure_is_immutable(
        self, org, operation_profile, draft_change, api_client_for_org
    ):
        _configure_manual_profile(operation_profile)
        change = _prepare_verification_pending_change(draft_change)
        client = api_client_for_org(org)
        client.post(
            f"/api/v1/changes/{change.id}/verification-results/",
            {
                "check_key": "manual-review",
                "outcome": "passed",
                "manual_attestation_text": "Production health was checked.",
            },
            format="json",
        )
        response = client.post(
            f"/api/v1/changes/{change.id}/close/",
            {"outcome": "success", "summary": "Immutable closure."},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

        change.refresh_from_db()
        closure = change.closure
        closure.summary = "Mutated"
        with pytest.raises(ValidationError):
            closure.save()
        with pytest.raises(ValidationError):
            closure.delete()
