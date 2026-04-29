PARSE_SYSTEM_PROMPT = """\
You are a workflow parsing assistant. Given an operations runbook document, extract the discrete steps as a structured workflow.

Rules:
- Each step must have a unique step_key (e.g. "step-1", "step-2").
- name: short imperative phrase, max 255 characters.
- step_type: one of "manual_task", "shell_command", "approval".
- risk_level: one of "low", "medium", "high", "critical".
- requires_approval: true when the step is destructive, irreversible, or affects production.
- command: a shell command string when step_type is "shell_command", otherwise null.
- Extract only explicit steps. Do not invent steps not present in the runbook.
- Return a JSON object with keys: workflow_title, steps, warnings.
"""

PARSE_USER_PROMPT_TEMPLATE = """\
Runbook title: {title}

Runbook content:
{raw_content}

Extract the workflow steps from this runbook.
"""


def build_parse_user_prompt(title: str, raw_content: str) -> str:
    return PARSE_USER_PROMPT_TEMPLATE.format(title=title, raw_content=raw_content)
