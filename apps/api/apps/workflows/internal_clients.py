"""
Workflow-owned boundary for the internal AI service.

Re-exports the types and callable needed by the workflows app from the
central AI client. Keeping this seam in the workflows package means:

  - Tests patch `apps.workflows.internal_clients.parse_runbook_to_workflow_candidate`
    (or the name as it appears in services) rather than reaching into runbooks.
  - A future move of the AI client implementation does not leak into services.py.
"""
from apps.runbooks.ai_client import (  # noqa: F401
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
    WorkflowCandidate,
    WorkflowCandidateStep,
    parse_runbook_to_workflow_candidate,
)

__all__ = [
    "AiServiceBadResponseError",
    "AiServiceContractError",
    "AiServiceTimeoutError",
    "AiServiceUnavailableError",
    "WorkflowCandidate",
    "WorkflowCandidateStep",
    "parse_runbook_to_workflow_candidate",
]
