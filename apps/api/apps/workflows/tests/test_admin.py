import pytest
from django.contrib.admin.sites import AdminSite

from apps.runbooks import services as runbook_services
from apps.workflows import services as wf_services
from apps.workflows.admin import WorkflowAdmin
from apps.workflows.internal_clients import StubWorkflowTransformClient
from apps.workflows.models import Workflow


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Admin Test Runbook",
        slug="admin-test",
        raw_content="Deploy\nVerify",
    )


@pytest.fixture
def draft_workflow(runbook):
    return wf_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )


@pytest.fixture
def published_workflow(draft_workflow):
    return wf_services.publish_workflow(workflow=draft_workflow)


@pytest.fixture
def superseded_workflow(runbook, published_workflow):
    new_wf = wf_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    wf_services.publish_workflow(workflow=new_wf)
    published_workflow.refresh_from_db()
    return published_workflow


@pytest.mark.django_db
class TestWorkflowAdminReadOnly:
    def _admin(self, rf):
        admin_instance = WorkflowAdmin(Workflow, AdminSite())
        request = rf.get("/")
        request.user = None
        return admin_instance, request

    def test_published_workflow_definition_is_readonly(self, published_workflow, rf):
        admin_instance, request = self._admin(rf)
        readonly = admin_instance.get_readonly_fields(request, obj=published_workflow)
        assert "definition" in readonly
        assert "name" in readonly
        assert "status" in readonly

    def test_superseded_workflow_definition_is_readonly(self, superseded_workflow, rf):
        admin_instance, request = self._admin(rf)
        readonly = admin_instance.get_readonly_fields(request, obj=superseded_workflow)
        assert "definition" in readonly

    def test_draft_workflow_definition_is_editable(self, draft_workflow, rf):
        admin_instance, request = self._admin(rf)
        readonly = admin_instance.get_readonly_fields(request, obj=draft_workflow)
        assert "definition" not in readonly

    def test_published_workflow_cannot_be_deleted(self, published_workflow, rf):
        admin_instance, request = self._admin(rf)
        assert not admin_instance.has_delete_permission(request, obj=published_workflow)

    def test_superseded_workflow_cannot_be_deleted(self, superseded_workflow, rf):
        admin_instance, request = self._admin(rf)
        assert not admin_instance.has_delete_permission(
            request, obj=superseded_workflow
        )

    def test_draft_workflow_delete_not_blocked_by_our_guard(self, draft_workflow, rf):
        """The guard must not block draft deletion — it only returns False for published/superseded."""
        from unittest.mock import MagicMock

        admin_instance = WorkflowAdmin(Workflow, AdminSite())
        request = rf.get("/")
        request.user = MagicMock()
        request.user.has_perm.return_value = True
        assert admin_instance.has_delete_permission(request, obj=draft_workflow)

    def test_always_readonly_fields_present_for_any_status(self, draft_workflow, rf):
        admin_instance, request = self._admin(rf)
        readonly = admin_instance.get_readonly_fields(request, obj=draft_workflow)
        for field in ("id", "created_at", "updated_at", "version"):
            assert field in readonly, f"Expected {field} always readonly"
