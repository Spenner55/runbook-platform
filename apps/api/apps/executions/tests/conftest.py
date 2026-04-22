import pytest
from unittest.mock import patch

from apps.runbooks.ai_client import WorkflowCandidate, WorkflowCandidateStep


def _make_candidate() -> WorkflowCandidate:
    return WorkflowCandidate(
        request_id="test-req-id",
        workflow_title="Test Workflow",
        steps=[
            WorkflowCandidateStep(
                step_key="step-1",
                name="Verify prerequisites",
                step_type="manual",
                risk_level="low",
                requires_approval=False,
            ),
            WorkflowCandidateStep(
                step_key="step-2",
                name="Execute main task",
                step_type="manual",
                risk_level="medium",
                requires_approval=False,
            ),
        ],
    )


@pytest.fixture(autouse=True)
def mock_ai_client():
    with patch(
        "apps.workflows.services.parse_runbook_to_workflow_candidate",
        return_value=_make_candidate(),
    ):
        yield
