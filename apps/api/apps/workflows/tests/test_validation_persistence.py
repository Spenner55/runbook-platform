"""
Tests for validation_status/report persistence and v2 publish enforcement.

Covers:
- valid v2 workflow can be saved as draft
- invalid v2 draft is saved with validation_status=invalid
- invalid v2 workflow cannot be published
- valid v2 workflow can be published
- v1 publish path unchanged by v2 enforcement
- definition_hash_sha256 is stable for semantically identical JSON key orderings
- validate endpoint (POST /api/v1/workflows/validate/)
"""

import pytest

from apps.common.exceptions import DomainConflictError
from apps.runbooks import services as runbook_services
from apps.workflows import services
from apps.workflows.models import Workflow

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _minimal_v2_definition(**overrides) -> dict:
    doc = {
        "schemaVersion": "2",
        "name": "Test Workflow",
        "steps": [
            {
                "id": "s1",
                "name": "Do something",
                "type": "manual_task",
                "risk": "low",
                "action": {"type": "manual_task"},
            }
        ],
    }
    doc.update(overrides)
    return doc


def _invalid_v2_definition() -> dict:
    # Missing required 'action' field — fails JSON schema
    return {
        "schemaVersion": "2",
        "name": "Bad Workflow",
        "steps": [{"id": "s1", "name": "Step", "type": "manual_task", "risk": "low"}],
    }


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Deploy Service",
        slug="deploy-service",
        raw_content="Step one",
    )


# ---------------------------------------------------------------------------
# Valid v2 draft
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_valid_v2_draft_saved_with_valid_status(runbook):
    wf = services.create_workflow_v2_draft(
        runbook=runbook, definition=_minimal_v2_definition()
    )
    assert wf.status == Workflow.Status.DRAFT
    assert wf.definition_schema_version == "workflow.schema.v2"
    assert wf.validation_status == Workflow.ValidationStatus.VALID
    assert wf.validation_report["valid"] is True
    assert wf.validation_report["errors"] == []


@pytest.mark.django_db
def test_valid_v2_draft_stores_catalog_version(runbook):
    wf = services.create_workflow_v2_draft(
        runbook=runbook, definition=_minimal_v2_definition(catalogVersion="pilot.v1")
    )
    assert wf.catalog_version == "pilot.v1"


@pytest.mark.django_db
def test_valid_v2_draft_catalog_version_defaults_to_pilot_v1(runbook):
    definition = _minimal_v2_definition()
    assert "catalogVersion" not in definition
    wf = services.create_workflow_v2_draft(runbook=runbook, definition=definition)
    assert wf.catalog_version == "pilot.v1"


@pytest.mark.django_db
def test_valid_v2_draft_stores_definition_hash(runbook):
    definition = _minimal_v2_definition()
    wf = services.create_workflow_v2_draft(runbook=runbook, definition=definition)
    expected = services.compute_definition_hash(definition)
    assert wf.definition_hash_sha256 == expected
    assert len(wf.definition_hash_sha256) == 64


# ---------------------------------------------------------------------------
# Invalid v2 draft (saved but marked invalid)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_v2_draft_is_saved_with_invalid_status(runbook):
    wf = services.create_workflow_v2_draft(
        runbook=runbook, definition=_invalid_v2_definition()
    )
    assert wf.status == Workflow.Status.DRAFT
    assert wf.validation_status == Workflow.ValidationStatus.INVALID
    assert wf.validation_report["valid"] is False
    assert len(wf.validation_report["errors"]) >= 1


@pytest.mark.django_db
def test_invalid_v2_draft_report_contains_error_code(runbook):
    wf = services.create_workflow_v2_draft(
        runbook=runbook, definition=_invalid_v2_definition()
    )
    error = wf.validation_report["errors"][0]
    assert "code" in error
    assert "detail" in error


# ---------------------------------------------------------------------------
# Publish enforcement for v2
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_v2_cannot_publish(runbook):
    wf = services.create_workflow_v2_draft(
        runbook=runbook, definition=_invalid_v2_definition()
    )
    assert wf.validation_status == Workflow.ValidationStatus.INVALID
    with pytest.raises(DomainConflictError) as exc_info:
        services.publish_workflow(workflow=wf)
    assert exc_info.value.code == "workflow_invalid_definition"


@pytest.mark.django_db
def test_valid_v2_can_publish(runbook):
    wf = services.create_workflow_v2_draft(
        runbook=runbook, definition=_minimal_v2_definition()
    )
    assert wf.validation_status == Workflow.ValidationStatus.VALID
    published = services.publish_workflow(workflow=wf)
    assert published.status == Workflow.Status.PUBLISHED


# ---------------------------------------------------------------------------
# v1 publish path unchanged
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_v1_workflow_publish_unaffected_by_v2_check(runbook):
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    wf = services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    assert wf.definition_schema_version == "workflow.schema.v1"
    # v1 validation_status is not_applicable; publish must still work
    published = services.publish_workflow(workflow=wf)
    assert published.status == Workflow.Status.PUBLISHED


@pytest.mark.django_db
def test_v1_workflow_has_not_applicable_status(runbook):
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    wf = services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    assert wf.validation_status == Workflow.ValidationStatus.NOT_APPLICABLE
    assert wf.validation_report == {}


# ---------------------------------------------------------------------------
# definition_hash_sha256 stability
# ---------------------------------------------------------------------------


def test_hash_is_stable_regardless_of_key_ordering():
    definition_a = {
        "name": "Deploy",
        "schemaVersion": "2",
        "steps": [
            {
                "id": "s1",
                "name": "Step one",
                "type": "manual_task",
                "risk": "low",
                "action": {"type": "manual_task"},
            }
        ],
    }
    definition_b = {
        "steps": [
            {
                "action": {"type": "manual_task"},
                "id": "s1",
                "name": "Step one",
                "risk": "low",
                "type": "manual_task",
            }
        ],
        "schemaVersion": "2",
        "name": "Deploy",
    }
    assert services.compute_definition_hash(definition_a) == services.compute_definition_hash(
        definition_b
    )


def test_hash_differs_for_different_definitions():
    a = {"name": "A", "steps": []}
    b = {"name": "B", "steps": []}
    assert services.compute_definition_hash(a) != services.compute_definition_hash(b)


# ---------------------------------------------------------------------------
# validate_definition_report
# ---------------------------------------------------------------------------


def test_validate_definition_report_valid_v2():
    report = services.validate_definition_report(
        definition=_minimal_v2_definition(), schema_version="workflow.schema.v2"
    )
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["warnings"] == []


def test_validate_definition_report_invalid_v2():
    report = services.validate_definition_report(
        definition=_invalid_v2_definition(), schema_version="workflow.schema.v2"
    )
    assert report["valid"] is False
    assert len(report["errors"]) >= 1


def test_validate_definition_report_unsupported_version():
    report = services.validate_definition_report(
        definition={}, schema_version="workflow.schema.v99"
    )
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "unsupported_schema_version"


# ---------------------------------------------------------------------------
# Validate REST endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_validate_endpoint_valid_v2(api_client_for_org, org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/workflows/validate/",
        data={
            "definition": _minimal_v2_definition(),
            "schema_version": "workflow.schema.v2",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["valid"] is True


@pytest.mark.django_db
def test_validate_endpoint_invalid_v2(api_client_for_org, org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/workflows/validate/",
        data={
            "definition": _invalid_v2_definition(),
            "schema_version": "workflow.schema.v2",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["valid"] is False
    assert len(response.data["errors"]) >= 1


@pytest.mark.django_db
def test_validate_endpoint_defaults_to_v2_schema(api_client_for_org, org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/workflows/validate/",
        data={"definition": _minimal_v2_definition()},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["valid"] is True


@pytest.mark.django_db
def test_validate_endpoint_requires_auth(org):
    from rest_framework.test import APIClient

    client = APIClient()
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    response = client.post(
        "/api/v1/workflows/validate/",
        data={"definition": _minimal_v2_definition()},
        format="json",
    )
    assert response.status_code == 401
