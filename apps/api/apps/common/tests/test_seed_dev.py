"""
Tests for the seed_dev management command.

Verifies idempotency, smoke workflow correctness, and seeded execution state.
"""

import pytest
from django.core.management import call_command
from django.test import override_settings

pytestmark = pytest.mark.django_db(transaction=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_seed(**options):
    with override_settings(DEBUG=True):
        call_command("seed_dev", **options)


def _get_smoke_workflows():
    from apps.workflows.models import Workflow

    return list(
        Workflow.objects.filter(
            runbook__slug="execution-plane-smoke-tests"
        ).order_by("version")
    )


def _get_smoke_executions():
    from apps.executions.models import Execution

    return list(
        Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests"
        ).order_by("created_at")
    )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestSeedDevIdempotency:
    def test_runs_twice_without_error(self):
        _run_seed()
        _run_seed()

    def test_no_duplicate_users_after_two_runs(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        _run_seed()
        count_after_first = User.objects.filter(email__endswith="@acme.test").count()
        _run_seed()
        count_after_second = User.objects.filter(email__endswith="@acme.test").count()
        assert count_after_first == count_after_second

    def test_no_duplicate_orgs_after_two_runs(self):
        from apps.organizations.models import Organization

        _run_seed()
        count_after_first = Organization.objects.filter(
            slug="acme-platform-eng"
        ).count()
        _run_seed()
        count_after_second = Organization.objects.filter(
            slug="acme-platform-eng"
        ).count()
        assert count_after_first == count_after_second == 1

    def test_no_duplicate_smoke_runbook_after_two_runs(self):
        from apps.runbooks.models import Runbook

        _run_seed()
        count_after_first = Runbook.objects.filter(
            slug="execution-plane-smoke-tests"
        ).count()
        _run_seed()
        count_after_second = Runbook.objects.filter(
            slug="execution-plane-smoke-tests"
        ).count()
        assert count_after_first == count_after_second == 1

    def test_no_duplicate_smoke_workflows_after_two_runs(self):
        _run_seed()
        count_after_first = len(_get_smoke_workflows())
        _run_seed()
        count_after_second = len(_get_smoke_workflows())
        assert count_after_first == count_after_second

    def test_no_duplicate_queued_smoke_executions_after_two_runs(self):
        from apps.executions.models import Execution

        _run_seed()
        queued_after_first = Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ).count()
        _run_seed()
        queued_after_second = Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ).count()
        # Second run must not create more queued executions when first-run ones are still queued.
        assert queued_after_second == queued_after_first


# ---------------------------------------------------------------------------
# Smoke runbook and workflow structure
# ---------------------------------------------------------------------------


class TestSmokeWorkflows:
    def setup_method(self):
        _run_seed()

    def test_six_smoke_workflows_seeded(self):
        workflows = _get_smoke_workflows()
        assert len(workflows) == 6

    def test_all_smoke_workflows_published(self):
        from apps.workflows.models import Workflow

        for wf in _get_smoke_workflows():
            assert wf.status == Workflow.Status.PUBLISHED, (
                f"{wf.name} should be published but is {wf.status}"
            )

    def test_all_smoke_workflows_no_review_required(self):
        for wf in _get_smoke_workflows():
            assert wf.requires_review is False, (
                f"{wf.name} must not require review (create_execution would raise)"
            )

    def test_all_smoke_step_types_are_command(self):
        """All smoke test steps must use 'command' type (supported by sandboxed runner)."""
        for wf in _get_smoke_workflows():
            for step in wf.definition.get("steps", []):
                assert step.get("type") == "command", (
                    f"Workflow {wf.name} step '{step.get('id')}' has type "
                    f"'{step.get('type')}'; expected 'command' for sandbox compatibility"
                )

    def test_all_smoke_steps_have_safe_commands(self):
        """Smoke steps must not use unsafe commands."""
        unsafe_patterns = [
            "kubectl",
            "pagerduty-cli",
            "rm -rf",
            "curl",
            "wget",
            "apt-get",
            "pip install",
            "npm install",
            "docker",
        ]
        for wf in _get_smoke_workflows():
            for step in wf.definition.get("steps", []):
                cmd = step.get("command", "")
                for pattern in unsafe_patterns:
                    assert pattern not in cmd, (
                        f"Workflow {wf.name} step '{step.get('id')}' uses unsafe "
                        f"pattern '{pattern}': {cmd[:80]!r}"
                    )

    def test_timeout_step_has_timeout_seconds(self):
        """The timeout probe step must have timeoutSeconds in its definition."""
        from apps.workflows.models import Workflow

        wf = Workflow.objects.get(
            runbook__slug="execution-plane-smoke-tests",
            name="sandbox-timeout-check",
        )
        timeout_step = next(
            s for s in wf.definition["steps"] if s["id"] == "timeout-probe"
        )
        assert "timeoutSeconds" in timeout_step, (
            "timeout-probe step must have timeoutSeconds in its definition "
            "so the executor can enforce it"
        )
        assert isinstance(timeout_step["timeoutSeconds"], int)
        assert timeout_step["timeoutSeconds"] > 0
        assert timeout_step["timeoutSeconds"] < 30, (
            "timeoutSeconds should be much less than the sleep duration (30s) "
            "to actually trigger the timeout path"
        )

    def test_failure_workflow_has_exit_1_step(self):
        """The failure workflow must include a step that explicitly exits non-zero."""
        from apps.workflows.models import Workflow

        wf = Workflow.objects.get(
            runbook__slug="execution-plane-smoke-tests",
            name="sandbox-failure-diagnostics",
        )
        commands = [s.get("command", "") for s in wf.definition["steps"]]
        assert any("exit 1" in cmd for cmd in commands), (
            "sandbox-failure-diagnostics must have a step with 'exit 1'"
        )

    def test_approval_workflow_has_high_risk_step(self):
        """The approval gate workflow must have a high-risk step."""
        from apps.workflows.models import Workflow

        wf = Workflow.objects.get(
            runbook__slug="execution-plane-smoke-tests",
            name="sandbox-policy-approval-gate",
        )
        risks = [s.get("risk") for s in wf.definition["steps"]]
        assert "high" in risks, (
            "sandbox-policy-approval-gate must have at least one high-risk step"
        )

    def test_all_smoke_step_ids_unique_within_workflow(self):
        for wf in _get_smoke_workflows():
            step_ids = [s["id"] for s in wf.definition.get("steps", [])]
            assert len(step_ids) == len(set(step_ids)), (
                f"Workflow {wf.name} has duplicate step ids: {step_ids}"
            )


# ---------------------------------------------------------------------------
# Seeded executions
# ---------------------------------------------------------------------------


class TestSmokeExecutions:
    def setup_method(self):
        _run_seed()

    def test_six_queued_smoke_executions_created(self):
        from apps.executions.models import Execution

        queued = Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ).count()
        assert queued == 6

    def test_each_smoke_execution_has_steps(self):
        """Executions created via create_execution must have ExecutionStep rows."""
        from apps.executions.models import Execution

        for ex in Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ):
            step_count = ex.steps.count()
            assert step_count > 0, (
                f"Execution {ex.id} for workflow '{ex.workflow.name}' has no steps"
            )

    def test_smoke_execution_steps_match_workflow_definition(self):
        """Step count in each execution must match the workflow definition."""
        from apps.executions.models import Execution

        for ex in Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ):
            expected = len(ex.workflow.definition.get("steps", []))
            actual = ex.steps.count()
            assert actual == expected, (
                f"Execution {ex.id} has {actual} steps but workflow "
                f"'{ex.workflow.name}' defines {expected}"
            )

    def test_smoke_execution_steps_are_pending(self):
        from apps.executions.models import Execution, ExecutionStep

        for ex in Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ):
            non_pending = ex.steps.exclude(status=ExecutionStep.Status.PENDING).count()
            assert non_pending == 0, (
                f"Execution {ex.id}: some steps are not pending (queued execution "
                "should have all steps pending before runner claims it)"
            )

    def test_timeout_execution_has_timeout_in_snapshot(self):
        """The timeout execution's step snapshot must carry timeoutSeconds."""
        from apps.executions.models import Execution

        ex = Execution.objects.filter(
            workflow__name="sandbox-timeout-check",
            status=Execution.Status.QUEUED,
        ).first()
        assert ex is not None, "No queued execution for sandbox-timeout-check"

        timeout_step = ex.steps.filter(step_key="timeout-probe").first()
        assert timeout_step is not None
        assert "timeoutSeconds" in timeout_step.step_snapshot, (
            "timeout-probe step_snapshot must contain timeoutSeconds "
            "so the executor can enforce it at claim time"
        )


# ---------------------------------------------------------------------------
# --execution-smoke flag
# ---------------------------------------------------------------------------


class TestSmokeOnlyFlag:
    def test_execution_smoke_flag_seeds_smoke_only(self):
        """--execution-smoke must seed smoke workflows and executions without error."""
        from apps.executions.models import Execution

        _run_seed()
        _run_seed(execution_smoke=True)

        queued = Execution.objects.filter(
            workflow__runbook__slug="execution-plane-smoke-tests",
            status=Execution.Status.QUEUED,
        ).count()
        assert queued == 6
