SUMMARIZE_SYSTEM_PROMPT = """\
You are an operations summary assistant. Given a completed (or failed) workflow execution, produce a concise human-readable summary for the operator who ran it.

Rules:
- summary: 1-3 sentences describing what happened and whether the execution succeeded.
- key_outcomes: list of short bullet-point strings (max 5), one per significant outcome or failure.
- Focus on facts present in the step outputs. Do not speculate about causes not evident in the data.
- Return a JSON object with keys: summary, key_outcomes.
"""

SUMMARIZE_USER_PROMPT_TEMPLATE = """\
Workflow: {workflow_title}
Execution status: {status}

Steps:
{steps_text}

Summarize this execution.
"""


def build_summarize_user_prompt(
    workflow_title: str, status: str, steps_text: str
) -> str:
    return SUMMARIZE_USER_PROMPT_TEMPLATE.format(
        workflow_title=workflow_title, status=status, steps_text=steps_text
    )
