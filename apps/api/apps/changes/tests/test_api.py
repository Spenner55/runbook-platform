"""API endpoint tests for changes app."""

import pytest
from rest_framework import status

from apps.changes.models import ChangeRecord


@pytest.mark.django_db
class TestOperationProfileListView:
    def test_lists_active_profiles(self, org, operation_profile, api_client_for_org):
        client = api_client_for_org(org)
        response = client.get("/api/v1/changes/operation-profiles/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["results"]
        assert len(data) == 1
        assert data[0]["key"] == "prod-maintenance"

    def test_excludes_inactive_profiles(self, org, operation_profile, api_client_for_org):
        operation_profile.is_active = False
        operation_profile.save()
        client = api_client_for_org(org)
        response = client.get("/api/v1/changes/operation-profiles/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_excludes_other_org_profiles(self, org, operation_profile, api_client_for_org):
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
class TestChangeRecordCreateView:
    def test_creates_draft(self, org, operation_profile, published_workflow, api_client_for_org):
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

    def test_invalid_profile_returns_400(self, org, operation_profile, published_workflow, api_client_for_org):
        client = api_client_for_org(org)
        payload = {
            "operation_profile_key": "nonexistent",
            "workflow_id": str(published_workflow.id),
            "title": "T",
            "targets": [{"target_type": "server", "target_identifier": "x", "environment": "production"}],
        }
        response = client.post("/api/v1/changes/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_production_target_returns_400(self, org, operation_profile, published_workflow, api_client_for_org):
        client = api_client_for_org(org)
        payload = {
            "operation_profile_key": "prod-maintenance",
            "workflow_id": str(published_workflow.id),
            "title": "T",
            "targets": [{"target_type": "server", "target_identifier": "x", "environment": "staging"}],
        }
        response = client.post("/api/v1/changes/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unauthenticated_rejected(self, api_client, published_workflow):
        payload = {
            "operation_profile_key": "prod-maintenance",
            "workflow_id": str(published_workflow.id),
            "title": "T",
            "targets": [{"target_type": "server", "target_identifier": "x", "environment": "production"}],
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
    def test_submit_moves_to_pending_approval(self, org, draft_change, operation_profile, api_client_for_org):
        operation_profile.requires_approval = True
        operation_profile.save()
        client = api_client_for_org(org)
        response = client.post(f"/api/v1/changes/{draft_change.id}/submit/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == ChangeRecord.Status.PENDING_APPROVAL

    def test_submit_idempotent_on_already_submitted_returns_409(self, org, draft_change, api_client_for_org):
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

    def test_submit_no_justification_returns_400(self, org, operation_profile, published_workflow, api_client_for_org):
        from apps.changes import services as change_services
        from apps.audit.services import AuditActor
        from apps.audit.models import AuditEvent
        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="No Justification",
            justification="",
            targets=[{"target_type": "server", "target_identifier": "srv", "environment": "production"}],
            actor=actor,
        )
        client = api_client_for_org(org)
        response = client.post(f"/api/v1/changes/{change.id}/submit/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
