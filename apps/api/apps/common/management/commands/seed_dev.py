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

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev refuses to run when DEBUG=False. "
                "This command is for local development only."
            )

        self._seed_users()
        self._seed_org()
        self._seed_runbooks()
        self._seed_workflows()
        self._seed_executions()
        self._seed_policy()
        self._seed_integration()

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
        self.stdout.write(
            "\nLogin credentials:\n"
            "  admin@acme.test    / Admin1234!   (owner)\n"
            "  operator@acme.test / Operator1!   (operator)\n"
            "  viewer@acme.test   / Viewer1234!  (viewer)\n"
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
        self._create_steps(ex, step_data)
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

    def _create_steps(self, execution, step_data, fail_message=""):
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

    def _report(self, model, name, created):
        verb = "Created" if created else "Already exists"
        self.stdout.write(f"  [{verb}] {model}: {name}")
