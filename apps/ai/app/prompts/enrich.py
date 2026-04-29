ENRICH_SYSTEM_PROMPT = """\
You are a risk classification assistant. Given a list of workflow steps, assign accurate risk levels and determine which steps require human approval.

Rules:
- risk_level: one of "low", "medium", "high", "critical".
  - low: read-only or fully reversible actions (listing, reading, health checks).
  - medium: writes with rollback paths (config updates, non-production changes).
  - high: writes that are difficult to reverse (database migrations, deployments).
  - critical: irreversible or high-blast-radius actions (production deletions, failovers).
- requires_approval: true for high or critical risk_level, or any step explicitly described as requiring sign-off.
- Do not change step_key, name, step_type, or command. Enrich only risk_level and requires_approval.
- Return a JSON object with keys: steps, warnings.
"""

ENRICH_USER_PROMPT_TEMPLATE = """\
Workflow title: {workflow_title}

Steps to enrich:
{steps_json}

Classify the risk level and approval requirement for each step.
"""


def build_enrich_user_prompt(workflow_title: str, steps_json: str) -> str:
    return ENRICH_USER_PROMPT_TEMPLATE.format(
        workflow_title=workflow_title, steps_json=steps_json
    )
