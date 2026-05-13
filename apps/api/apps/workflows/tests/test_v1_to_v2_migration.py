"""
Tests for the v1→v2 draft migration service and endpoint.

Covers:
  - draft / published / superseded v1 workflows can be lifted
  - unsupported source schema is rejected
  - original workflow row is unchanged after migration
  - migrated workflow validates as v2
  - requires_review flag logic (AI source, shell steps)
  - API endpoint returns 201 and correct body
"""

import pytest

from apps.common.exceptions import DomainValidationError
from apps.runbooks import services as runbook_services
from apps.workflows import services
from apps.workflows.internal_clients import StubWorkflowTransformClient
from apps.workflows.models import Workflow
from apps.workflows.validators import validate_workflow_definition


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Deploy Service",
        slug="deploy-service",
        raw_content="Do step one",
    )


def _make_v1_draft(runbook, **kwargs):
    return services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        **kwargs,
    )


def _v1_def_with_types(step_types):
    """Build a minimal v1 definition with steps of the given types."""
    steps = []
    for i, st in enumerate(step_types, 1):
        step: dict = {
            "id": f"step-{i}",
            "name": f"Step {i}",
            "type": st,
            "risk": "low",
            "requiresApproval": False,
        }
        if st == "shell_command":
            step["command"] = "echo hello"
        if st == "approval":
            step["requiresApproval"] = True
        steps.append(step)
    return {"name": "Test Workflow", "steps": steps}


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lift_draft_v1_creates_new_draft(runbook):
    source = _make_v1_draft(runbook)
    assert source.status == Workflow.Status.DRAFT

    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.pk != source.pk
    assert result.status == Workflow.Status.DRAFT
    assert result.definition_schema_version == "workflow.schema.v2"
    assert result.runbook_id == source.runbook_id
    assert result.version == source.version + 1


@pytest.mark.django_db
def test_lift_published_v1_creates_new_draft(runbook):
    source = _make_v1_draft(runbook)
    services.publish_workflow(workflow=source)
    source.refresh_from_db()
    assert source.status == Workflow.Status.PUBLISHED

    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.pk != source.pk
    assert result.status == Workflow.Status.DRAFT
    assert result.definition_schema_version == "workflow.schema.v2"


@pytest.mark.django_db
def test_lift_superseded_v1_creates_new_draft(runbook):
    source = _make_v1_draft(runbook)
    services.publish_workflow(workflow=source)
    # Create and publish a second workflow to supersede the first.
    second = _make_v1_draft(runbook)
    services.publish_workflow(workflow=second)
    source.refresh_from_db()
    assert source.status == Workflow.Status.SUPERSEDED

    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.status == Workflow.Status.DRAFT
    assert result.definition_schema_version == "workflow.schema.v2"


@pytest.mark.django_db
def test_unsupported_source_schema_rejected(runbook):
    source = _make_v1_draft(runbook)
    # Directly set an unsupported schema version.
    Workflow.objects.filter(pk=source.pk).update(
        definition_schema_version="workflow.schema.v2"
    )
    source.refresh_from_db()

    with pytest.raises(DomainValidationError) as exc_info:
        services.create_v2_draft_from_v1(workflow=source)

    assert exc_info.value.code == "unsupported_source_schema"


@pytest.mark.django_db
def test_original_workflow_unchanged_after_migration(runbook):
    source = _make_v1_draft(runbook)
    original_version = source.version
    original_status = source.status
    original_definition = dict(source.definition)
    original_schema = source.definition_schema_version

    services.create_v2_draft_from_v1(workflow=source)

    source.refresh_from_db()
    assert source.version == original_version
    assert source.status == original_status
    assert source.definition == original_definition
    assert source.definition_schema_version == original_schema


@pytest.mark.django_db
def test_migrated_workflow_validates_as_v2(runbook):
    source = _make_v1_draft(runbook)
    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.validation_status == Workflow.ValidationStatus.VALID
    assert result.validation_report["valid"] is True
    # Raises nothing if valid.
    validate_workflow_definition(result.definition, "workflow.schema.v2")


@pytest.mark.django_db
def test_schema_version_fields_set_correctly(runbook):
    source = _make_v1_draft(runbook)
    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.definition_schema_version == "workflow.schema.v2"
    assert result.definition["schemaVersion"] == "2"
    assert result.catalog_version == "pilot.v1"
    assert result.definition["catalogVersion"] == "pilot.v1"


# ---------------------------------------------------------------------------
# Lift rule tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_manual_task_lifted_to_manual_task_action(runbook):
    source = _make_v1_draft(runbook)
    # StubWorkflowTransformClient produces manual_task steps by default.
    result = services.create_v2_draft_from_v1(workflow=source)

    for step in result.definition["steps"]:
        assert step["type"] == "manual_task"
        assert step["action"]["type"] == "manual_task"


@pytest.mark.django_db
def test_approval_step_lifted_to_approval_gate(runbook):
    source = _make_v1_draft(runbook)
    Workflow.objects.filter(pk=source.pk).update(
        definition=_v1_def_with_types(["approval"])
    )
    source.refresh_from_db()

    result = services.create_v2_draft_from_v1(workflow=source)

    step = result.definition["steps"][0]
    assert step["type"] == "approval_gate"
    assert step["action"]["type"] == "approval_gate"


@pytest.mark.django_db
def test_shell_command_lifted_with_command_in_params(runbook):
    source = _make_v1_draft(runbook)
    Workflow.objects.filter(pk=source.pk).update(
        definition=_v1_def_with_types(["shell_command"])
    )
    source.refresh_from_db()

    result = services.create_v2_draft_from_v1(workflow=source)

    step = result.definition["steps"][0]
    assert step["type"] == "shell_command"
    assert step["action"]["type"] == "shell_command"
    assert step["action"]["params"]["command"] == "echo hello"


@pytest.mark.django_db
def test_risk_preserved_after_lift(runbook):
    source = _make_v1_draft(runbook)
    Workflow.objects.filter(pk=source.pk).update(
        definition={
            "name": "Risk Test",
            "steps": [
                {
                    "id": "s1",
                    "name": "Critical Step",
                    "type": "manual_task",
                    "risk": "critical",
                    "requiresApproval": False,
                }
            ],
        }
    )
    source.refresh_from_db()

    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.definition["steps"][0]["risk"] == "critical"


@pytest.mark.django_db
def test_requires_approval_preserved_after_lift(runbook):
    source = _make_v1_draft(runbook)
    Workflow.objects.filter(pk=source.pk).update(
        definition={
            "name": "Approval Test",
            "steps": [
                {
                    "id": "s1",
                    "name": "Approved Step",
                    "type": "manual_task",
                    "risk": "high",
                    "requiresApproval": True,
                }
            ],
        }
    )
    source.refresh_from_db()

    result = services.create_v2_draft_from_v1(workflow=source)

    assert result.definition["steps"][0]["requiresApproval"] is True


@pytest.mark.django_db
def test_approval_timeout_seconds_preserved(runbook):
    source = _make_v1_draft(runbook)
    Workflow.objects.filter(pk=source.pk).update(
        definition={
            "name": "Timeout Test",
            "steps": [
                {
                    "id": "s1",
                    "name": "Gated Step",
                    "type": "approval",
                    "risk": "medium",
                    "requiresApproval": True,
                    "approvalTimeoutSeconds": 3600,
                }
            ],
        }
    )
    source.refresh_from_db()

    result = services.create_v2_draft_from_v1(workflow=source)

    step = result.definition["steps"][0]
    assert step.get("approvalTimeoutSeconds") == 3600


@pytest.mark.django_db
def test_defaults_applied_retry_and_idempotency(runbook):
    source = _make_v1_draft(runbook)
    result = services.create_v2_draft_from_v1(workflow=source)

    for step in result.definition["steps"]:
        assert step["retry"] == {"maxAttempts": 1}
        assert step["idempotency"] == {"mode": "none"}
        assert step["artifacts"] == []
        assert step["secrets"] == []


@pytest.mark.django_db
def test_top_level_secrets_empty(runbook):
    source = _make_v1_draft(runbook)
    result = services.create_v2_draft_from_v1(workflow=source)
    assert result.definition["secrets"] == []


# ---------------------------------------------------------------------------
# requires_review logic
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_requires_review_false_for_manual_workflow(runbook):
    source = _make_v1_draft(runbook, parse_source=Workflow.ParseSource.MANUAL)
    result = services.create_v2_draft_from_v1(workflow=source)
    # No shell steps → requires_review depends only on parse_source.
    assert result.requires_review is False


@pytest.mark.django_db
def test_requires_review_true_when_source_is_ai_parse(runbook):
    source = _make_v1_draft(
        runbook,
        requires_review=False,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )
    result = services.create_v2_draft_from_v1(workflow=source)
    assert result.requires_review is True


@pytest.mark.django_db
def test_requires_review_true_when_shell_step_introduced(runbook):
    source = _make_v1_draft(runbook, parse_source=Workflow.ParseSource.MANUAL)
    Workflow.objects.filter(pk=source.pk).update(
        definition=_v1_def_with_types(["shell_command"])
    )
    source.refresh_from_db()

    result = services.create_v2_draft_from_v1(workflow=source)
    assert result.requires_review is True


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_v2_draft_endpoint_returns_201(runbook, api_client_for_org):
    source = _make_v1_draft(runbook)
    client = api_client_for_org(runbook.organization)

    response = client.post(f"/api/v1/workflows/{source.id}/create-v2-draft/")

    assert response.status_code == 201
    body = response.json()
    assert body["definition_schema_version"] == "workflow.schema.v2"
    assert body["status"] == "draft"
    assert body["version"] == source.version + 1


@pytest.mark.django_db
def test_create_v2_draft_endpoint_returns_400_for_v2_source(runbook, api_client_for_org):
    source = _make_v1_draft(runbook)
    Workflow.objects.filter(pk=source.pk).update(
        definition_schema_version="workflow.schema.v2"
    )
    client = api_client_for_org(runbook.organization)

    response = client.post(f"/api/v1/workflows/{source.id}/create-v2-draft/")

    assert response.status_code == 400


@pytest.mark.django_db
def test_create_v2_draft_endpoint_wrong_org_returns_404(org, runbook, api_client_for_org):
    from apps.organizations.models import Organization

    source = _make_v1_draft(runbook)
    other_org = Organization.objects.create(name="Other", slug="other")
    client = api_client_for_org(other_org)

    response = client.post(f"/api/v1/workflows/{source.id}/create-v2-draft/")

    assert response.status_code == 404
