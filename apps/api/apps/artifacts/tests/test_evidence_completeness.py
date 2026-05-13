"""
Tests: evidence completeness helper (Phase B.5).

Covers:
- step with no required artifact declarations → complete
- step with required declaration, no uploaded artifact → incomplete
- step with required declaration, matching uploaded artifact → complete
- step with multiple required declarations, partial upload → incomplete
- declaration key matched by metadata.declaration_key
- non-required declarations do not affect completeness
- v1 step (no artifacts in snapshot) → always complete
"""

import io

import pytest

from apps.artifacts import services as artifact_services
from apps.executions import services as exec_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as wf_services

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _publish_v2(runbook, definition):
    wf = wf_services.create_workflow_v2_draft(runbook=runbook, definition=definition)
    return wf_services.publish_workflow(workflow=wf)


def _v2_def(steps) -> dict:
    return {
        "schemaVersion": "2",
        "name": "Evidence Test Workflow",
        "steps": steps,
    }


def _file_obj(content=b"test content"):
    f = io.BytesIO(content)
    f.name = "artifact.txt"
    f.size = len(content)
    f.chunks = lambda: [content]
    return f


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Evidence Test",
        slug="evidence-test",
        raw_content="step one",
    )


@pytest.fixture(autouse=True)
def artifact_settings(settings):
    settings.ARTIFACT_REQUIRE_CHECKSUM = False
    settings.ARTIFACT_ALLOWED_MIME_TYPES = []
    settings.ARTIFACT_MAX_METADATA_BYTES = 8192


@pytest.fixture
def claimed_result_for_step(org, runbook):
    """Return a claim result for a v2 workflow with one required artifact declaration."""
    steps = [
        {
            "id": "s1",
            "name": "Run step",
            "type": "shell_command",
            "risk": "low",
            "action": {"type": "shell_command", "params": {"command": "echo hi"}},
            "artifacts": [
                {"key": "output_log", "kind": "file", "path": "out.log", "required": True},
                {"key": "report", "kind": "report", "path": "report.json", "required": False},
            ],
        }
    ]
    wf = _publish_v2(runbook, _v2_def(steps))
    exec_services.create_execution(workflow=wf)
    return exec_services.claim_next_execution(runner_id="runner-ev")


@pytest.fixture
def claimed_step(claimed_result_for_step):
    return claimed_result_for_step["execution"].steps.first()


@pytest.fixture
def claimed_execution(claimed_result_for_step):
    return claimed_result_for_step["execution"]


@pytest.fixture
def claim_token(claimed_result_for_step):
    return str(claimed_result_for_step["claim_token"])


# ---------------------------------------------------------------------------
# No declarations → always complete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_with_no_artifact_declarations_is_complete(org, runbook):
    steps = [
        {
            "id": "s1",
            "name": "No artifacts",
            "type": "shell_command",
            "risk": "low",
            "action": {"type": "shell_command", "params": {"command": "echo hi"}},
            # no artifacts key — all complete
        }
    ]
    wf = _publish_v2(runbook, _v2_def(steps))
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-no-art")
    step = result["execution"].steps.first()

    status = artifact_services.check_step_evidence_completeness(step)
    assert status["complete"] is True
    assert status["required_keys"] == []
    assert status["missing_keys"] == []


@pytest.mark.django_db
def test_v1_step_with_no_snapshot_artifacts_is_complete(org, runbook):
    """v1 steps have no artifacts key in snapshot — treated as complete."""
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    wf = wf_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    wf = wf_services.publish_workflow(workflow=wf)
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-v1-ev")
    step = result["execution"].steps.first()

    status = artifact_services.check_step_evidence_completeness(step)
    assert status["complete"] is True


# ---------------------------------------------------------------------------
# Required declaration, no upload → incomplete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_required_artifact_missing_marks_evidence_incomplete(claimed_step):
    status = artifact_services.check_step_evidence_completeness(claimed_step)
    assert status["complete"] is False
    assert "output_log" in status["required_keys"]
    assert "output_log" in status["missing_keys"]
    assert status["satisfied_keys"] == []


@pytest.mark.django_db
def test_non_required_declaration_does_not_affect_completeness(claimed_step):
    # "report" is required=False — should not appear in required_keys
    status = artifact_services.check_step_evidence_completeness(claimed_step)
    assert "report" not in status["required_keys"]


# ---------------------------------------------------------------------------
# Upload satisfies the required declaration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_with_declaration_key_satisfies_requirement(
    claimed_execution, claimed_step, claim_token, artifact_media_root
):
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=claimed_step,
        runner_id="runner-ev",
        claim_token=claim_token,
        kind="file",
        name="output_log.txt",
        file_obj=_file_obj(),
        metadata={"declaration_key": "output_log"},
    )

    status = artifact_services.check_step_evidence_completeness(claimed_step)
    assert status["complete"] is True
    assert "output_log" in status["satisfied_keys"]
    assert status["missing_keys"] == []


# ---------------------------------------------------------------------------
# Partial satisfaction
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_partial_satisfaction_leaves_evidence_incomplete(org, runbook, artifact_media_root):
    steps = [
        {
            "id": "s1",
            "name": "Two required",
            "type": "shell_command",
            "risk": "low",
            "action": {"type": "shell_command", "params": {"command": "echo hi"}},
            "artifacts": [
                {"key": "log_a", "kind": "file", "path": "log_a.txt", "required": True},
                {"key": "log_b", "kind": "file", "path": "log_b.txt", "required": True},
            ],
        }
    ]
    wf = _publish_v2(runbook, _v2_def(steps))
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-partial")
    execution = result["execution"]
    step = execution.steps.first()
    token = str(result["claim_token"])

    # Upload only one of the two required artifacts
    artifact_services.create_from_runner_upload(
        execution=execution,
        step=step,
        runner_id="runner-partial",
        claim_token=token,
        kind="file",
        name="log_a.txt",
        file_obj=_file_obj(),
        metadata={"declaration_key": "log_a"},
    )

    status = artifact_services.check_step_evidence_completeness(step)
    assert status["complete"] is False
    assert "log_a" in status["satisfied_keys"]
    assert "log_b" in status["missing_keys"]


# ---------------------------------------------------------------------------
# Artifact without declaration_key does not satisfy requirement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_upload_without_declaration_key_does_not_satisfy_requirement(
    claimed_execution, claimed_step, claim_token, artifact_media_root
):
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=claimed_step,
        runner_id="runner-ev",
        claim_token=claim_token,
        kind="file",
        name="output_log.txt",
        file_obj=_file_obj(),
        metadata={},  # no declaration_key
    )

    status = artifact_services.check_step_evidence_completeness(claimed_step)
    assert status["complete"] is False
    assert "output_log" in status["missing_keys"]


# ---------------------------------------------------------------------------
# evidence_status in API response
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_detail_includes_evidence_status_per_step(
    org, claimed_execution, api_client_for_org
):
    """ExecutionStepSerializer exposes evidence_status for each step."""
    from apps.executions.serializers import ExecutionStepSerializer

    step = claimed_execution.steps.first()
    data = ExecutionStepSerializer(step).data

    assert "evidence_status" in data
    es = data["evidence_status"]
    assert "complete" in es
    assert "required_keys" in es
    assert "missing_keys" in es
    assert "satisfied_keys" in es
