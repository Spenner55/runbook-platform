"""
Management command: seed_dev

Populates the local development database with a canonical dataset for
thorough manual testing. Covers: users, orgs, memberships, runbooks,
workflows, executions (all status variants), steps, approvals, policies,
integrations, runner pool, runner registration token, and artifacts.

Always wipes the previous seed data before re-seeding. Aborts if
DEBUG is False. Never calls any AI/LLM endpoints.

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
    help = "Wipe and re-seed local dev database with comprehensive test data (no AI calls)."

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

        self.stdout.write(self.style.WARNING("\nWiping existing seed data..."))
        self._wipe()

        if smoke_only:
            self._seed_users()
            self._seed_org()
            self._seed_runner_pool()
            self._runbooks = {}
            self._workflows = {}
            self._seed_smoke_runbook()
            self._seed_smoke_workflows()
            self._seed_smoke_executions()
            self.stdout.write(self.style.SUCCESS("\nSmoke seed complete."))
            self._print_runner_instructions()
            self.stdout.write(
                "\nSmoke test workflows queued and ready.\n"
                "Set RUNNER_EXECUTION_MODE=sandboxed in .env to run real commands.\n"
            )
            return

        self._seed_users()
        self._seed_org()
        self._seed_runner_pool()
        self._seed_runbooks()
        self._seed_workflows()
        self._seed_executions()
        self._seed_policy()
        self._seed_integration()
        self._seed_smoke_runbook()
        self._seed_smoke_workflows()
        self._seed_smoke_executions()
        self._seed_operation_profiles()
        self._seed_target_connectivity_routes()
        self._seed_freeze_rules()
        self._seed_change_records()
        self._seed_auditor_workspace()

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
        self.stdout.write(
            "\nLogin credentials:\n"
            "  admin@acme.test    / Admin1234!   (owner)\n"
            "  operator@acme.test / Operator1!   (operator)\n"
            "  viewer@acme.test   / Viewer1234!  (viewer)\n"
            "\nSeeded execution scenarios (representational):\n"
            "  SUCCEEDED          — deploy run with sandbox metadata on all steps\n"
            "  FAILED             — deploy step action_failed failure_kind\n"
            "  RUNNING/approval   — incident runbook awaiting approval\n"
            "  QUEUED             — deploy run waiting to be claimed\n"
            "  CANCELLED          — deploy run cancelled before it started (queued path)\n"
            "  RUNNING/cancel     — deploy run with cancellation pending (cancel banner)\n"
            "  CANCELLED/mid-run  — deploy run cancelled while running (cancelled step)\n"
            "  FAILED/timed-out   — deploy step exceeded timeout (timed_out banner)\n"
            "\nSeeded change/evidence/auditor scenarios:\n"
            "  Operation profiles: prod-deploy, db-migration, rollback, emergency-remediation\n"
            "  Target connectivity routes: service/*, database/db-*, legacy-service/* (inactive)\n"
            "  Freeze rules: past-expired, upcoming-maintenance, current-exception-required\n"
            "  Change records: draft, pending_approval, approved, running, verification_pending,\n"
            "                  verified, closed×2, rejected, canceled, emergency+breakglass\n"
            "  Evidence bundles: compiling (verified change), sealed + export + legal hold (closed)\n"
            "  Auditor workspace: service catalog, control mapping, external refs, access grants\n"
            "  Retro reviews: pending, overdue, submitted\n"
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
        self._print_runner_instructions()

    # ------------------------------------------------------------------
    # Wipe
    # ------------------------------------------------------------------

    def _wipe(self):
        """Delete all seed data in PROTECT-safe order so re-seed starts clean."""
        from django.contrib.auth import get_user_model

        from apps.executions.models import Execution
        from apps.organizations.models import Membership, Organization
        from apps.runners.models import ExecutionLease, Runner, RunnerPool, RunnerRegistrationToken

        User = get_user_model()
        seed_emails = {"admin@acme.test", "operator@acme.test", "viewer@acme.test"}

        # Delete any existing registration token record for the configured token
        # (it may live under a different org from a previous setup) so we can
        # re-create it pointing at the fresh seed pool without a hash conflict.
        reg_token = getattr(settings, "RUNNER_REGISTRATION_TOKEN", "")
        if reg_token:
            token_hash = hashlib.sha256(reg_token.encode()).hexdigest()
            RunnerRegistrationToken.objects.filter(token_hash=token_hash).delete()

        try:
            org = Organization.objects.get(slug="acme-platform-eng")
        except Organization.DoesNotExist:
            User.objects.filter(email__in=seed_emails).delete()
            self.stdout.write("  No existing seed org found — starting fresh.\n")
            return

        # 0a. Evidence domain — must precede ChangeRecord (PROTECT references)
        from apps.evidence.models import EvidenceBundle, EvidenceExport
        from apps.auditor.models import (
            AuditorAccessGrant,
            ChangeControlCoverage,
            ControlMappingProfile,
            ExternalChangeReference,
            ServiceCatalogEntry,
        )
        from apps.changes.models import (
            BreakglassSession,
            ChangeClosure,
            ChangeException,
            ChangeExecutionBinding,
            ChangeRecord,
            DispatchEligibilityCheck,
            FreezeRule,
            OperationProfile,
            RetroReview,
            TargetLock,
            VerificationPlan,
            VerificationResult,
        )
        from apps.runners.models import TargetConnectivityRoute

        from django.db.models import ProtectedError  # noqa

        # Legal holds → EvidenceExport → ControlCoverage → EvidenceBundle (items cascade)
        try:
            from apps.evidence.models import LegalHold
            LegalHold.objects.filter(organization=org).delete()
        except Exception:
            pass
        EvidenceExport.objects.filter(organization=org).delete()
        ChangeControlCoverage.objects.filter(organization=org).delete()
        EvidenceBundle.objects.filter(organization=org).delete()

        # Auditor workspace
        ExternalChangeReference.objects.filter(organization=org).delete()
        AuditorAccessGrant.objects.filter(organization=org).delete()
        ServiceCatalogEntry.objects.filter(organization=org).delete()
        ControlMappingProfile.objects.filter(organization=org).delete()

        # Change exceptions / sessions / retro reviews
        RetroReview.objects.filter(organization=org).delete()
        BreakglassSession.objects.filter(organization=org).delete()
        ChangeException.objects.filter(organization=org).delete()

        # Preflight / locks — TargetLock PROTECT references Execution so must go here
        DispatchEligibilityCheck.objects.filter(organization=org).delete()
        TargetLock.objects.filter(organization=org).delete()

        # Verification results before plan (PROTECT on plan/check/change)
        VerificationResult.objects.filter(organization=org).delete()

        # Closure and bindings — ChangeExecutionBinding PROTECT references Execution!
        ChangeClosure.objects.filter(organization=org).delete()
        ChangeExecutionBinding.objects.filter(organization=org).delete()

        # Verification plan (cascade deletes VerificationCheck)
        VerificationPlan.objects.filter(organization=org).delete()

        # Change records (cascade: ChangeTarget, ChangeWindow)
        ChangeRecord.objects.filter(organization=org).delete()

        # Freeze rules and connectivity routes
        FreezeRule.objects.filter(organization=org).delete()
        TargetConnectivityRoute.objects.filter(organization=org).delete()

        # Operation profiles — clear M2M allowed_workflows first
        for p in OperationProfile.objects.filter(organization=org):
            p.allowed_workflows.clear()
        OperationProfile.objects.filter(organization=org).delete()

        # 1. ExecutionLease — blocks Execution, Runner, RunnerPool, Organization
        ExecutionLease.objects.filter(organization=org).delete()

        # 2. Artifact — PROTECT on organization and execution
        from apps.artifacts.models import Artifact
        Artifact.objects.filter(organization=org).delete()

        # 3. Execution — cascade-deletes ExecutionStep and ApprovalRequest
        Execution.objects.filter(organization=org).delete()

        # 4. Workflow — PROTECT on organization and runbook
        from apps.workflows.models import Workflow
        Workflow.objects.filter(organization=org).delete()

        # 5. Runbook — PROTECT on organization
        from apps.runbooks.models import Runbook
        Runbook.objects.filter(organization=org).delete()

        # 6. Runner — PROTECT on organization and pool
        Runner.objects.filter(organization=org).delete()

        # 7. RunnerRegistrationToken — PROTECT on pool (and deleted above by hash if needed)
        RunnerRegistrationToken.objects.filter(organization=org).delete()

        # 8. RunnerPool — PROTECT on organization
        RunnerPool.objects.filter(organization=org).delete()

        # 9. Policy / PolicyRule — PolicyRule cascades from Policy
        from apps.policies.models import Policy
        Policy.objects.filter(organization=org).delete()

        # 10. IntegrationConnection
        from apps.integrations.models import IntegrationConnection
        IntegrationConnection.objects.filter(organization=org).delete()

        # 11. AuditEvent — append-only queryset blocks ORM delete; use raw SQL
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM audit_auditevent WHERE organization_id = %s",
                [str(org.id)],
            )

        # 12. Membership — cascade from org deletion, but explicit for safety
        Membership.objects.filter(organization=org).delete()

        # 13. Organization
        org.delete()

        # 14. Seed users (remove after org so membership cascade doesn't conflict)
        User.objects.filter(email__in=seed_emails).delete()

        self.stdout.write("  Seed data wiped.\n")

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
    # Runner pool + registration token
    # ------------------------------------------------------------------

    def _seed_runner_pool(self):
        from apps.runners.models import RunnerPool, RunnerRegistrationToken

        pool, created = RunnerPool.objects.get_or_create(
            organization=self._org,
            key="default",
            defaults={
                "name": "Default Runner Pool",
                "display_name": "Default",
                "description": "Default runner pool for local development and manual testing.",
                "status": RunnerPool.Status.ACTIVE,
                "max_concurrent_executions": 5,
                "default_for_non_change_executions": False,
            },
        )
        self._pool = pool
        self._report("RunnerPool", pool.key, created)

        reg_token = getattr(settings, "RUNNER_REGISTRATION_TOKEN", "")
        if not reg_token:
            self.stdout.write(
                self.style.WARNING(
                    "  [Skipped] RunnerRegistrationToken: RUNNER_REGISTRATION_TOKEN not set in .env.\n"
                    "  The runner cannot claim executions until a token is configured."
                )
            )
            self._token_created = False
            return

        token_hash = hashlib.sha256(reg_token.encode()).hexdigest()
        tok, created = RunnerRegistrationToken.objects.get_or_create(
            token_hash=token_hash,
            defaults={
                "organization": self._org,
                "pool": pool,
                "expires_at": timezone.now() + timedelta(days=365),
                "max_registrations": 100,
            },
        )
        self._token_created = created
        self._report("RunnerRegistrationToken", "seed token (100 uses, 365 day TTL)", created)

    def _print_runner_instructions(self):
        self.stdout.write(
            "\nRunner setup:\n"
            "  The seed org 'acme-platform-eng' now has a runner pool tied to\n"
            "  your RUNNER_REGISTRATION_TOKEN. Restart the runner to pick it up:\n\n"
            "    docker compose restart runner\n\n"
            "  The runner will re-register to the seed org and start claiming executions.\n"
        )

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
                    "failure_kind": "action_failed",
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
        from apps.approvals.models import ApprovalDecision as _AD

        existing_ar = ApprovalRequest.objects.filter(step=step2).first()
        if existing_ar is not None:
            _AD.objects.filter(approval_request=existing_ar).delete()
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
    # Operation profiles
    # ------------------------------------------------------------------

    def _seed_operation_profiles(self):
        from apps.audit.services import system_actor
        from apps.changes.models import OperationProfile
        from apps.changes.services import create_operation_profile

        actor = system_actor("seed_dev")

        # Each spec: fields for create_operation_profile + extras set via update()
        specs = [
            {
                "key": "prod-deploy",
                "name": "Production Deploy",
                "description": (
                    "Standard production deployment for API and frontend services. "
                    "Requires approval and post-deployment verification."
                ),
                "risk_level": "high",
                "requires_approval": True,
                "verification_required": True,
                "dispatch_ttl_seconds": 900,
                "allowed_target_types": ["service"],
                "target_schema": {"allow_empty_targets": False, "max_targets": 5},
                "_allow_emergency": True,
                "_max_breakglass": 3600,
                "_retro_sla": 86400,
                "_verif_template": {
                    "checks": [
                        {
                            "key": "health-check",
                            "name": "Post-deployment health check",
                            "type": "manual_attestation",
                            "required": True,
                            "manual_attestation_config": {
                                "instructions": "Verify the deployed service is responding correctly to health endpoint.",
                                "min_chars": 20,
                            },
                        },
                        {
                            "key": "error-rate",
                            "name": "Error rate within normal bounds",
                            "type": "manual_attestation",
                            "required": True,
                            "manual_attestation_config": {
                                "instructions": "Check error rate dashboard — confirm p99 latency and error rate are normal.",
                                "min_chars": 10,
                            },
                        },
                    ]
                },
                "_workflows": ["deploy"],
            },
            {
                "key": "db-migration",
                "name": "Database Migration",
                "description": (
                    "Schema and data migrations requiring DBA review and row-count verification."
                ),
                "risk_level": "critical",
                "requires_approval": True,
                "verification_required": True,
                "dispatch_ttl_seconds": 1800,
                "allowed_target_types": ["database"],
                "target_schema": {"allow_empty_targets": False, "max_targets": 3},
                "_allow_emergency": False,
                "_max_breakglass": None,
                "_retro_sla": None,
                "_verif_template": {
                    "checks": [
                        {
                            "key": "row-counts",
                            "name": "Verify row counts post-migration",
                            "type": "manual_attestation",
                            "required": True,
                            "manual_attestation_config": {
                                "instructions": "Run SELECT COUNT(*) on affected tables and confirm expected counts.",
                                "min_chars": 20,
                            },
                        }
                    ]
                },
                "_workflows": ["deploy"],
            },
            {
                "key": "rollback",
                "name": "Service Rollback",
                "description": "Emergency rollback to the previous stable release version.",
                "risk_level": "high",
                "requires_approval": True,
                "verification_required": True,
                "dispatch_ttl_seconds": 900,
                "allowed_target_types": ["service"],
                "target_schema": {"allow_empty_targets": False, "max_targets": 5},
                "_allow_emergency": True,
                "_max_breakglass": 1800,
                "_retro_sla": 86400,
                "_verif_template": {"checks": []},
                "_workflows": ["incident"],
            },
            {
                "key": "emergency-remediation",
                "name": "Emergency Remediation",
                "description": (
                    "Unplanned emergency response for active production incidents. "
                    "Supports breakglass and bypass procedures."
                ),
                "risk_level": "high",
                "requires_approval": False,
                "verification_required": True,
                "dispatch_ttl_seconds": 1800,
                "allowed_target_types": ["service", "database"],
                "target_schema": {"allow_empty_targets": False, "max_targets": 10},
                "_allow_emergency": True,
                "_max_breakglass": 7200,
                "_retro_sla": 43200,
                "_verif_template": {
                    "checks": [
                        {
                            "key": "incident-resolved",
                            "name": "Incident resolved confirmation",
                            "type": "manual_attestation",
                            "required": True,
                            "manual_attestation_config": {
                                "instructions": "Confirm the incident is fully resolved and service is stable.",
                                "min_chars": 20,
                            },
                        }
                    ]
                },
                "_workflows": ["incident"],
            },
        ]

        self._profiles = {}
        for spec in specs:
            existing = OperationProfile.objects.filter(
                organization=self._org, key=spec["key"]
            ).first()
            if existing:
                self._profiles[spec["key"]] = existing
                self._report("OperationProfile", spec["name"], False)
                continue

            # Extract extra fields not accepted by the service
            allow_emergency = spec.pop("_allow_emergency", False)
            max_breakglass = spec.pop("_max_breakglass", None)
            retro_sla = spec.pop("_retro_sla", None)
            verif_template = spec.pop("_verif_template", {})
            workflow_keys = spec.pop("_workflows", [])
            workflow_ids = [
                str(self._workflows[k].id)
                for k in workflow_keys
                if k in self._workflows
            ]

            profile = create_operation_profile(
                organization=self._org,
                actor=actor,
                workflow_ids=workflow_ids,
                **spec,
            )
            OperationProfile.objects.filter(pk=profile.pk).update(
                allow_emergency_changes=allow_emergency,
                max_breakglass_seconds=max_breakglass,
                retro_review_sla_seconds=retro_sla,
                verification_plan_template=verif_template,
                allowed_runner_pool_keys=["default"],
            )
            profile.refresh_from_db()
            self._profiles[profile.key] = profile
            self._report("OperationProfile", profile.name, True)

    # ------------------------------------------------------------------
    # Target connectivity routes
    # ------------------------------------------------------------------

    def _seed_target_connectivity_routes(self):
        from apps.runners.models import TargetConnectivityRoute

        routes = [
            {
                "environment": "production",
                "target_type": "service",
                "normalized_identifier_pattern": "*",
                "priority": 100,
                "is_active": True,
                "_label": "service/* → default pool",
            },
            {
                "environment": "production",
                "target_type": "database",
                "normalized_identifier_pattern": "db-*",
                "priority": 100,
                "is_active": True,
                "_label": "database/db-* → default pool",
            },
            {
                "environment": "production",
                "target_type": "legacy-service",
                "normalized_identifier_pattern": "*",
                "priority": 200,
                "is_active": False,  # inactive — shows disabled state in UI
                "_label": "legacy-service/* → default pool (inactive)",
            },
        ]

        for r in routes:
            label = r.pop("_label")
            route, created = TargetConnectivityRoute.objects.get_or_create(
                organization=self._org,
                environment=r["environment"],
                target_type=r["target_type"],
                normalized_identifier_pattern=r["normalized_identifier_pattern"],
                pool=self._pool,
                defaults={
                    "priority": r["priority"],
                    "is_active": r["is_active"],
                },
            )
            self._report("TargetConnectivityRoute", label, created)

    # ------------------------------------------------------------------
    # Freeze rules
    # ------------------------------------------------------------------

    def _seed_freeze_rules(self):
        from apps.changes.models import FreezeRule

        now = timezone.now()
        admin = self._admin_user()

        rules = [
            # Past — shows in list as inactive/expired
            {
                "name": "Q4 2024 Code Freeze",
                "description": "Year-end code freeze covering all production targets.",
                "is_active": False,
                "behavior": FreezeRule.Behavior.BLOCK,
                "scope_type": FreezeRule.ScopeType.ALL_PRODUCTION,
                "starts_at": now - timedelta(days=180),
                "ends_at": now - timedelta(days=90),
                "requires_exception_reference": False,
            },
            # Future active — upcoming maintenance window (blocks preflight when active)
            {
                "name": "Quarterly Maintenance Window",
                "description": "Upcoming maintenance window blocking non-emergency changes.",
                "is_active": True,
                "behavior": FreezeRule.Behavior.BLOCK,
                "scope_type": FreezeRule.ScopeType.ALL_PRODUCTION,
                "starts_at": now + timedelta(days=14),
                "ends_at": now + timedelta(days=14, hours=8),
                "requires_exception_reference": False,
            },
            # Currently active allow-with-exception — will show conflict on preflight
            {
                "name": "Database Service Freeze (Exception Allowed)",
                "description": "Database changes require a change-management ticket reference.",
                "is_active": True,
                "behavior": FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
                "scope_type": FreezeRule.ScopeType.TARGET_TYPE,
                "target_type": "database",
                "starts_at": now - timedelta(days=3),
                "ends_at": now + timedelta(days=4),
                "requires_exception_reference": True,
            },
        ]

        for r in rules:
            freeze, created = FreezeRule.objects.get_or_create(
                organization=self._org,
                name=r["name"],
                defaults={**r, "created_by": admin, "updated_by": admin},
            )
            self._report("FreezeRule", freeze.name, created)

    # ------------------------------------------------------------------
    # Change records (full lifecycle coverage)
    # ------------------------------------------------------------------

    def _seed_change_records(self):
        """Seed change records across all meaningful lifecycle states."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self._changes = {}

        # Load users for actor references
        admin = self._admin_user()
        operator = User.objects.filter(email="operator@acme.test").first()

        # Require profiles and workflows to exist
        if not self._profiles or "prod-deploy" not in self._profiles:
            self.stdout.write(
                self.style.WARNING("  [Skipped] Change records: no operation profiles seeded.")
            )
            return

        deploy_wf = self._workflows.get("deploy")
        incident_wf = self._workflows.get("incident")
        if not deploy_wf or not incident_wf:
            self.stdout.write(
                self.style.WARNING("  [Skipped] Change records: seed workflows missing.")
            )
            return

        prod_profile = self._profiles["prod-deploy"]
        db_profile = self._profiles.get("db-migration", prod_profile)
        emerg_profile = self._profiles.get("emergency-remediation", prod_profile)

        # ------- 1. DRAFT -------
        self._changes["draft"] = self._seed_change_in_status(
            profile=prod_profile,
            workflow=deploy_wf,
            title="[Seed] Production Deploy — Draft",
            summary="Frontend v2.4.1 release including performance improvements.",
            justification="Scheduled quarterly release. All CI checks passing.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "frontend",
                    "environment": "production",
                    "display_name": "Frontend Service",
                }
            ],
            requested_inputs={"version": "v2.4.1", "rollback_version": "v2.4.0"},
            requested_by=admin,
        )
        self._report("ChangeRecord", "[Seed] Draft", self._changes["draft"][1])

        # ------- 2. PENDING_APPROVAL -------
        self._changes["pending_approval"] = self._seed_change_in_status(
            profile=prod_profile,
            workflow=deploy_wf,
            title="[Seed] Production Deploy — Pending Approval",
            summary="API service v3.1.0 with new rate limiting and auth improvements.",
            justification="Planned release after QA sign-off. Requires manager approval.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "api-service",
                    "environment": "production",
                    "display_name": "API Service",
                }
            ],
            requested_inputs={"version": "v3.1.0", "rollback_version": "v3.0.9"},
            requested_by=operator,
            advance_to="pending_approval",
            advance_by=operator,
            advance_at=timedelta(hours=-6),
        )
        self._report("ChangeRecord", "[Seed] Pending Approval", self._changes["pending_approval"][1])

        # ------- 3. APPROVED -------
        self._changes["approved"] = self._seed_change_in_status(
            profile=prod_profile,
            workflow=deploy_wf,
            title="[Seed] Production Deploy — Approved",
            summary="Worker service v1.8.2 with queue processing improvements.",
            justification="Performance-critical fix approved by platform lead.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "worker-service",
                    "environment": "production",
                    "display_name": "Worker Service",
                }
            ],
            requested_inputs={"version": "v1.8.2", "rollback_version": "v1.8.1"},
            requested_by=admin,
            advance_to="approved",
            advance_by=admin,
            advance_at=timedelta(hours=-3),
        )
        self._report("ChangeRecord", "[Seed] Approved", self._changes["approved"][1])

        # ------- 4. RUNNING (with execution binding) -------
        self._changes["running"] = self._seed_change_running()
        self._report("ChangeRecord", "[Seed] Running", self._changes["running"][1])

        # ------- 5. VERIFICATION_PENDING -------
        self._changes["verification_pending"] = self._seed_change_verification_pending(
            admin=admin, operator=operator
        )
        self._report("ChangeRecord", "[Seed] Verification Pending", self._changes["verification_pending"][1])

        # ------- 6. VERIFIED -------
        self._changes["verified"] = self._seed_change_in_status(
            profile=prod_profile,
            workflow=deploy_wf,
            title="[Seed] Production Deploy — Verified",
            summary="Cache service v0.9.4 deployed and verified clean.",
            justification="Routine cache warming update with automated smoke tests.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "cache-service",
                    "environment": "production",
                    "display_name": "Cache Service",
                }
            ],
            requested_inputs={"version": "v0.9.4", "rollback_version": "v0.9.3"},
            requested_by=admin,
            advance_to="verified",
            advance_by=admin,
            advance_at=timedelta(hours=-1),
        )
        self._report("ChangeRecord", "[Seed] Verified", self._changes["verified"][1])

        # ------- 7. CLOSED (success) — primary evidence target -------
        self._changes["closed"] = self._seed_change_closed(admin=admin, operator=operator)
        self._report("ChangeRecord", "[Seed] Closed (success)", self._changes["closed"][1])

        # ------- 8. CLOSED (rolled_back) -------
        self._changes["closed_rollback"] = self._seed_change_in_status(
            profile=prod_profile,
            workflow=deploy_wf,
            title="[Seed] Production Deploy — Closed (Rolled Back)",
            summary="Auth service v2.0.0 deployment rolled back due to latency spike.",
            justification="Urgent fix triggered by P1 incident during canary.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "auth-service",
                    "environment": "production",
                    "display_name": "Auth Service",
                }
            ],
            requested_inputs={"version": "v2.0.0", "rollback_version": "v1.9.8"},
            requested_by=operator,
            advance_to="closed",
            advance_by=admin,
            advance_at=timedelta(days=-2),
            extra_fields={"terminal_reason": "rolled_back"},
        )
        self._report("ChangeRecord", "[Seed] Closed (Rolled Back)", self._changes["closed_rollback"][1])

        # ------- 9. REJECTED -------
        self._changes["rejected"] = self._seed_change_in_status(
            profile=db_profile,
            workflow=deploy_wf,
            title="[Seed] Database Migration — Rejected",
            summary="Schema migration adding nullable columns to billing table.",
            justification="Required for billing v4 feature flag support.",
            targets=[
                {
                    "target_type": "database",
                    "target_identifier": "db-billing",
                    "environment": "production",
                    "display_name": "Billing Database",
                }
            ],
            requested_inputs={"migration_name": "0042_billing_v4_flags", "dry_run": False},
            requested_by=operator,
            advance_to="rejected",
            advance_by=admin,
            advance_at=timedelta(hours=-8),
            extra_fields={"terminal_reason": "policy_violation"},
        )
        self._report("ChangeRecord", "[Seed] Rejected", self._changes["rejected"][1])

        # ------- 10. CANCELED -------
        self._changes["canceled"] = self._seed_change_in_status(
            profile=prod_profile,
            workflow=deploy_wf,
            title="[Seed] Production Deploy — Canceled",
            summary="Notification service v1.2.3 release — canceled by requester.",
            justification="Superseded by emergency hotfix v1.2.4.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "notification-service",
                    "environment": "production",
                    "display_name": "Notification Service",
                }
            ],
            requested_inputs={"version": "v1.2.3"},
            requested_by=admin,
            advance_to="canceled",
            advance_by=admin,
            advance_at=timedelta(days=-1),
            extra_fields={"terminal_reason": "requester_canceled"},
        )
        self._report("ChangeRecord", "[Seed] Canceled", self._changes["canceled"][1])

        # ------- 11. EMERGENCY + active breakglass session -------
        self._changes["emergency"] = self._seed_change_emergency(
            admin=admin, emerg_profile=emerg_profile
        )
        self._report("ChangeRecord", "[Seed] Emergency + Breakglass", self._changes["emergency"][1])

    def _admin_user(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.filter(email="admin@acme.test").first()

    def _seed_change_in_status(
        self,
        *,
        profile,
        workflow,
        title,
        summary,
        justification,
        targets,
        requested_inputs=None,
        requested_by=None,
        advance_to=None,
        advance_by=None,
        advance_at=None,
        extra_fields=None,
    ):
        """Create a draft change via service then advance status directly."""
        from apps.audit.services import system_actor
        from apps.audit.models import AuditEvent
        from apps.changes.models import ChangeRecord
        from apps.changes.services import create_change_record, sha256_canonical_json

        # Return existing if already seeded (title is our idempotency key)
        existing = ChangeRecord.objects.filter(
            organization=self._org, title=title
        ).first()
        if existing is not None:
            return existing, False

        # Build actor
        if requested_by is not None:
            from apps.audit.services import AuditActor

            actor = AuditActor(
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(requested_by.id),
                actor_label=requested_by.email,
            )
        else:
            actor = system_actor("seed_dev")

        change = create_change_record(
            organization=self._org,
            operation_profile_key=profile.key,
            workflow_id=str(workflow.id),
            title=title,
            summary=summary,
            justification=justification,
            requested_inputs=requested_inputs or {},
            targets=targets,
            actor=actor,
        )

        if advance_to is None or advance_to == "draft":
            return change, True

        now = timezone.now()
        base_time = now + (advance_at or timedelta())
        target_objs = list(change.targets.order_by("position"))

        # Compute snapshot hashes (same as submit_change_record does)
        inputs_sha = sha256_canonical_json(change.requested_inputs)
        from apps.changes.services import build_request_snapshot

        snapshot = build_request_snapshot(
            change, target_objs, submitted_at=base_time, profile=profile, workflow=workflow
        )
        snapshot_sha = sha256_canonical_json(snapshot)
        wf_def_sha = sha256_canonical_json(workflow.definition or {})

        # Map target status to timestamps
        ts = {
            "pending_approval": {"submitted_at": base_time, "status": "pending_approval"},
            "approved": {
                "submitted_at": base_time - timedelta(hours=1),
                "approved_at": base_time,
                "status": "approved",
            },
            "dispatchable": {
                "submitted_at": base_time - timedelta(hours=2),
                "approved_at": base_time - timedelta(hours=1),
                "dispatchable_at": base_time,
                "status": "dispatchable",
            },
            "running": {
                "submitted_at": base_time - timedelta(hours=3),
                "approved_at": base_time - timedelta(hours=2),
                "dispatchable_at": base_time - timedelta(hours=1),
                "running_at": base_time,
                "status": "running",
            },
            "verification_pending": {
                "submitted_at": base_time - timedelta(hours=4),
                "approved_at": base_time - timedelta(hours=3),
                "dispatchable_at": base_time - timedelta(hours=2),
                "running_at": base_time - timedelta(hours=1, minutes=30),
                "verification_pending_at": base_time,
                "status": "verification_pending",
            },
            "verified": {
                "submitted_at": base_time - timedelta(hours=5),
                "approved_at": base_time - timedelta(hours=4),
                "dispatchable_at": base_time - timedelta(hours=3),
                "running_at": base_time - timedelta(hours=2),
                "verified_at": base_time,
                "status": "verified",
            },
            "closed": {
                "submitted_at": base_time - timedelta(hours=6),
                "approved_at": base_time - timedelta(hours=5),
                "dispatchable_at": base_time - timedelta(hours=4),
                "running_at": base_time - timedelta(hours=3),
                "verified_at": base_time - timedelta(hours=1),
                "closed_at": base_time,
                "status": "closed",
            },
            "rejected": {
                "submitted_at": base_time - timedelta(hours=2),
                "rejected_at": base_time,
                "status": "rejected",
            },
            "canceled": {
                "submitted_at": base_time - timedelta(hours=3),
                "canceled_at": base_time,
                "status": "canceled",
            },
        }

        fields = ts.get(advance_to, {"status": advance_to})
        fields.update(
            {
                "requested_inputs_sha256": inputs_sha,
                "request_snapshot": snapshot,
                "request_snapshot_sha256": snapshot_sha,
                "operation_profile_key_snapshot": profile.key,
                "workflow_version_snapshot": workflow.version,
                "workflow_definition_sha256": wf_def_sha,
                "submitted_by_id": str(advance_by.id) if advance_by else None,
            }
        )
        if extra_fields:
            fields.update(extra_fields)

        ChangeRecord.objects.filter(pk=change.pk).update(**fields)
        change.refresh_from_db()
        return change, True

    def _seed_change_running(self):
        """Running change with execution binding."""
        import json

        from apps.changes.models import ChangeExecutionBinding, ChangeRecord
        from apps.changes.services import sha256_canonical_json, build_request_snapshot
        from apps.executions.models import Execution

        profile = self._profiles.get("prod-deploy")
        workflow = self._workflows.get("deploy")
        admin = self._admin_user()
        title = "[Seed] Production Deploy — Running"

        existing = ChangeRecord.objects.filter(
            organization=self._org, title=title
        ).first()
        if existing is not None:
            return existing, False

        change, _ = self._seed_change_in_status(
            profile=profile,
            workflow=workflow,
            title=title,
            summary="Scheduler service v2.2.0 deployment in progress.",
            justification="Approved for scheduled maintenance window.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "scheduler-service",
                    "environment": "production",
                    "display_name": "Scheduler Service",
                }
            ],
            requested_inputs={"version": "v2.2.0", "rollback_version": "v2.1.9"},
            requested_by=admin,
            advance_to="running",
            advance_by=admin,
            advance_at=timedelta(hours=-1),
        )

        # Create a queued execution to bind to this change
        try:
            from apps.executions.services import create_execution

            ex = create_execution(workflow=workflow)
            now = timezone.now()
            Execution.objects.filter(pk=ex.pk).update(
                status=Execution.Status.RUNNING,
                started_at=now - timedelta(minutes=30),
                claimed_by_runner_id="seed-runner-01",
                claim_token=uuid.uuid4(),
                claimed_at=now - timedelta(minutes=30),
            )
            ex.refresh_from_db()

            # Create a simple binding (mimics what dispatch would create)
            nonce = secrets.token_hex(32)
            token_hash = hashlib.sha256(nonce.encode()).hexdigest()

            if not ChangeExecutionBinding.objects.filter(change_record=change).exists():
                ChangeExecutionBinding.objects.create(
                    change_record=change,
                    execution=ex,
                    organization=self._org,
                    operation_profile_key=profile.key,
                    requested_inputs_sha256=hashlib.sha256(
                        json.dumps(change.requested_inputs, sort_keys=True).encode()
                    ).hexdigest(),
                    dispatch_token_nonce=nonce,
                    dispatch_token_hash=token_hash,
                    dispatch_token_expires_at=now + timedelta(minutes=15),
                    reserved_at=now - timedelta(minutes=30),
                    bound_at=now - timedelta(minutes=29),
                    bound_by_runner_id="seed-runner-01",
                    execution_accepted_at=now - timedelta(minutes=29),
                    execution_started_at=now - timedelta(minutes=28),
                )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  [Warning] Running change binding: {exc}"))

        return change, True

    def _seed_change_verification_pending(self, *, admin, operator):
        """Change in verification_pending with a VerificationPlan and pending checks."""
        from apps.changes.models import (
            ChangeRecord,
            VerificationCheck,
            VerificationPlan,
        )
        from apps.changes.services import sha256_canonical_json

        profile = self._profiles.get("prod-deploy")
        workflow = self._workflows.get("deploy")
        title = "[Seed] Production Deploy — Verification Pending"

        change, created = self._seed_change_in_status(
            profile=profile,
            workflow=workflow,
            title=title,
            summary="Metrics service v1.5.0 deployed; awaiting manual post-deployment verification.",
            justification="Scheduled release — requires health check attestation.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "metrics-service",
                    "environment": "production",
                    "display_name": "Metrics Service",
                }
            ],
            requested_inputs={"version": "v1.5.0", "rollback_version": "v1.4.9"},
            requested_by=operator,
            advance_to="verification_pending",
            advance_by=admin,
            advance_at=timedelta(hours=-2),
        )

        # Create VerificationPlan if not exists
        plan, plan_created = VerificationPlan.objects.get_or_create(
            change_record=change,
            defaults={
                "organization": self._org,
                "operation_profile": profile,
                "mode": VerificationPlan.Mode.MANUAL,
                "status": VerificationPlan.Status.ACTIVE,
                "generated_from_profile_snapshot": {"key": profile.key, "name": profile.name},
                "generated_from_profile_sha256": sha256_canonical_json(
                    {"key": profile.key, "name": profile.name}
                ),
                "required_check_count": 2,
                "optional_check_count": 0,
                "satisfied_required_count": 0,
                "failed_required_count": 0,
                "generated_at": timezone.now() - timedelta(hours=2),
                "activated_at": timezone.now() - timedelta(hours=2),
            },
        )
        self._report("VerificationPlan", f"[Seed] Verification Pending plan", plan_created)

        # Create checks
        check_specs = [
            {
                "key": "health-check",
                "name": "Post-deployment health check",
                "check_type": VerificationCheck.CheckType.MANUAL_ATTESTATION,
                "required": True,
                "position": 0,
                "description": "Verify the deployed service is responding correctly.",
                "manual_attestation_config": {
                    "instructions": "Check /health endpoint returns 200 OK.",
                    "min_chars": 20,
                },
            },
            {
                "key": "error-rate",
                "name": "Error rate within normal bounds",
                "check_type": VerificationCheck.CheckType.MANUAL_ATTESTATION,
                "required": True,
                "position": 1,
                "description": "Check monitoring dashboard for error rate.",
                "manual_attestation_config": {
                    "instructions": "Confirm error rate < 1% in Grafana dashboard.",
                    "min_chars": 10,
                },
            },
        ]
        for cs in check_specs:
            VerificationCheck.objects.get_or_create(
                plan=plan,
                key=cs["key"],
                defaults={
                    "organization": self._org,
                    "change_record": change,
                    "position": cs["position"],
                    "name": cs["name"],
                    "description": cs["description"],
                    "check_type": cs["check_type"],
                    "required": cs["required"],
                    "status": VerificationCheck.Status.PENDING,
                    "manual_attestation_config": cs.get("manual_attestation_config", {}),
                },
            )

        return change, created

    def _seed_change_closed(self, *, admin, operator):
        """Closed (success) change — the primary target for evidence bundle seeding."""
        import json

        from apps.changes.models import (
            ChangeRecord,
            ChangeClosure,
            VerificationCheck,
            VerificationPlan,
            VerificationResult,
        )
        from apps.changes.services import sha256_canonical_json

        profile = self._profiles.get("prod-deploy")
        workflow = self._workflows.get("deploy")
        title = "[Seed] Production Deploy — Closed (Success)"

        change, created = self._seed_change_in_status(
            profile=profile,
            workflow=workflow,
            title=title,
            summary="Payments service v4.1.0 successfully deployed and verified.",
            justification="Scheduled Q1 release with PCI compliance improvements.",
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "payments-service",
                    "environment": "production",
                    "display_name": "Payments Service",
                }
            ],
            requested_inputs={"version": "v4.1.0", "rollback_version": "v4.0.9"},
            requested_by=operator,
            advance_to="closed",
            advance_by=admin,
            advance_at=timedelta(days=-3),
        )

        # Create verification plan + completed checks
        plan, _ = VerificationPlan.objects.get_or_create(
            change_record=change,
            defaults={
                "organization": self._org,
                "operation_profile": profile,
                "mode": VerificationPlan.Mode.MANUAL,
                "status": VerificationPlan.Status.SATISFIED,
                "generated_from_profile_snapshot": {"key": profile.key},
                "generated_from_profile_sha256": sha256_canonical_json({"key": profile.key}),
                "required_check_count": 2,
                "optional_check_count": 0,
                "satisfied_required_count": 2,
                "failed_required_count": 0,
                "generated_at": timezone.now() - timedelta(days=3, hours=4),
                "activated_at": timezone.now() - timedelta(days=3, hours=3),
                "satisfied_at": timezone.now() - timedelta(days=3, hours=1),
            },
        )

        check1, _ = VerificationCheck.objects.get_or_create(
            plan=plan,
            key="health-check",
            defaults={
                "organization": self._org,
                "change_record": change,
                "position": 0,
                "name": "Post-deployment health check",
                "check_type": VerificationCheck.CheckType.MANUAL_ATTESTATION,
                "required": True,
                "status": VerificationCheck.Status.PASSED,
                "manual_attestation_config": {
                    "instructions": "Check /health endpoint.",
                    "min_chars": 20,
                },
                "satisfied_at": timezone.now() - timedelta(days=3, hours=2),
            },
        )
        check2, _ = VerificationCheck.objects.get_or_create(
            plan=plan,
            key="error-rate",
            defaults={
                "organization": self._org,
                "change_record": change,
                "position": 1,
                "name": "Error rate within normal bounds",
                "check_type": VerificationCheck.CheckType.MANUAL_ATTESTATION,
                "required": True,
                "status": VerificationCheck.Status.PASSED,
                "manual_attestation_config": {
                    "instructions": "Confirm error rate < 1%.",
                    "min_chars": 10,
                },
                "satisfied_at": timezone.now() - timedelta(days=3, hours=1, minutes=30),
            },
        )

        # Create verification results (immutable — skip if already exist)
        for check in [check1, check2]:
            if not VerificationResult.objects.filter(
                plan=plan, verification_check=check
            ).exists():
                VerificationResult.objects.create(
                    organization=self._org,
                    change_record=change,
                    plan=plan,
                    verification_check=check,
                    source=VerificationResult.Source.USER,
                    outcome=VerificationResult.Outcome.PASSED,
                    validation_status=VerificationResult.ValidationStatus.ACCEPTED,
                    submitted_by=operator,
                    manual_attestation_text=(
                        "Health check confirmed — /health returns 200 OK with all systems nominal."
                        if check.key == "health-check"
                        else "Error rate is 0.02% over 30m window — well within 1% threshold."
                    ),
                    submitted_at=timezone.now() - timedelta(days=3, hours=2),
                    validated_at=timezone.now() - timedelta(days=3, hours=2),
                )

        # Create ChangeClosure (immutable — skip if exists)
        if not ChangeClosure.objects.filter(change_record=change).exists():
            ChangeClosure.objects.create(
                organization=self._org,
                change_record=change,
                outcome=ChangeClosure.Outcome.SUCCESS,
                closed_by=admin,
                independent_reviewer=operator,
                summary=(
                    "Payments service v4.1.0 deployed successfully. "
                    "All health checks passed. Error rate nominal. "
                    "No rollback required."
                ),
                verification_plan=plan,
                verification_summary={
                    "required_checks": 2,
                    "passed": 2,
                    "failed": 0,
                    "status": "satisfied",
                },
                execution_summary={"workflow": workflow.name, "status": "succeeded"},
                closed_at=timezone.now() - timedelta(days=3),
            )

        self._changes_closed_plan = plan
        return change, created

    def _seed_change_emergency(self, *, admin, emerg_profile):
        """Emergency change with active breakglass session and pending retro review."""
        import json
        from apps.changes.models import (
            BreakglassSession,
            ChangeRecord,
            RetroReview,
        )
        from apps.changes.services import sha256_canonical_json

        workflow = self._workflows.get("incident")
        title = "[Seed] Emergency Remediation — Active Breakglass"

        existing = ChangeRecord.objects.filter(
            organization=self._org, title=title
        ).first()
        if existing is not None:
            return existing, False

        from apps.audit.services import AuditActor
        from apps.audit.models import AuditEvent

        actor = AuditActor(
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(admin.id),
            actor_label=admin.email,
        )
        from apps.changes.services import create_change_record

        change = create_change_record(
            organization=self._org,
            operation_profile_key=emerg_profile.key,
            workflow_id=str(workflow.id),
            title=title,
            summary="P1 incident: authentication service returning 503s for 12% of requests.",
            justification="Emergency remediation to restore auth service stability.",
            requested_inputs={"rollback_target": "auth-service", "strategy": "pod-restart"},
            targets=[
                {
                    "target_type": "service",
                    "target_identifier": "auth-service",
                    "environment": "production",
                    "display_name": "Auth Service",
                }
            ],
            actor=actor,
            is_emergency=True,
            emergency_reason=(
                "Auth service degraded: 12% of login requests failing with 503. "
                "Customer-impacting incident INC-2024-0847 declared P1."
            ),
        )

        now = timezone.now()
        from apps.changes.services import build_request_snapshot

        target_objs = list(change.targets.order_by("position"))
        snapshot = build_request_snapshot(
            change,
            target_objs,
            submitted_at=now - timedelta(hours=1),
            profile=emerg_profile,
            workflow=workflow,
        )
        snapshot_sha = sha256_canonical_json(snapshot)

        ChangeRecord.objects.filter(pk=change.pk).update(
            status="running",
            submitted_at=now - timedelta(hours=1),
            approved_at=now - timedelta(hours=1),
            dispatchable_at=now - timedelta(minutes=55),
            running_at=now - timedelta(minutes=50),
            requested_inputs_sha256=sha256_canonical_json(change.requested_inputs),
            request_snapshot=snapshot,
            request_snapshot_sha256=snapshot_sha,
            operation_profile_key_snapshot=emerg_profile.key,
            workflow_version_snapshot=workflow.version,
            workflow_definition_sha256=sha256_canonical_json(workflow.definition or {}),
            submitted_by_id=str(admin.id),
            retro_review_required=True,
            retro_review_due_at=now + timedelta(hours=23),
        )
        change.refresh_from_db()

        # Create active breakglass session
        scope_json = {"service_keys": ["auth-service"], "statuses": ["running"]}
        scope_sha = hashlib.sha256(
            json.dumps(scope_json, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        bgl, bgl_created = BreakglassSession.objects.get_or_create(
            change_record=change,
            status=BreakglassSession.Status.ACTIVE,
            defaults={
                "organization": self._org,
                "scope_json": scope_json,
                "scope_sha256": scope_sha,
                "reason": (
                    "Auth service P1 incident — bypassing normal approval window "
                    "to restore service immediately."
                ),
                "activated_by": admin,
                "started_at": now - timedelta(minutes=50),
                "expires_at": now + timedelta(minutes=70),
                "review_due_at": now + timedelta(hours=23),
                "review_status": BreakglassSession.ReviewStatus.PENDING,
                "last_heartbeat_at": now - timedelta(minutes=2),
            },
        )
        self._report("BreakglassSession", "[Seed] Active breakglass", bgl_created)

        # RetroReview — pending (requires breakglass_session)
        retro, retro_created = RetroReview.objects.get_or_create(
            change_record=change,
            breakglass_session=bgl,
            defaults={
                "organization": self._org,
                "status": RetroReview.Status.PENDING,
                "due_at": now + timedelta(hours=23),
                "remediation_required": False,
            },
        )
        self._report("RetroReview", "[Seed] Pending retro review", retro_created)
        return change, True

    # ------------------------------------------------------------------
    # Evidence bundles and auditor workspace
    # ------------------------------------------------------------------

    def _seed_auditor_workspace(self):
        """Seed evidence bundles, auditor grants, service catalog, external refs."""
        admin = self._admin_user()
        self._seed_evidence_bundle(admin=admin)
        self._seed_service_catalog(admin=admin)
        self._seed_control_mapping(admin=admin)
        self._seed_external_references(admin=admin)
        self._seed_auditor_grants(admin=admin)
        self._seed_completed_retro_review(admin=admin)

    def _seed_evidence_bundle(self, *, admin):
        """Create sealed + exported evidence bundle on the closed change."""
        import json

        from apps.evidence.models import EvidenceBundle, EvidenceBundleItem, EvidenceExport

        closed_change = self._changes.get("closed")
        if closed_change is None or closed_change[0] is None:
            return
        change = closed_change[0] if isinstance(closed_change, tuple) else closed_change

        # Get change from db to confirm it's closed
        from apps.changes.models import ChangeRecord

        change = ChangeRecord.objects.filter(pk=change.pk).first()
        if change is None or change.status != ChangeRecord.Status.CLOSED:
            return

        # Compiling bundle on the verified (but not closed) change — shows completeness UI
        verified_change_tuple = self._changes.get("verified")
        if verified_change_tuple is not None:
            verified_change = (
                verified_change_tuple[0]
                if isinstance(verified_change_tuple, tuple)
                else verified_change_tuple
            )
            verified_change = ChangeRecord.objects.filter(pk=verified_change.pk).first()
            if verified_change is not None and verified_change.status == ChangeRecord.Status.VERIFIED:
                EvidenceBundle.objects.get_or_create(
                    change_record=verified_change,
                    version=1,
                    defaults={
                        "organization": self._org,
                        "status": EvidenceBundle.Status.COMPILING,
                        "completeness_status": EvidenceBundle.CompletenessStatus.INCOMPLETE,
                        "completeness_report": {
                            "required": ["change_snapshot", "approval", "verification_result"],
                            "present": ["change_snapshot"],
                            "missing": ["approval", "verification_result"],
                        },
                        "source_cutoff_at": timezone.now(),
                        "source_high_watermark": {"audit_events": 0, "artifacts": 0},
                        "compiled_at": timezone.now() - timedelta(hours=1),
                        "created_by": admin,
                    },
                )
                self._report("EvidenceBundle", "[Seed] Compiling (verified change)", True)

        # Sealed bundle on the closed change
        existing_bundle = EvidenceBundle.objects.filter(change_record=change).first()
        if existing_bundle is not None:
            self._sealed_bundle = existing_bundle
            self._report("EvidenceBundle", "[Seed] Sealed (closed change)", False)
        else:
            # Build deterministic hashes from fixed content
            manifest = {
                "schema_version": "1.0",
                "change_id": str(change.id),
                "org_id": str(self._org.id),
                "items": [
                    {"type": "change_snapshot", "key": str(change.id), "path": "change/snapshot.json"},
                    {"type": "closure", "key": str(change.id), "path": "change/closure.json"},
                    {"type": "verification_result", "key": "check-health-check", "path": "verification/health-check.json"},
                    {"type": "verification_result", "key": "check-error-rate", "path": "verification/error-rate.json"},
                ],
            }
            manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

            payload_data = manifest_bytes + b"\x00" + str(change.id).encode()
            payload_checksums_sha = hashlib.sha256(payload_data).hexdigest()
            content_sha = hashlib.sha256(payload_data + manifest_bytes).hexdigest()
            content_size = len(payload_data) + len(manifest_bytes)

            bundle_id = uuid.uuid4()
            storage_key = (
                f"evidence/org/{self._org.id}/change/{change.id}/bundle/{bundle_id}.zip"
            )
            source_snapshot = {"change_id": str(change.id), "status": "closed", "org_id": str(self._org.id)}
            source_sha = hashlib.sha256(
                json.dumps(source_snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()

            now = timezone.now()
            # Create as COMPILING first so items can be inserted (sealed bundles are immutable)
            bundle = EvidenceBundle.objects.create(
                id=bundle_id,
                organization=self._org,
                change_record=change,
                version=1,
                status=EvidenceBundle.Status.COMPILING,
                completeness_status=EvidenceBundle.CompletenessStatus.COMPLETE,
                completeness_report={
                    "required": ["change_snapshot", "approval", "closure", "verification_result"],
                    "present": ["change_snapshot", "approval", "closure", "verification_result"],
                    "missing": [],
                },
                source_snapshot_sha256=source_sha,
                source_cutoff_at=now - timedelta(days=3),
                source_high_watermark={"audit_events": 12, "artifacts": 1},
                manifest=manifest,
                compiled_at=now - timedelta(days=3, hours=1),
                created_by=admin,
            )

            # Add bundle items while bundle is still COMPILING
            item_specs = [
                ("change_snapshot", str(change.id), "change/snapshot.json", "/", 0),
                ("closure", str(change.id), "change/closure.json", "/outcome", 1),
                ("verification_result", "health-check", "verification/health-check.json", "/outcome", 2),
                ("verification_result", "error-rate", "verification/error-rate.json", "/outcome", 3),
            ]
            for item_type, item_key, path, pointer, pos in item_specs:
                item_content = json.dumps({"type": item_type, "key": item_key}).encode()
                EvidenceBundleItem.objects.get_or_create(
                    bundle=bundle,
                    item_type=item_type,
                    item_key=item_key,
                    defaults={
                        "organization": self._org,
                        "canonical_path": path,
                        "json_pointer": pointer,
                        "position": pos,
                        "required": True,
                        "present": True,
                        "valid": True,
                        "source_type": item_type,
                        "source_id": item_key,
                        "source_updated_at": now - timedelta(days=3),
                        "content_sha256": hashlib.sha256(item_content).hexdigest(),
                        "content_size_bytes": len(item_content),
                        "mime_type": "application/json",
                    },
                )

            # Now seal via filter().update() to bypass the sealed immutability guard
            EvidenceBundle.objects.filter(pk=bundle.pk).update(
                status=EvidenceBundle.Status.SEALED,
                manifest_sha256=manifest_sha,
                payload_checksums_sha256=payload_checksums_sha,
                content_sha256=content_sha,
                content_size_bytes=content_size,
                storage_key=storage_key,
                mime_type="application/zip",
                sealed_at=now - timedelta(days=3),
                sealed_by=admin,
            )
            bundle.refresh_from_db()
            self._sealed_bundle = bundle
            self._report("EvidenceBundle", "[Seed] Sealed (closed change)", True)

        # Create export
        self._seed_evidence_export(change=change, bundle=self._sealed_bundle, admin=admin)

        # Legal hold
        try:
            from apps.evidence.models import LegalHold

            LegalHold.objects.get_or_create(
                change_record=change,
                evidence_bundle=self._sealed_bundle,
                defaults={
                    "organization": self._org,
                    "status": LegalHold.Status.ACTIVE,
                    "reason": (
                        "Regulatory audit request from compliance team — SOC 2 Type II review "
                        "covering Q1 2024 production deployments."
                    ),
                    "external_reference": "LEGAL-2024-0042",
                    "placed_by": admin,
                    "placed_at": timezone.now() - timedelta(days=2),
                },
            )
            self._report("LegalHold", "[Seed] Active legal hold on closed change", True)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  [Warning] LegalHold: {exc}"))

    def _seed_evidence_export(self, *, change, bundle, admin):
        import json

        from apps.evidence.models import EvidenceExport

        if EvidenceExport.objects.filter(bundle=bundle).exists():
            self._report("EvidenceExport", "[Seed] Evidence export (ready)", False)
            return

        now = timezone.now()
        export_id = uuid.uuid4()
        storage_key = (
            f"evidence/org/{self._org.id}/change/{change.id}/export/{export_id}.zip"
        )
        receipt = {
            "export_id": str(export_id),
            "bundle_id": str(bundle.id),
            "change_id": str(change.id),
            "exported_at": now.isoformat(),
            "redaction_policy": "none",
        }
        receipt_bytes = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()

        export_content = bundle.manifest_sha256.encode() + b"\x00" + receipt_bytes
        content_sha = hashlib.sha256(export_content).hexdigest()

        manifest = {"items": list(bundle.manifest.get("items", [])), "receipt": receipt}
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

        EvidenceExport.objects.create(
            id=export_id,
            organization=self._org,
            bundle=bundle,
            status=EvidenceExport.Status.READY,
            requested_by=admin,
            requested_at=now - timedelta(days=2, hours=12),
            ready_at=now - timedelta(days=2, hours=11),
            expires_at=now + timedelta(days=28),
            storage_key=storage_key,
            content_sha256=content_sha,
            content_size_bytes=len(export_content),
            manifest=manifest,
            manifest_sha256=manifest_sha,
            source_manifest_sha256=bundle.manifest_sha256,
            source_bundle_content_sha256=bundle.content_sha256,
            redaction_summary={"redacted_fields": 0, "total_fields": 12},
            receipt=receipt,
            receipt_sha256=receipt_sha,
        )
        self._report("EvidenceExport", "[Seed] Evidence export (ready)", True)

    def _seed_service_catalog(self, *, admin):
        from apps.auditor.models import ServiceCatalogEntry

        entries = [
            {
                "service_key": "api-service",
                "name": "API Service",
                "description": "Core REST API handling authentication, billing, and data access.",
                "owner_team": "Platform Engineering",
                "business_owner": "Ada Admin",
                "criticality": "critical",
                "environment": "production",
                "target_patterns": ["api-service", "api-service-*"],
                "metadata": {"tier": "1", "region": "us-east-1"},
            },
            {
                "service_key": "payments-service",
                "name": "Payments Service",
                "description": "PCI-compliant payment processing service.",
                "owner_team": "Payments Team",
                "business_owner": "Ada Admin",
                "criticality": "critical",
                "environment": "production",
                "target_patterns": ["payments-service"],
                "metadata": {"tier": "1", "compliance": "pci-dss"},
            },
            {
                "service_key": "auth-service",
                "name": "Auth Service",
                "description": "Authentication and authorization service (OAuth2/OIDC).",
                "owner_team": "Security Team",
                "business_owner": "Ada Admin",
                "criticality": "critical",
                "environment": "production",
                "target_patterns": ["auth-service"],
                "metadata": {"tier": "1"},
            },
        ]
        for e in entries:
            _, created = ServiceCatalogEntry.objects.get_or_create(
                organization=self._org,
                service_key=e["service_key"],
                defaults={**e, "created_by": admin, "updated_by": admin},
            )
            self._report("ServiceCatalogEntry", e["service_key"], created)

    def _seed_control_mapping(self, *, admin):
        from apps.auditor.models import ControlMappingProfile

        profile, created = ControlMappingProfile.objects.get_or_create(
            organization=self._org,
            key="soc2-change-management",
            version=1,
            defaults={
                "name": "SOC 2 Change Management Controls",
                "standard": "soc2",
                "description": "SOC 2 Type II controls covering change management and deployment.",
                "is_active": True,
                "mapping_rules": [
                    {
                        "control_id": "CC8.1",
                        "title": "Change management process",
                        "evidence_sections": ["change_snapshot", "approval", "closure"],
                    },
                    {
                        "control_id": "CC6.8",
                        "title": "Unauthorized or malicious code protection",
                        "evidence_sections": ["change_snapshot", "verification_result"],
                    },
                    {
                        "control_id": "CC7.2",
                        "title": "System monitoring",
                        "evidence_sections": ["audit_event", "verification_result"],
                    },
                ],
                "created_by": admin,
                "updated_by": admin,
            },
        )
        self._control_profile = profile
        self._report("ControlMappingProfile", "soc2-change-management", created)

        # Create control coverage on the sealed bundle
        if not created or not hasattr(self, "_sealed_bundle"):
            return
        self._seed_control_coverage(admin=admin)

    def _seed_control_coverage(self, *, admin):
        from apps.auditor.models import ChangeControlCoverage

        closed_change_tuple = self._changes.get("closed")
        if closed_change_tuple is None:
            return
        change = closed_change_tuple[0] if isinstance(closed_change_tuple, tuple) else closed_change_tuple
        bundle = getattr(self, "_sealed_bundle", None)
        profile = getattr(self, "_control_profile", None)
        if bundle is None or profile is None:
            return

        controls = [
            {
                "control_id": "CC8.1",
                "control_title": "Change management process",
                "coverage_status": "covered",
                "matched_sections": ["change_snapshot", "approval", "closure"],
                "missing_sections": [],
                "evidence_paths": ["change/snapshot.json", "change/closure.json"],
            },
            {
                "control_id": "CC6.8",
                "control_title": "Unauthorized or malicious code protection",
                "coverage_status": "partially_covered",
                "matched_sections": ["change_snapshot"],
                "missing_sections": ["artifact"],
                "evidence_paths": ["change/snapshot.json"],
            },
            {
                "control_id": "CC7.2",
                "control_title": "System monitoring",
                "coverage_status": "covered",
                "matched_sections": ["audit_event", "verification_result"],
                "missing_sections": [],
                "evidence_paths": ["verification/health-check.json"],
            },
        ]

        for ctrl in controls:
            fingerprint_data = f"{bundle.id}:{profile.id}:{ctrl['control_id']}:{ctrl['coverage_status']}"
            fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()
            ChangeControlCoverage.objects.get_or_create(
                evidence_bundle=bundle,
                mapping_profile=profile,
                control_id=ctrl["control_id"],
                defaults={
                    "organization": self._org,
                    "change_record": change,
                    "standard": "soc2",
                    "control_title": ctrl["control_title"],
                    "coverage_status": ctrl["coverage_status"],
                    "matched_sections": ctrl["matched_sections"],
                    "missing_sections": ctrl["missing_sections"],
                    "evidence_paths": ctrl["evidence_paths"],
                    "coverage_fingerprint_sha256": fingerprint,
                    "computed_by": admin,
                },
            )
        self._report("ChangeControlCoverage", "soc2 controls (3)", True)

    def _seed_external_references(self, *, admin):
        from apps.auditor.models import ExternalChangeReference

        closed_change_tuple = self._changes.get("closed")
        if closed_change_tuple is None:
            return
        change = closed_change_tuple[0] if isinstance(closed_change_tuple, tuple) else closed_change_tuple

        refs = [
            {
                "system": "servicenow",
                "reference_type": "ticket",
                "external_id": "CHG0012345",
                "external_key": "CHG0012345",
                "display_label": "ServiceNow CHG0012345 — Q1 Payments Service Upgrade",
                "external_url": "https://acme.service-now.com/nav_to.do?uri=change_request.do?sys_id=CHG0012345",
                "snapshot": {
                    "number": "CHG0012345",
                    "state": "closed",
                    "approval": "approved",
                    "category": "software",
                    "priority": "3-Moderate",
                    "assigned_to": "Oscar Operator",
                    "close_code": "successful",
                },
                "notes": "ServiceNow change ticket cross-referencing this deployment.",
            },
            {
                "system": "jira",
                "reference_type": "ticket",
                "external_id": "PLAT-4821",
                "external_key": "PLAT-4821",
                "display_label": "Jira PLAT-4821 — Payments v4.1.0 Release",
                "external_url": "https://acme.atlassian.net/browse/PLAT-4821",
                "snapshot": {
                    "key": "PLAT-4821",
                    "status": "Done",
                    "issue_type": "Task",
                    "priority": "Medium",
                    "reporter": "Oscar Operator",
                    "assignee": "Ada Admin",
                },
                "notes": "Jira tracking ticket for this release.",
            },
        ]

        for r in refs:
            ExternalChangeReference.objects.get_or_create(
                organization=self._org,
                change_record=change,
                system=r["system"],
                reference_type=r["reference_type"],
                external_id=r["external_id"],
                defaults={
                    "external_key": r["external_key"],
                    "display_label": r["display_label"],
                    "external_url": r["external_url"],
                    "snapshot": r["snapshot"],
                    "notes": r["notes"],
                    "linked_by": admin,
                },
            )
            self._report("ExternalChangeReference", r["display_label"], True)

    def _seed_auditor_grants(self, *, admin):
        from django.contrib.auth import get_user_model
        from apps.auditor.models import AuditorAccessGrant

        User = get_user_model()
        viewer = User.objects.filter(email="viewer@acme.test").first()
        operator = User.objects.filter(email="operator@acme.test").first()

        now = timezone.now()
        grants = [
            {
                "user": viewer,
                "status": "active",
                "scope": {"all": True},
                "reason": "Quarterly compliance audit — full read access for Q1 review.",
                "starts_at": now - timedelta(days=7),
                "expires_at": now + timedelta(days=23),
                "_label": "viewer@acme.test — active full-scope grant",
            },
            {
                "user": operator,
                "status": "active",
                "scope": {"statuses": ["closed", "verified"], "risk_levels": ["high", "critical"]},
                "reason": "Scoped access for post-release review of high-risk changes.",
                "starts_at": now - timedelta(days=1),
                "expires_at": now + timedelta(days=6),
                "_label": "operator@acme.test — scoped active grant",
            },
        ]

        for g in grants:
            if g["user"] is None:
                continue
            label = g.pop("_label")
            existing = AuditorAccessGrant.objects.filter(
                organization=self._org,
                user=g["user"],
                status=g["status"],
            ).first()
            if existing:
                self._report("AuditorAccessGrant", label, False)
                continue
            AuditorAccessGrant.objects.create(
                organization=self._org,
                created_by=admin,
                **g,
            )
            self._report("AuditorAccessGrant", label, True)

    def _seed_completed_retro_review(self, *, admin):
        """Seed a submitted retro review (on the emergency change's exception)."""
        import json
        from apps.changes.models import (
            BreakglassSession,
            ChangeException,
            ChangeRecord,
            RetroReview,
        )

        emergency_tuple = self._changes.get("emergency")
        if emergency_tuple is None:
            return
        emerg_change = (
            emergency_tuple[0]
            if isinstance(emergency_tuple, tuple)
            else emergency_tuple
        )

        now = timezone.now()

        # Seed an additional emergency change (already closed) with a submitted retro review
        emerg_profile = self._profiles.get("emergency-remediation")
        workflow = self._workflows.get("incident")
        if emerg_profile is None or workflow is None:
            return

        title = "[Seed] Emergency Remediation — Closed with Retro Review"
        from apps.changes.models import ChangeRecord as CR

        existing = CR.objects.filter(organization=self._org, title=title).first()
        if existing is None:
            from apps.audit.services import AuditActor
            from apps.audit.models import AuditEvent
            from apps.changes.services import create_change_record, sha256_canonical_json, build_request_snapshot

            actor = AuditActor(
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(admin.id),
                actor_label=admin.email,
            )
            past_change = create_change_record(
                organization=self._org,
                operation_profile_key=emerg_profile.key,
                workflow_id=str(workflow.id),
                title=title,
                summary="Disk space emergency on database host — log rotation and cleanup.",
                justification="Automated alert: disk > 95%. Cleared 40GB of old logs.",
                requested_inputs={"target": "db-primary", "action": "log-rotation"},
                targets=[
                    {
                        "target_type": "service",
                        "target_identifier": "db-primary",
                        "environment": "production",
                        "display_name": "DB Primary Host",
                    }
                ],
                actor=actor,
                is_emergency=True,
                emergency_reason="Disk usage at 97% on db-primary; service degradation imminent.",
            )
            past_at = now - timedelta(days=5)
            target_objs = list(past_change.targets.order_by("position"))
            snapshot = build_request_snapshot(
                past_change, target_objs, submitted_at=past_at,
                profile=emerg_profile, workflow=workflow,
            )
            CR.objects.filter(pk=past_change.pk).update(
                status="closed",
                submitted_at=past_at,
                approved_at=past_at,
                dispatchable_at=past_at + timedelta(minutes=2),
                running_at=past_at + timedelta(minutes=5),
                verified_at=past_at + timedelta(minutes=20),
                closed_at=past_at + timedelta(minutes=25),
                requested_inputs_sha256=sha256_canonical_json(past_change.requested_inputs),
                request_snapshot=snapshot,
                request_snapshot_sha256=sha256_canonical_json(snapshot),
                operation_profile_key_snapshot=emerg_profile.key,
                workflow_version_snapshot=workflow.version,
                workflow_definition_sha256=sha256_canonical_json(workflow.definition or {}),
                submitted_by_id=str(admin.id),
                retro_review_required=True,
                retro_review_due_at=past_at + timedelta(hours=12),
            )
            past_change.refresh_from_db()
            existing = past_change

        # Closed breakglass on this past change
        scope_json = {"service_keys": ["db-primary"]}
        scope_sha = hashlib.sha256(
            json.dumps(scope_json, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        past_at = now - timedelta(days=5)

        bgl, bgl_created = BreakglassSession.objects.get_or_create(
            change_record=existing,
            defaults={
                "organization": self._org,
                "status": BreakglassSession.Status.ENDED,
                "scope_json": scope_json,
                "scope_sha256": scope_sha,
                "reason": "Disk emergency on db-primary — immediate log cleanup.",
                "activated_by": admin,
                "started_at": past_at,
                "expires_at": past_at + timedelta(hours=1),
                "ended_at": past_at + timedelta(minutes=18),
                "ended_by": admin,
                "end_reason": "resolved",
                "review_due_at": past_at + timedelta(hours=12),
                "review_status": BreakglassSession.ReviewStatus.ACCEPTED,
            },
        )
        self._report("BreakglassSession", "[Seed] Ended breakglass (past emergency)", bgl_created)

        # Submitted retro review
        retro, retro_created = RetroReview.objects.get_or_create(
            change_record=existing,
            breakglass_session=bgl,
            defaults={
                "organization": self._org,
                "status": RetroReview.Status.SUBMITTED,
                "disposition": RetroReview.Disposition.ACCEPTED,
                "reviewed_by": admin,
                "reviewed_at": past_at + timedelta(hours=8),
                "due_at": past_at + timedelta(hours=12),
                "summary": (
                    "Emergency log rotation was necessary and appropriate. "
                    "Disk utilization returned to normal. "
                    "Root cause: log rotation cron disabled after last migration. "
                    "Remediation: re-enabled cron and added alerting at 80% threshold."
                ),
                "remediation_required": True,
                "remediation_reference": "PLAT-5001",
            },
        )
        self._report("RetroReview", "[Seed] Submitted retro review", retro_created)

    # ------------------------------------------------------------------

    def _report(self, model, name, created):
        verb = "Created" if created else "Already exists"
        self.stdout.write(f"  [{verb}] {model}: {name}")
