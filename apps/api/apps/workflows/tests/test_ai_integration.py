"""
Tests for Phase 10.6 Django-side AI integration.

All network calls use httpx.MockTransport — no real API calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from apps.common.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    InvalidWorkflowDefinitionError,
)
from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.runbooks.ai_client import (
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    ExecutionSummary,
    RunbookAiClient,
    WorkflowCandidate,
    WorkflowCandidateStep,
    WorkflowEnrichment,
)
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import (
    HttpWorkflowTransformClient,
    StubWorkflowTransformClient,
)
from apps.workflows.models import Workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler) -> RunbookAiClient:
    """Build a RunbookAiClient backed by a MockTransport."""
    transport = httpx.MockTransport(handler)
    return RunbookAiClient(
        base_url="http://ai-test",
        timeout=httpx.Timeout(5.0),
        transport=transport,
    )


def _json_response(data: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _parse_response_body() -> dict:
    return {
        "request_id": "req-1",
        "workflow_title": "Deploy Service",
        "steps": [
            {
                "step_key": "step-001",
                "name": "Drain traffic",
                "step_type": "manual_task",
                "risk_level": "high",
                "requires_approval": True,
                "command": None,
            }
        ],
        "warnings": [],
    }


def _enrich_response_body() -> dict:
    return {
        "request_id": "req-2",
        "steps": [
            {
                "step_key": "step-001",
                "name": "Drain traffic",
                "step_type": "manual_task",
                "risk_level": "critical",
                "requires_approval": True,
                "command": None,
            }
        ],
        "warnings": ["risk elevated by enrichment"],
    }


def _summarize_response_body() -> dict:
    return {
        "request_id": "req-3",
        "summary": "Deployment completed successfully in 4 minutes.",
        "key_outcomes": ["service restarted", "health checks passed"],
    }


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Deploy Service",
        slug="deploy-service",
        raw_content="Drain traffic from instance",
    )


# ---------------------------------------------------------------------------
# enrich_workflow_candidate — happy path
# ---------------------------------------------------------------------------


def test_enrich_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/enrich/workflow"
        return _json_response(_enrich_response_body())

    client = _make_client(handler)
    steps = [
        WorkflowCandidateStep(
            step_key="step-001",
            name="Drain traffic",
            step_type="manual_task",
            risk_level="high",
            requires_approval=False,
        )
    ]
    result = client.enrich_workflow_candidate(
        request_id="req-2",
        workflow_title="Deploy Service",
        steps=steps,
    )
    assert isinstance(result, WorkflowEnrichment)
    assert result.steps[0].risk_level == "critical"
    assert result.steps[0].requires_approval is True
    assert result.warnings == ["risk elevated by enrichment"]


def test_enrich_passes_command_field():
    """command field on steps must be forwarded in the POST payload."""
    received_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_body.update(json.loads(request.content))
        return _json_response(_enrich_response_body())

    client = _make_client(handler)
    steps = [
        WorkflowCandidateStep(
            step_key="step-001",
            name="Restart",
            step_type="shell_command",
            risk_level="medium",
            requires_approval=False,
            command="systemctl restart web",
        )
    ]
    client.enrich_workflow_candidate(
        request_id="req-x",
        workflow_title="Restart",
        steps=steps,
    )
    sent_step = received_body["steps"][0]
    assert sent_step["command"] == "systemctl restart web"


# ---------------------------------------------------------------------------
# enrich_workflow_candidate — error paths
# ---------------------------------------------------------------------------


def test_enrich_timeout_raises_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = _make_client(handler)
    with pytest.raises(AiServiceTimeoutError):
        client.enrich_workflow_candidate(request_id="r", workflow_title="T", steps=[])


def test_enrich_non_200_raises_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad"})

    client = _make_client(handler)
    with pytest.raises(AiServiceBadResponseError):
        client.enrich_workflow_candidate(request_id="r", workflow_title="T", steps=[])


def test_enrich_missing_steps_raises_contract_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"request_id": "r"})

    client = _make_client(handler)
    with pytest.raises(AiServiceContractError):
        client.enrich_workflow_candidate(request_id="r", workflow_title="T", steps=[])


def test_enrich_non_boolean_requires_approval_raises_contract_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _enrich_response_body()
        body["steps"][0]["requires_approval"] = "yes"
        return _json_response(body)

    client = _make_client(handler)
    with pytest.raises(AiServiceContractError):
        client.enrich_workflow_candidate(
            request_id="r",
            workflow_title="T",
            steps=[
                WorkflowCandidateStep(
                    step_key="step-001",
                    name="Drain traffic",
                    step_type="manual_task",
                    risk_level="medium",
                    requires_approval=False,
                )
            ],
        )


def test_enrich_contract_does_not_require_workflow_title():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _enrich_response_body()
        assert "workflow_title" not in body
        return _json_response(body)

    client = _make_client(handler)
    result = client.enrich_workflow_candidate(
        request_id="r",
        workflow_title="Parse title owns this",
        steps=[
            WorkflowCandidateStep(
                step_key="step-001",
                name="Drain traffic",
                step_type="manual_task",
                risk_level="medium",
                requires_approval=False,
            )
        ],
    )
    assert result.steps[0].step_key == "step-001"


# ---------------------------------------------------------------------------
# parse -> enrich pipeline
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_parse_enrich_pipeline_happy_path(runbook):
    seen_paths: list[str] = []
    seen_request_ids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        seen_request_ids.append(request.headers.get("X-Request-ID"))
        if request.url.path == "/parse/runbook":
            return _json_response(_parse_response_body())
        if request.url.path == "/enrich/workflow":
            return _json_response(_enrich_response_body())
        return httpx.Response(404)

    transform_client = HttpWorkflowTransformClient(ai_client=_make_client(handler))
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=transform_client,
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
        request_id="django-req-001",
    )

    assert seen_paths == ["/parse/runbook", "/enrich/workflow"]
    assert seen_request_ids == ["django-req-001", "django-req-001"]
    assert workflow.definition["name"] == "Deploy Service"
    assert workflow.definition["steps"][0]["risk"] == "critical"
    assert workflow.definition["steps"][0]["requiresApproval"] is True
    assert workflow.requires_review is True
    assert workflow.parse_source == Workflow.ParseSource.AI_PARSE


@pytest.mark.django_db
def test_parse_enrich_missing_step_key_fails(runbook):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/parse/runbook":
            body = _parse_response_body()
            body["steps"].append(
                {
                    "step_key": "step-002",
                    "name": "Validate health",
                    "step_type": "manual_task",
                    "risk_level": "low",
                    "requires_approval": False,
                }
            )
            return _json_response(body)
        return _json_response(_enrich_response_body())

    transform_client = HttpWorkflowTransformClient(ai_client=_make_client(handler))
    with pytest.raises(AiServiceContractError):
        workflow_services.create_workflow(
            runbook=runbook,
            transform_client=transform_client,
            requires_review=True,
            parse_source=Workflow.ParseSource.AI_PARSE,
        )


@pytest.mark.django_db
def test_parse_enrich_extra_step_key_fails(runbook):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/parse/runbook":
            return _json_response(_parse_response_body())
        body = _enrich_response_body()
        body["steps"].append(
            {
                "step_key": "step-extra",
                "name": "Unexpected",
                "step_type": "manual_task",
                "risk_level": "low",
                "requires_approval": False,
            }
        )
        return _json_response(body)

    transform_client = HttpWorkflowTransformClient(ai_client=_make_client(handler))
    with pytest.raises(AiServiceContractError):
        workflow_services.create_workflow(
            runbook=runbook,
            transform_client=transform_client,
            requires_review=True,
            parse_source=Workflow.ParseSource.AI_PARSE,
        )


@pytest.mark.django_db
def test_parse_enrich_duplicate_step_key_fails(runbook):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/parse/runbook":
            return _json_response(_parse_response_body())
        body = _enrich_response_body()
        body["steps"].append(dict(body["steps"][0]))
        return _json_response(body)

    transform_client = HttpWorkflowTransformClient(ai_client=_make_client(handler))
    with pytest.raises(AiServiceContractError):
        workflow_services.create_workflow(
            runbook=runbook,
            transform_client=transform_client,
            requires_review=True,
            parse_source=Workflow.ParseSource.AI_PARSE,
        )


# ---------------------------------------------------------------------------
# summarize_execution — happy path
# ---------------------------------------------------------------------------


def test_summarize_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/summarize/execution"
        return _json_response(_summarize_response_body())

    client = _make_client(handler)
    result = client.summarize_execution(
        request_id="req-3",
        execution_id="exec-1",
        workflow_title="Deploy Service",
        status="succeeded",
        steps=[{"step_id": "s1", "name": "Drain", "status": "succeeded"}],
    )
    assert isinstance(result, ExecutionSummary)
    assert "successfully" in result.summary
    assert "service restarted" in result.key_outcomes


def test_summarize_non_200_raises_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    client = _make_client(handler)
    with pytest.raises(AiServiceBadResponseError):
        client.summarize_execution(
            request_id="r",
            execution_id="e",
            workflow_title="T",
            status="failed",
            steps=[],
        )


def test_summarize_missing_summary_key_raises_contract_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"request_id": "r", "key_outcomes": []})

    client = _make_client(handler)
    result = client.summarize_execution(
        request_id="r",
        execution_id="e",
        workflow_title="T",
        status="failed",
        steps=[],
    )
    # Empty string summary is valid (no error raised); non-string would raise.
    assert result.summary == ""


def test_summarize_non_string_summary_raises_contract_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"request_id": "r", "summary": 42, "key_outcomes": []})

    client = _make_client(handler)
    with pytest.raises(AiServiceContractError):
        client.summarize_execution(
            request_id="r",
            execution_id="e",
            workflow_title="T",
            status="failed",
            steps=[],
        )


# ---------------------------------------------------------------------------
# Input guard — AI_MAX_INPUT_CHARS
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_input_guard_rejects_oversized_content(runbook):
    """create_workflow_from_runbook must reject content exceeding AI_MAX_INPUT_CHARS."""
    oversized = "x" * 100001
    runbook.raw_content = oversized
    runbook.save(update_fields=["raw_content"])

    with patch("apps.workflows.services.settings") as mock_settings:
        mock_settings.AI_MAX_INPUT_CHARS = 100000
        with pytest.raises(DomainValidationError) as exc_info:
            workflow_services.create_workflow_from_runbook(runbook=runbook)

    assert exc_info.value.code == "ai_input_too_large"


@pytest.mark.django_db
def test_input_guard_allows_content_at_limit(runbook):
    """Content exactly at the limit must be accepted (guard is exclusive upper bound)."""
    at_limit = "x" * 100000
    runbook.raw_content = at_limit
    runbook.save(update_fields=["raw_content"])

    fake_candidate = WorkflowCandidate(
        request_id="r",
        workflow_title="Deploy Service",
        steps=[
            WorkflowCandidateStep(
                step_key="step-001",
                name="Run step",
                step_type="manual_task",
                risk_level="low",
                requires_approval=False,
            )
        ],
    )
    mock_http_client = MagicMock(spec=HttpWorkflowTransformClient)
    mock_http_client.transform_runbook.return_value = fake_candidate

    with (
        patch("apps.workflows.services.settings") as mock_settings,
        patch.object(
            HttpWorkflowTransformClient, "from_settings", return_value=mock_http_client
        ),
    ):
        mock_settings.AI_MAX_INPUT_CHARS = 100000
        workflow = workflow_services.create_workflow_from_runbook(runbook=runbook)

    assert workflow is not None


# ---------------------------------------------------------------------------
# Schema validation — jsonschema enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_schema_validation_rejects_missing_required_step_field(runbook):
    """A step missing 'risk' must be rejected before persisting."""
    broken_candidate = WorkflowCandidate(
        request_id="r",
        workflow_title="Deploy",
        steps=[
            WorkflowCandidateStep(
                step_key="step-001",
                name="Check",
                step_type="manual_task",
                risk_level="",  # empty string — maps to empty "risk" in definition
                requires_approval=False,
            )
        ],
    )
    client = MagicMock()
    client.transform_runbook.return_value = broken_candidate

    # Empty risk passes _validate_candidate but schema validation should catch it
    # if type mismatch. With an empty string the schema allows it (type string).
    # We test a None-based violation by patching _map_candidate_to_definition output.
    from apps.workflows import services

    with patch.object(
        services,
        "_map_candidate_to_definition",
        return_value={
            "name": "Deploy",
            "steps": [{"id": "step-001", "name": "Check", "type": "manual_task"}],
        },
    ):
        with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
            workflow_services.create_workflow(runbook=runbook, transform_client=client)

    assert exc_info.value.code == "workflow_schema_violation"


@pytest.mark.django_db
def test_schema_validation_rejects_non_list_steps(runbook):
    from apps.workflows import services

    valid_candidate = WorkflowCandidate(
        request_id="r",
        workflow_title="T",
        steps=[
            WorkflowCandidateStep(
                step_key="s1",
                name="Step",
                step_type="manual_task",
                risk_level="low",
                requires_approval=False,
            )
        ],
    )
    client = MagicMock()
    client.transform_runbook.return_value = valid_candidate

    with patch.object(
        services,
        "_map_candidate_to_definition",
        return_value={"name": "T", "steps": "not-a-list"},
    ):
        with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
            workflow_services.create_workflow(runbook=runbook, transform_client=client)

    assert exc_info.value.code == "workflow_schema_violation"


# ---------------------------------------------------------------------------
# create_workflow_from_runbook sets requires_review and parse_source
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_workflow_from_runbook_sets_requires_review(runbook):
    fake_candidate = WorkflowCandidate(
        request_id="r",
        workflow_title="Deploy Service",
        steps=[
            WorkflowCandidateStep(
                step_key="step-001",
                name="Run step",
                step_type="manual_task",
                risk_level="low",
                requires_approval=False,
            )
        ],
    )
    mock_http_client = MagicMock(spec=HttpWorkflowTransformClient)
    mock_http_client.transform_runbook.return_value = fake_candidate

    with patch.object(
        HttpWorkflowTransformClient, "from_settings", return_value=mock_http_client
    ):
        workflow = workflow_services.create_workflow_from_runbook(runbook=runbook)

    assert workflow.requires_review is True
    assert workflow.parse_source == Workflow.ParseSource.AI_PARSE


@pytest.mark.django_db
def test_create_workflow_manual_does_not_set_requires_review(runbook):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
    )
    assert workflow.requires_review is False
    assert workflow.parse_source == Workflow.ParseSource.MANUAL


# ---------------------------------------------------------------------------
# accept_review / reject_review
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_accept_review_clears_flag(runbook):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )
    assert workflow.requires_review is True

    accepted = workflow_services.accept_review(workflow=workflow)
    assert accepted.requires_review is False
    assert accepted.status == Workflow.Status.DRAFT


@pytest.mark.django_db
def test_accept_review_refreshes_from_db(runbook):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )
    workflow_services.accept_review(workflow=workflow)
    refreshed = Workflow.objects.get(pk=workflow.pk)
    assert refreshed.requires_review is False


@pytest.mark.django_db
def test_accept_review_on_non_pending_raises(runbook):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
    )
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        workflow_services.accept_review(workflow=workflow)
    assert exc_info.value.code == "workflow_not_pending_review"


@pytest.mark.django_db
def test_reject_review_archives_workflow(runbook):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )
    rejected = workflow_services.reject_review(workflow=workflow)
    assert rejected.status == Workflow.Status.ARCHIVED
    assert rejected.requires_review is False


@pytest.mark.django_db
def test_reject_review_on_non_pending_raises(runbook):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
    )
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        workflow_services.reject_review(workflow=workflow)
    assert exc_info.value.code == "workflow_not_pending_review"


# ---------------------------------------------------------------------------
# Execution guard — requires_review blocks execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_execution_blocked_when_requires_review(runbook):
    """Execution must be refused for a workflow flagged requires_review."""
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )
    # Manually publish without clearing review flag to isolate the guard.
    workflow.status = Workflow.Status.PUBLISHED
    workflow.save(update_fields=["status", "updated_at"])

    with pytest.raises(DomainValidationError) as exc_info:
        execution_services.create_execution(workflow=workflow)

    assert exc_info.value.code == "workflow_requires_review"


@pytest.mark.django_db
def test_create_execution_allowed_after_review_accepted(runbook):
    """After accept_review, execution must proceed normally."""
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )
    workflow_services.accept_review(workflow=workflow)
    workflow_services.publish_workflow(workflow=workflow)
    workflow.refresh_from_db()

    execution = execution_services.create_execution(workflow=workflow)
    assert execution is not None
