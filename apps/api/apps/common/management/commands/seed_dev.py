"""
Management command: seed_dev

Populates the local development database with a canonical dataset for
thorough manual testing. Covers: users, orgs, memberships, runbooks,
workflows, executions (all status variants), steps, approvals, policies,
integrations, and artifacts.

Safe to run multiple times. Aborts if DEBUG is False. Never calls any
AI/LLM endpoints.

Usage:
    python manage.py seed_dev
"""

import hashlib
import os
import uuid
from copy import deepcopy
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed local dev database with comprehensive test data (no AI calls)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execution-smoke",
            action="store_true",
            help=(
                "Seed only the execution smoke test runbook, workflows, and fresh queued "
                "executions. Faster reset when you just need to re-queue smoke runs."
            ),
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev refuses to run when DEBUG=False. "
                "This command is for local development only."
            )

        smoke_only = options.get("execution_smoke", False)

        if smoke_only:
            self._seed_users()
            self._seed_org()
            self._runbooks = {}
            self._workflows = {}
            self._seed_smoke_runbook()
            self._seed_smoke_workflows()
            self._seed_smoke_executions()
            self.stdout.write(self.style.SUCCESS("\nSmoke seed complete."))
            self.stdout.write(
                "\nSmoke test workflows queued and ready.\n"
                "Set RUNNER_EXECUTION_MODE=sandboxed in .env to run real commands.\n"
                "Then: make up-d && make logs-runner\n"
            )
            return

        self._seed_users()
        self._seed_org()
        self._seed_runbooks()
        self._seed_workflows()
        self._seed_executions()
        self._seed_policy()
        self._seed_integration()
        self._seed_smoke_runbook()
        self._seed_smoke_workflows()
        self._seed_smoke_executions()

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
        self.stdout.write(
            "\nLogin credentials:\n"
            "  admin@acme.test    / Admin1234!   (owner)\n"
            "  operator@acme.test / Operator1!   (operator)\n"
            "  viewer@acme.test   / Viewer1234!  (viewer)\n"
            "\nSeeded execution scenarios (representational):\n"
            "  SUCCEEDED          — deploy run with sandbox metadata on all steps\n"
            "  FAILED             — deploy step exit_nonzero + failure_kind\n"
            "  RUNNING/approval   — incident runbook awaiting approval\n"
            "  QUEUED             — deploy run waiting to be claimed\n"
            "  CANCELLED          — deploy run cancelled before it started (queued path)\n"
            "  RUNNING/cancel     — deploy run with cancellation pending (cancel banner)\n"
            "  CANCELLED/mid-run  — deploy run cancelled while running (cancelled step)\n"
            "  FAILED/timed-out   — deploy step exceeded timeout (timed_out banner)\n"
            "\nSeeded smoke test executions (real — requires sandboxed runner):\n"
            "  QUEUED smoke-success    — happy path; all steps succeed\n"
            "  QUEUED smoke-failure    — step 2 exits non-zero; proves failure capture\n"
            "  QUEUED smoke-timeout    — step 2 sleeps 30s with 5s timeout; proves timeout path\n"
            "  QUEUED smoke-artifacts  — generates files; proves workspace/stdout capture\n"
            "  QUEUED smoke-cancel     — 60-tick loop; start then cancel from UI to test cancel\n"
            "  QUEUED smoke-approval   — high-risk step; requires approval via UI before running\n"
            "\nTo run smoke tests:\n"
            "  1. Set RUNNER_EXECUTION_MODE=sandboxed in .env\n"
            "  2. make up-d && make logs-runner\n"
            "  3. Watch the runner pick up and execute each queued smoke execution\n"
            "  See docs/runbooks/manual-execution-plane-testing.md for the full guide.\n"
        )

    # ------------------------------------------------------------------
    # Users & org
    # ------------------------------------------------------------------

    def _seed_users(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        accounts = [
            ("admin@acme.test", "Admin1234!", "Ada", "Admin", True),
            ("operator@acme.test", "Operator1!", "Oscar", "Operator", False),
            ("viewer@acme.test", "Viewer1234!", "Vera", "Viewer", False),
        ]
        for email, password, first, last, is_staff in accounts:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "is_staff": is_staff,
                    "is_active": True,
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
            self._report("User", email, created)

    def _seed_org(self):
        from django.contrib.auth import get_user_model

        from apps.organizations.models import Membership, MembershipRole, Organization

        User = get_user_model()

        org, created = Organization.objects.get_or_create(
            slug="acme-platform-eng",
            defaults={"name": "Acme Platform Engineering"},
        )
        self._report("Organization", org.name, created)
        self._org = org

        role_map = {
            "admin@acme.test": MembershipRole.OWNER,
            "operator@acme.test": MembershipRole.OPERATOR,
            "viewer@acme.test": MembershipRole.VIEWER,
        }
        for email, role in role_map.items():
            user = User.objects.get(email=email)
            m, created = Membership.objects.get_or_create(
                organization=org,
                user=user,
                defaults={"role": role},
            )
            self._report("Membership", f"{email} → {role}", created)

    # ------------------------------------------------------------------
    # Runbooks
    # ------------------------------------------------------------------

    def _seed_runbooks(self):
        from apps.runbooks.models import Runbook

        specs = [
            (
                "deploy-production",
                "Deploy to Production",
                Runbook.Status.READY,
                "Standard procedure for deploying a new release to the production "
                "environment. Includes pre-deploy health checks, the deployment "
                "script, and a post-deploy smoke test.",
            ),
            (
                "database-rollback",
                "Database Rollback",
                Runbook.Status.DRAFT,
                "Emergency procedure for rolling back a database migration. "
                "Use only when a migration causes production data corruption.",
            ),
            (
                "incident-response",
                "Incident Response",
                Runbook.Status.READY,
                "On-call incident response runbook. Covers alerting, triage, "
                "mitigation, and postmortem steps.",
            ),
            (
                "certificate-renewal",
                "TLS Certificate Renewal",
                Runbook.Status.ARCHIVED,
                "Legacy manual certificate renewal steps — superseded by automation.",
            ),
        ]
        self._runbooks = {}
        for slug, title, status, content in specs:
            rb, created = self._org.runbooks.get_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "raw_content": content,
                    "status": status,
                },
            )
            self._runbooks[slug] = rb
            self._report("Runbook", title, created)

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    def _seed_workflows(self):
        from apps.workflows.models import Workflow

        self._workflows = {}

        # --- deploy-production v1 (published) ---
        deploy_def = {
            "name": "Deploy to Production",
            "steps": [
                {
                    "id": "check-health",
                    "name": "Pre-deploy health check",
                    "type": "shell_command",
                    "risk": "low",
                    "command": "curl -sf http://internal/health || exit 1",
                    "requiresApproval": False,
                },
                {
                    "id": "deploy",
                    "name": "Run deployment script",
                    "type": "shell_command",
                    "risk": "high",
                    "command": "./scripts/deploy.sh --env production",
                    "requiresApproval": True,
                },
                {
                    "id": "smoke-test",
                    "name": "Post-deploy smoke test",
                    "type": "shell_command",
                    "risk": "low",
                    "command": "pytest tests/smoke/ -q",
                    "requiresApproval": False,
                },
            ],
        }
        wf, created = Workflow.objects.get_or_create(
            runbook=self._runbooks["deploy-production"],
            version=1,
            defaults={
                "organization": self._org,
                "name": "deploy-production-v1",
                "status": Workflow.Status.PUBLISHED,
                "definition": deploy_def,
                "parse_source": Workflow.ParseSource.MANUAL,
            },
        )
        self._workflows["deploy"] = wf
        self._report("Workflow", wf.name, created)

        # --- incident-response v1 (published) ---
        incident_def = {
            "name": "Incident Response",
            "steps": [
                {
                    "id": "page-oncall",
                    "name": "Page on-call engineer",
                    "type": "shell_command",
                    "risk": "low",
                    "command": "pagerduty-cli trigger --severity critical",
                    "requiresApproval": False,
                },
                {
                    "id": "restart-service",
                    "name": "Restart affected service",
                    "type": "shell_command",
                    "risk": "high",
                    "command": "kubectl rollout restart deployment/api",
                    "requiresApproval": True,
                },
            ],
        }
        wf2, created = Workflow.objects.get_or_create(
            runbook=self._runbooks["incident-response"],
            version=1,
            defaults={
                "organization": self._org,
                "name": "incident-response-v1",
                "status": Workflow.Status.PUBLISHED,
                "definition": incident_def,
                "parse_source": Workflow.ParseSource.MANUAL,
            },
        )
        self._workflows["incident"] = wf2
        self._report("Workflow", wf2.name, created)

        # --- deploy-production v2 (draft — shows versioning in UI) ---
        deploy_def_v2 = dict(deploy_def)
        deploy_def_v2["steps"] = deploy_def["steps"] + [
            {
                "id": "notify-slack",
                "name": "Notify Slack",
                "type": "shell_command",
                "risk": "low",
                "command": "slack-cli post --channel deployments 'Deploy complete'",
                "requiresApproval": False,
            }
        ]
        wf3, created = Workflow.objects.get_or_create(
            runbook=self._runbooks["deploy-production"],
            version=2,
            defaults={
                "organization": self._org,
                "name": "deploy-production-v2",
                "status": Workflow.Status.DRAFT,
                "definition": deploy_def_v2,
                "parse_source": Workflow.ParseSource.MANUAL,
            },
        )
        self._workflows["deploy_v2"] = wf3
        self._report("Workflow", wf3.name, created)

    # ------------------------------------------------------------------
    # Executions (all status variants)
    # ------------------------------------------------------------------

    def _seed_executions(self):
        self._seed_execution_succeeded()
        self._seed_execution_failed()
        self._seed_execution_waiting_approval()
        self._seed_execution_queued()
        self._seed_execution_cancelled()
        self._seed_execution_cancel_pending()
        self._seed_execution_cancelled_mid_run()
        self._seed_execution_timed_out()

    def _seed_execution_succeeded(self):
        from apps.executions.models import Execution

        wf = self._workflows["deploy"]

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-succeeded",
            workflow=wf,
            status=Execution.Status.SUCCEEDED,
            defaults={
                "started_at": timezone.now() - timedelta(hours=2),
                "finished_at": timezone.now() - timedelta(hours=1, minutes=50),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": timezone.now() - timedelta(hours=2),
            },
        )
        self._report("Execution", f"SUCCEEDED [{ex.id}]", created)

        step_data = [
            (
                "check-health",
                "Pre-deploy health check",
                "low",
                False,
                0,
                "succeeded",
                0,
            ),
            ("deploy", "Run deployment script", "high", True, 1, "succeeded", 0),
            (
                "smoke-test",
                "Post-deploy smoke test",
                "low",
                False,
                2,
                "succeeded",
                0,
            ),
        ]
        self._create_steps(
            ex,
            step_data,
            step_overrides={
                0: {
                    "sandbox_provider": "local_process",
                    "sandbox_run_id": "seed-succ-step0",
                },
                1: {
                    "sandbox_provider": "local_process",
                    "sandbox_run_id": "seed-succ-step1",
                },
                2: {
                    "sandbox_provider": "local_process",
                    "sandbox_run_id": "seed-succ-step2",
                },
            },
        )
        self._seed_artifact(ex)

    def _seed_execution_failed(self):
        from apps.executions.models import Execution

        wf = self._workflows["deploy"]

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-failed",
            workflow=wf,
            status=Execution.Status.FAILED,
            defaults={
                "started_at": timezone.now() - timedelta(hours=5),
                "finished_at": timezone.now() - timedelta(hours=4, minutes=55),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": timezone.now() - timedelta(hours=5),
            },
        )
        self._report("Execution", f"FAILED [{ex.id}]", created)

        step_data = [
            (
                "check-health",
                "Pre-deploy health check",
                "low",
                False,
                0,
                "succeeded",
                0,
            ),
            ("deploy", "Run deployment script", "high", True, 1, "failed", 1),
            (
                "smoke-test",
                "Post-deploy smoke test",
                "low",
                False,
                2,
                "skipped",
                None,
            ),
        ]
        self._create_steps(
            ex,
            step_data,
            fail_message="Script exited with code 1: permission denied on /app/deploy",
            step_overrides={
                0: {
                    "sandbox_provider": "local_process",
                    "sandbox_run_id": "seed-fail-step0",
                },
                1: {
                    "sandbox_provider": "local_process",
                    "sandbox_run_id": "seed-fail-step1",
                    "failure_kind": "exit_nonzero",
                },
            },
        )

    def _seed_execution_waiting_approval(self):
        from apps.approvals.models import ApprovalRequest
        from apps.executions.models import Execution, ExecutionStep

        wf = self._workflows["incident"]
        snap = self._seed_workflow_snapshot(wf, "incident-awaiting-approval")

        ex, created = self._get_or_create_seed_execution(
            seed_key="incident-awaiting-approval",
            workflow=wf,
            status=Execution.Status.RUNNING,
            defaults={
                "started_at": timezone.now() - timedelta(minutes=5),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": timezone.now() - timedelta(minutes=5),
            },
        )
        self._report("Execution", f"RUNNING/awaiting-approval [{ex.id}]", created)

        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=0,
            defaults={
                "step_key": "page-oncall",
                "name": "Page on-call engineer",
                "step_type": "shell_command",
                "risk_level": "low",
                "command": "pagerduty-cli trigger --severity critical",
                "requires_approval": False,
                "step_snapshot": snap["steps"][0],
                "status": ExecutionStep.Status.SUCCEEDED,
                "started_at": timezone.now() - timedelta(minutes=4),
                "finished_at": timezone.now() - timedelta(minutes=3),
                "exit_code": 0,
                "error_message": "",
            },
        )
        step2, _ = ExecutionStep.objects.update_or_create(
            execution=ex,
            position=1,
            defaults={
                "step_key": "restart-service",
                "name": "Restart affected service",
                "step_type": "shell_command",
                "risk_level": "high",
                "command": "kubectl rollout restart deployment/api",
                "requires_approval": True,
                "step_snapshot": snap["steps"][1],
                "status": ExecutionStep.Status.WAITING_FOR_APPROVAL,
                "started_at": timezone.now() - timedelta(minutes=3),
                "finished_at": None,
                "exit_code": None,
                "error_message": "",
            },
        )

        # Pending approval request — this is what you'd approve/reject in the UI
        approval, approval_created = ApprovalRequest.objects.update_or_create(
            step=step2,
            defaults={
                "organization": self._org,
                "execution": ex,
                "status": ApprovalRequest.Status.PENDING,
                "requested_by_runner_id": "seed-runner-01",
                "requested_at": timezone.now() - timedelta(minutes=3),
                "timeout_seconds": 3600,
                "expires_at": timezone.now() + timedelta(minutes=57),
                "resolved_at": None,
            },
        )
        self._report(
            "ApprovalRequest",
            f"PENDING for restart-service [{approval.id}]",
            approval_created,
        )

    def _seed_execution_queued(self):
        from apps.executions.models import Execution

        wf = self._workflows["deploy"]

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-queued",
            workflow=wf,
            status=Execution.Status.QUEUED,
            defaults={
                "started_at": None,
                "finished_at": None,
                "claimed_by_runner_id": "",
                "claim_token": None,
                "claimed_at": None,
                "last_heartbeat_at": None,
            },
        )
        self._report("Execution", f"QUEUED [{ex.id}]", created)

    def _seed_execution_cancelled(self):
        from apps.executions.models import Execution

        wf = self._workflows["deploy"]

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-cancelled",
            workflow=wf,
            status=Execution.Status.CANCELLED,
            defaults={
                "started_at": timezone.now() - timedelta(days=1),
                "finished_at": timezone.now()
                - timedelta(days=1)
                + timedelta(minutes=1),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": timezone.now() - timedelta(days=1),
            },
        )
        self._report("Execution", f"CANCELLED [{ex.id}]", created)

    def _seed_execution_cancel_pending(self):
        """RUNNING execution with cancel_requested_at set — tests the cancellation banner."""
        from apps.executions.models import Execution, ExecutionStep

        wf = self._workflows["deploy"]
        now = timezone.now()

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-cancel-pending",
            workflow=wf,
            status=Execution.Status.RUNNING,
            defaults={
                "started_at": now - timedelta(minutes=4),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": now - timedelta(minutes=4),
                "cancel_requested_at": now - timedelta(minutes=1),
                "cancel_requested_by": "operator@acme.test",
                "cancel_reason": "Hotfix deployment required — stopping in-progress run",
            },
        )
        self._report("Execution", f"RUNNING/cancel-pending [{ex.id}]", created)

        snap_steps = wf.definition.get("steps", [])

        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=0,
            defaults={
                "step_key": "check-health",
                "name": "Pre-deploy health check",
                "step_type": "shell_command",
                "risk_level": "low",
                "command": snap_steps[0].get("command", "") if snap_steps else "",
                "requires_approval": False,
                "step_snapshot": snap_steps[0] if snap_steps else {},
                "status": ExecutionStep.Status.SUCCEEDED,
                "started_at": ex.started_at,
                "finished_at": ex.started_at + timedelta(seconds=12),
                "exit_code": 0,
                "error_message": "",
                "sandbox_provider": "local_process",
                "sandbox_run_id": "seed-cp-step0",
            },
        )
        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=1,
            defaults={
                "step_key": "deploy",
                "name": "Run deployment script",
                "step_type": "shell_command",
                "risk_level": "high",
                "command": snap_steps[1].get("command", "")
                if len(snap_steps) > 1
                else "",
                "requires_approval": True,
                "step_snapshot": snap_steps[1] if len(snap_steps) > 1 else {},
                "status": ExecutionStep.Status.RUNNING,
                "started_at": ex.started_at + timedelta(seconds=15),
                "finished_at": None,
                "exit_code": None,
                "error_message": "",
                "sandbox_provider": "local_process",
                "sandbox_run_id": "seed-cp-step1",
            },
        )

    def _seed_execution_cancelled_mid_run(self):
        """CANCELLED execution that was running when cancelled — tests cancelled step banner."""
        from apps.executions.models import Execution, ExecutionStep

        wf = self._workflows["deploy"]
        started = timezone.now() - timedelta(hours=3)

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-cancelled-mid-run",
            workflow=wf,
            status=Execution.Status.CANCELLED,
            defaults={
                "started_at": started,
                "finished_at": started + timedelta(minutes=2),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": started,
                "cancel_requested_at": started + timedelta(minutes=1),
                "cancel_requested_by": "admin@acme.test",
                "cancel_reason": "Emergency maintenance window",
            },
        )
        self._report("Execution", f"CANCELLED/mid-run [{ex.id}]", created)

        snap_steps = wf.definition.get("steps", [])

        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=0,
            defaults={
                "step_key": "check-health",
                "name": "Pre-deploy health check",
                "step_type": "shell_command",
                "risk_level": "low",
                "command": snap_steps[0].get("command", "") if snap_steps else "",
                "requires_approval": False,
                "step_snapshot": snap_steps[0] if snap_steps else {},
                "status": ExecutionStep.Status.SUCCEEDED,
                "started_at": started,
                "finished_at": started + timedelta(seconds=10),
                "exit_code": 0,
                "error_message": "",
                "sandbox_provider": "local_process",
                "sandbox_run_id": "seed-cmr-step0",
            },
        )
        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=1,
            defaults={
                "step_key": "deploy",
                "name": "Run deployment script",
                "step_type": "shell_command",
                "risk_level": "high",
                "command": snap_steps[1].get("command", "")
                if len(snap_steps) > 1
                else "",
                "requires_approval": True,
                "step_snapshot": snap_steps[1] if len(snap_steps) > 1 else {},
                "status": ExecutionStep.Status.CANCELLED,
                "started_at": started + timedelta(seconds=15),
                "finished_at": started + timedelta(minutes=1),
                "exit_code": None,
                "error_message": "",
                "cancelled": True,
                "failure_kind": "cancelled",
                "sandbox_provider": "local_process",
                "sandbox_run_id": "seed-cmr-step1",
            },
        )
        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=2,
            defaults={
                "step_key": "smoke-test",
                "name": "Post-deploy smoke test",
                "step_type": "shell_command",
                "risk_level": "low",
                "command": snap_steps[2].get("command", "")
                if len(snap_steps) > 2
                else "",
                "requires_approval": False,
                "step_snapshot": snap_steps[2] if len(snap_steps) > 2 else {},
                "status": ExecutionStep.Status.SKIPPED,
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "error_message": "",
            },
        )

    def _seed_execution_timed_out(self):
        """FAILED execution where a step exceeded its timeout — tests the timed-out banner."""
        from apps.executions.models import Execution, ExecutionStep

        wf = self._workflows["deploy"]
        started = timezone.now() - timedelta(hours=6)

        ex, created = self._get_or_create_seed_execution(
            seed_key="deploy-timed-out",
            workflow=wf,
            status=Execution.Status.FAILED,
            defaults={
                "started_at": started,
                "finished_at": started + timedelta(minutes=7),
                "claimed_by_runner_id": "seed-runner-01",
                "claim_token": uuid.uuid4(),
                "claimed_at": started,
            },
        )
        self._report("Execution", f"FAILED/timed-out [{ex.id}]", created)

        snap_steps = wf.definition.get("steps", [])

        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=0,
            defaults={
                "step_key": "check-health",
                "name": "Pre-deploy health check",
                "step_type": "shell_command",
                "risk_level": "low",
                "command": snap_steps[0].get("command", "") if snap_steps else "",
                "requires_approval": False,
                "step_snapshot": snap_steps[0] if snap_steps else {},
                "status": ExecutionStep.Status.SUCCEEDED,
                "started_at": started,
                "finished_at": started + timedelta(seconds=8),
                "exit_code": 0,
                "error_message": "",
                "sandbox_provider": "local_process",
                "sandbox_run_id": "seed-to-step0",
            },
        )
        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=1,
            defaults={
                "step_key": "deploy",
                "name": "Run deployment script",
                "step_type": "shell_command",
                "risk_level": "high",
                "command": snap_steps[1].get("command", "")
                if len(snap_steps) > 1
                else "",
                "requires_approval": True,
                "step_snapshot": snap_steps[1] if len(snap_steps) > 1 else {},
                "status": ExecutionStep.Status.FAILED,
                "started_at": started + timedelta(seconds=12),
                "finished_at": started + timedelta(minutes=5),
                "exit_code": None,
                "error_message": "Step exceeded maximum allowed execution time (300 seconds)",
                "timed_out": True,
                "failure_kind": "timeout",
                "sandbox_provider": "local_process",
                "sandbox_run_id": "seed-to-step1",
            },
        )
        ExecutionStep.objects.update_or_create(
            execution=ex,
            position=2,
            defaults={
                "step_key": "smoke-test",
                "name": "Post-deploy smoke test",
                "step_type": "shell_command",
                "risk_level": "low",
                "command": snap_steps[2].get("command", "")
                if len(snap_steps) > 2
                else "",
                "requires_approval": False,
                "step_snapshot": snap_steps[2] if len(snap_steps) > 2 else {},
                "status": ExecutionStep.Status.SKIPPED,
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "error_message": "",
            },
        )

    def _seed_workflow_snapshot(self, workflow, seed_key):
        snapshot = deepcopy(workflow.definition)
        snapshot["seed_dev_key"] = seed_key
        return snapshot

    def _get_or_create_seed_execution(
        self, *, seed_key, workflow, status, defaults=None
    ):
        from apps.executions.models import Execution

        defaults = defaults or {}
        snapshot = self._seed_workflow_snapshot(workflow, seed_key)
        base_lookup = {
            "organization": self._org,
            "workflow": workflow,
            "workflow_version": workflow.version,
        }
        execution = (
            Execution.objects.filter(
                **base_lookup,
                workflow_snapshot__seed_dev_key=seed_key,
            )
            .order_by("created_at", "id")
            .first()
        )
        if execution is None:
            candidates = Execution.objects.filter(
                **base_lookup,
                status=status,
            ).order_by("created_at", "id")
            for candidate in candidates:
                candidate_seed_key = (candidate.workflow_snapshot or {}).get(
                    "seed_dev_key"
                )
                if candidate_seed_key in (None, seed_key):
                    execution = candidate
                    break

        if execution is None:
            return (
                Execution.objects.create(
                    **base_lookup,
                    status=status,
                    workflow_snapshot=snapshot,
                    **defaults,
                ),
                True,
            )

        update_fields = []
        if execution.status != status:
            execution.status = status
            update_fields.append("status")
        if execution.workflow_snapshot != snapshot:
            execution.workflow_snapshot = snapshot
            update_fields.append("workflow_snapshot")
        for field, value in defaults.items():
            if getattr(execution, field) != value:
                setattr(execution, field, value)
                update_fields.append(field)
        if update_fields:
            execution.save(update_fields=[*update_fields, "updated_at"])
        return execution, False

    def _create_steps(self, execution, step_data, fail_message="", step_overrides=None):
        from apps.executions.models import ExecutionStep

        snap_steps = execution.workflow_snapshot.get("steps", [])

        for (
            step_key,
            name,
            risk,
            requires_approval,
            pos,
            status,
            exit_code,
        ) in step_data:
            snap = next((s for s in snap_steps if s["id"] == step_key), {})
            finished = None
            started = None
            err = ""

            if status in ("succeeded", "failed", "skipped"):
                started = execution.started_at + timedelta(minutes=pos * 2)
                finished = started + timedelta(minutes=1)
                if status == "failed":
                    err = fail_message

            extra = (step_overrides or {}).get(pos, {})
            ExecutionStep.objects.update_or_create(
                execution=execution,
                position=pos,
                defaults={
                    "step_key": step_key,
                    "name": name,
                    "step_type": "shell_command",
                    "risk_level": risk,
                    "command": snap.get("command", ""),
                    "requires_approval": requires_approval,
                    "step_snapshot": snap,
                    "status": status,
                    "started_at": started,
                    "finished_at": finished,
                    "exit_code": exit_code,
                    "error_message": err,
                    **extra,
                },
            )

    # ------------------------------------------------------------------
    # Artifacts (local file + DB record)
    # ------------------------------------------------------------------

    def _seed_artifact(self, execution):
        from apps.artifacts.models import Artifact

        content = b"=== Smoke test output ===\n3 passed in 0.42s\n"
        sha256 = hashlib.sha256(content).hexdigest()
        safe_name = "smoke_test.log"
        media_root = getattr(settings, "ARTIFACT_MEDIA_ROOT", "/app/media/artifacts")

        existing = (
            Artifact.objects.filter(execution=execution, name=safe_name)
            .order_by("created_at", "id")
            .first()
        )
        if existing:
            full_path = os.path.join(media_root, existing.storage_key)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(content)
            self._report("Artifact", safe_name, False)
            return

        artifact_id = uuid.uuid4()
        storage_key = (
            f"artifacts/org/{execution.organization_id}"
            f"/execution/{execution.id}"
            f"/step/execution"
            f"/artifact/{artifact_id}"
            f"/{safe_name}"
        )

        # Write the file to local storage
        full_path = os.path.join(media_root, storage_key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)

        Artifact.objects.create(
            id=artifact_id,
            execution=execution,
            name=safe_name,
            organization=self._org,
            step=None,
            kind=Artifact.Kind.STDOUT,
            original_name="smoke_test.log",
            mime_type="text/plain; charset=utf-8",
            size_bytes=len(content),
            checksum_sha256=sha256,
            storage_key=storage_key,
            uploaded_by_runner_id="seed-runner-01",
            upload_status=Artifact.UploadStatus.AVAILABLE,
            uploaded_at=execution.finished_at or timezone.now(),
            content_disposition=Artifact.ContentDisposition.INLINE,
            metadata={"step": "smoke-test"},
        )
        self._report("Artifact", safe_name, True)

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def _seed_policy(self):
        from apps.policies.models import Policy, PolicyRule

        policy, created = Policy.objects.get_or_create(
            organization=self._org,
            name="High-risk steps require approval",
            defaults={
                "description": "Any step with risk level 'high' must be approved before execution.",
                "is_active": True,
                "created_by_label": "seed_dev",
                "updated_by_label": "seed_dev",
            },
        )
        self._report("Policy", policy.name, created)

        rule, r_created = PolicyRule.objects.update_or_create(
            policy=policy,
            name="High risk → approval required",
            defaults={
                "description": "Block high-risk steps unless a human approves.",
                "is_active": True,
                "priority": 10,
                "condition_type": PolicyRule.ConditionType.RISK_LEVEL,
                "condition_params": {"operator": "in", "values": ["high"]},
                "outcome": PolicyRule.Outcome.APPROVAL_REQUIRED,
                "reason": "High-risk steps require human sign-off before execution.",
            },
        )
        self._report("PolicyRule", rule.name, r_created)

        rule2, r2_created = PolicyRule.objects.update_or_create(
            policy=policy,
            name="Low/medium risk → auto approve",
            defaults={
                "description": "Low and medium risk steps run without approval.",
                "is_active": True,
                "priority": 20,
                "condition_type": PolicyRule.ConditionType.RISK_LEVEL,
                "condition_params": {"operator": "in", "values": ["low", "medium"]},
                "outcome": PolicyRule.Outcome.AUTO_APPROVE,
                "reason": "Low/medium risk steps are pre-approved by policy.",
            },
        )
        self._report("PolicyRule", rule2.name, r2_created)

    # ------------------------------------------------------------------
    # Integration
    # ------------------------------------------------------------------

    def _seed_integration(self):
        from apps.integrations.models import IntegrationConnection

        existing = IntegrationConnection.objects.filter(
            organization=self._org,
            name="Seed Generic Webhook",
        ).first()
        if existing:
            self._report("IntegrationConnection", existing.name, False)
            return

        conn = IntegrationConnection(
            organization=self._org,
            type=IntegrationConnection.Type.GENERIC_WEBHOOK,
            name="Seed Generic Webhook",
            config={"url": "https://webhook.example.invalid/hook"},
            event_types=[
                "execution.started",
                "execution.finished",
                "artifact.uploaded",
            ],
            is_active=True,
        )
        try:
            conn.set_credentials({"url": "https://webhook.example.invalid/hook"})
            conn.save()
            self._report("IntegrationConnection", conn.name, True)
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(
                    f"  [Skipped] IntegrationConnection: {exc} "
                    "(check INTEGRATION_FERNET_KEY in .env)"
                )
            )

    # ------------------------------------------------------------------
    # Execution smoke test runbook, workflows, and queued executions
    # ------------------------------------------------------------------

    def _seed_smoke_runbook(self):
        from apps.runbooks.models import Runbook

        rb, created = self._org.runbooks.get_or_create(
            slug="execution-plane-smoke-tests",
            defaults={
                "title": "Execution Plane Smoke Tests",
                "raw_content": (
                    "A set of workflows that exercise the real execution plane end-to-end. "
                    "Each workflow tests a specific scenario (success, failure, timeout, "
                    "artifact generation, cancellation, approval gate) using safe local "
                    "shell commands. Requires RUNNER_EXECUTION_MODE=sandboxed."
                ),
                "status": Runbook.Status.READY,
            },
        )
        self._runbooks["smoke"] = rb
        self._report("Runbook", rb.title, created)

    def _seed_smoke_workflows(self):
        from apps.workflows.models import Workflow

        rb = self._runbooks["smoke"]

        # ── Workflow 1: success ───────────────────────────────────────
        success_def = {
            "name": "Sandbox Success Release Check",
            "steps": [
                {
                    "id": "print-context",
                    "name": "Print release context",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== Release Preflight ==="\n'
                        "date\n"
                        'echo "pwd=$(pwd)"\n'
                        'echo "user=$(id -un 2>/dev/null || echo unknown)"'
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "write-metadata",
                    "name": "Write and verify release metadata",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        "mkdir -p output\n"
                        'printf \'{"service":"api","env":"local","status":"ok"}\\n\''
                        " > output/release-metadata.json\n"
                        'echo "Written: output/release-metadata.json"\n'
                        "cat output/release-metadata.json\n"
                        "test -s output/release-metadata.json"
                        ' && echo "PASS: metadata file exists and is non-empty"'
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "system-checks",
                    "name": "Run quick system checks",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== System Checks ==="\n'
                        "mkdir -p tmp\n"
                        'echo "check=fs_writable result=ok"\n'
                        'echo "check=date result=$(date +%s)"\n'
                        'echo "check=echo result=ok"\n'
                        'echo "checks=3 passed=3 failed=0"'
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "success-banner",
                    "name": "Print success banner",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'printf "\\n=== RELEASE PREFLIGHT PASSED at %s ===\\n" "$(date -u)"'
                    ),
                    "requiresApproval": False,
                },
            ],
        }
        wf, created = Workflow.objects.get_or_create(
            runbook=rb,
            version=1,
            defaults={
                "organization": self._org,
                "name": "sandbox-success-release-check",
                "status": Workflow.Status.PUBLISHED,
                "definition": success_def,
                "parse_source": Workflow.ParseSource.MANUAL,
                "requires_review": False,
            },
        )
        self._workflows["smoke-success"] = wf
        self._report("Workflow", wf.name, created)

        # ── Workflow 2: failure diagnostics ──────────────────────────
        failure_def = {
            "name": "Sandbox Failure Diagnostics",
            "steps": [
                {
                    "id": "prep-step",
                    "name": "Preparation (succeeds)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== Pre-validation setup ==="\n'
                        'echo "Step 1: Checking prerequisites..."\n'
                        'echo "result=ok"'
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "failing-validation",
                    "name": "Validate required config (fails intentionally)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== Validation ==="\n'
                        'echo "Checking required configuration..."\n'
                        'echo "ERROR: required env var LOCAL_FAKE_SECRET is not set" >&2\n'
                        'echo "Hint: set LOCAL_FAKE_SECRET=<value> in your environment" >&2\n'
                        "exit 1"
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "post-failure-step",
                    "name": "Post-failure cleanup (should not run)",
                    "type": "command",
                    "risk": "low",
                    "command": 'echo "ERROR: this step should never execute after step 2 fails" >&2\nexit 1',
                    "requiresApproval": False,
                },
            ],
        }
        wf2, created = Workflow.objects.get_or_create(
            runbook=rb,
            version=2,
            defaults={
                "organization": self._org,
                "name": "sandbox-failure-diagnostics",
                "status": Workflow.Status.PUBLISHED,
                "definition": failure_def,
                "parse_source": Workflow.ParseSource.MANUAL,
                "requires_review": False,
            },
        )
        self._workflows["smoke-failure"] = wf2
        self._report("Workflow", wf2.name, created)

        # ── Workflow 3: timeout check ─────────────────────────────────
        # timeoutSeconds: 5 is in the step definition; executor clamps it to
        # min(5, RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS). The step will time
        # out while sleeping, proving the real sandbox timeout path.
        timeout_def = {
            "name": "Sandbox Timeout Check",
            "steps": [
                {
                    "id": "quick-step",
                    "name": "Quick pre-check (succeeds)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "Timeout probe: quick step started"\n'
                        "date\n"
                        'echo "quick step: ok"'
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "timeout-probe",
                    "name": "Timeout probe step (sleep 30 with 5s limit)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "Timeout probe: long step started at $(date)"\n'
                        'echo "Sleeping 30s (will be killed by 5s timeout)"\n'
                        "sleep 30\n"
                        'echo "ERROR: this line should never appear" >&2'
                    ),
                    "requiresApproval": False,
                    "timeoutSeconds": 5,
                },
            ],
        }
        wf3, created = Workflow.objects.get_or_create(
            runbook=rb,
            version=3,
            defaults={
                "organization": self._org,
                "name": "sandbox-timeout-check",
                "status": Workflow.Status.PUBLISHED,
                "definition": timeout_def,
                "parse_source": Workflow.ParseSource.MANUAL,
                "requires_review": False,
            },
        )
        self._workflows["smoke-timeout"] = wf3
        self._report("Workflow", wf3.name, created)

        # ── Workflow 4: generated artifacts ──────────────────────────
        artifacts_def = {
            "name": "Sandbox Generated Artifacts",
            "steps": [
                {
                    "id": "generate-files",
                    "name": "Generate and verify output files",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== Generating output files ==="\n'
                        "mkdir -p output\n"
                        'echo "health=ok" > output/health-report.txt\n'
                        "printf "
                        '\'{"checks":[{"name":"db","status":"ok"},{"name":"cache","status":"ok"}]}\''
                        " > output/checks.json\n"
                        'printf "# Smoke Summary\\n\\nAll local checks passed.\\n"'
                        " > output/summary.md\n"
                        'echo "=== Generated files:"\n'
                        "find output -type f -maxdepth 1 -print\n"
                        'echo "=== File sizes:"\n'
                        "wc -c output/health-report.txt output/checks.json output/summary.md\n"
                        'echo "=== Verification:"\n'
                        'test -s output/checks.json && echo "PASS: checks.json"\n'
                        'test -s output/health-report.txt && echo "PASS: health-report.txt"\n'
                        'test -s output/summary.md && echo "PASS: summary.md"\n'
                        'echo "All files generated and verified."'
                    ),
                    "requiresApproval": False,
                },
            ],
        }
        wf4, created = Workflow.objects.get_or_create(
            runbook=rb,
            version=4,
            defaults={
                "organization": self._org,
                "name": "sandbox-generated-artifacts",
                "status": Workflow.Status.PUBLISHED,
                "definition": artifacts_def,
                "parse_source": Workflow.ParseSource.MANUAL,
                "requires_review": False,
            },
        )
        self._workflows["smoke-artifacts"] = wf4
        self._report("Workflow", wf4.name, created)

        # ── Workflow 5: cancellation long-running ─────────────────────
        # Start this execution, then cancel it from the UI to verify cancel
        # path. The loop prints a tick every second for up to 60 ticks.
        cancel_def = {
            "name": "Sandbox Cancellation Long Running",
            "steps": [
                {
                    "id": "long-running-loop",
                    "name": "60-tick countdown (cancel me from the UI)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "Long-running operation started at $(date)"\n'
                        "i=1\n"
                        'while [ "$i" -le 60 ]; do\n'
                        '  echo "tick=$i elapsed=${i}s"\n'
                        "  sleep 1\n"
                        "  i=$((i+1))\n"
                        "done\n"
                        'echo "Long-running operation completed (was not cancelled)"'
                    ),
                    "requiresApproval": False,
                },
            ],
        }
        wf5, created = Workflow.objects.get_or_create(
            runbook=rb,
            version=5,
            defaults={
                "organization": self._org,
                "name": "sandbox-cancellation-long-running",
                "status": Workflow.Status.PUBLISHED,
                "definition": cancel_def,
                "parse_source": Workflow.ParseSource.MANUAL,
                "requires_review": False,
            },
        )
        self._workflows["smoke-cancel"] = wf5
        self._report("Workflow", wf5.name, created)

        # ── Workflow 6: policy / approval gate ───────────────────────
        # The seeded policy requires approval for high-risk steps. This
        # workflow will pause at the high-risk step waiting for a human
        # to approve via the UI or API before the runner proceeds.
        approval_def = {
            "name": "Sandbox Policy Approval Gate",
            "steps": [
                {
                    "id": "pre-deploy-check",
                    "name": "Pre-deploy check (low risk, auto-approved)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== Pre-deploy check ==="\n'
                        "date\n"
                        'echo "Pre-deploy checks passed."'
                    ),
                    "requiresApproval": False,
                },
                {
                    "id": "high-risk-deploy",
                    "name": "Simulated production deploy (high risk — needs approval)",
                    "type": "command",
                    "risk": "high",
                    "command": (
                        'echo "=== Simulated Deploy (Approved) ==="\n'
                        "date\n"
                        'echo "deploy=simulated env=local status=ok"\n'
                        'echo "Deploy simulation complete."'
                    ),
                    "requiresApproval": True,
                },
                {
                    "id": "post-deploy-verify",
                    "name": "Post-deploy verification (low risk)",
                    "type": "command",
                    "risk": "low",
                    "command": (
                        'echo "=== Post-deploy verification ==="\necho "result=ok"'
                    ),
                    "requiresApproval": False,
                },
            ],
        }
        wf6, created = Workflow.objects.get_or_create(
            runbook=rb,
            version=6,
            defaults={
                "organization": self._org,
                "name": "sandbox-policy-approval-gate",
                "status": Workflow.Status.PUBLISHED,
                "definition": approval_def,
                "parse_source": Workflow.ParseSource.MANUAL,
                "requires_review": False,
            },
        )
        self._workflows["smoke-approval"] = wf6
        self._report("Workflow", wf6.name, created)

    def _seed_smoke_executions(self):
        from apps.executions.models import Execution
        from apps.executions.services import create_execution

        smoke_keys = [
            "smoke-success",
            "smoke-failure",
            "smoke-timeout",
            "smoke-artifacts",
            "smoke-cancel",
            "smoke-approval",
        ]
        for key in smoke_keys:
            wf = self._workflows.get(key)
            if wf is None:
                continue

            # Reuse existing non-terminal execution (avoids pile-up if runner is stopped).
            existing = (
                Execution.objects.filter(
                    workflow=wf,
                    status__in=[
                        Execution.Status.QUEUED,
                        Execution.Status.CLAIMED,
                        Execution.Status.RUNNING,
                    ],
                )
                .order_by("created_at")
                .first()
            )
            if existing is not None:
                self._report("Execution", f"QUEUED/{key} [{existing.id}]", False)
                continue

            try:
                ex = create_execution(workflow=wf)
                self._report("Execution", f"QUEUED/{key} [{ex.id}]", True)
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"  [Skipped] Execution {key}: {exc}")
                )

    # ------------------------------------------------------------------

    def _report(self, model, name, created):
        verb = "Created" if created else "Already exists"
        self.stdout.write(f"  [{verb}] {model}: {name}")
