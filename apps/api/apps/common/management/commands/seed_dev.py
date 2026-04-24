"""
Management command: seed_dev

Populates the local development database with a minimal, canonical dataset.
Safe to run multiple times (idempotent via get_or_create).
Aborts if DEBUG is False.

Usage:
    python manage.py seed_dev
    python manage.py seed_dev --with-execution
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Seed local development database with canonical dev data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-execution",
            action="store_true",
            default=False,
            help="Also create a seed execution record.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_dev refuses to run when DEBUG=False. "
                "This command is for local development only."
            )

        from apps.executions.models import Execution
        from apps.organizations.models import Organization
        from apps.runbooks.models import Runbook
        from apps.workflows.models import Workflow

        org, org_created = Organization.objects.get_or_create(
            slug="acme-platform-eng",
            defaults={"name": "Acme Platform Engineering"},
        )
        self._report("Organization", org.name, org_created)

        runbook, rb_created = Runbook.objects.get_or_create(
            organization=org,
            slug="deploy-production",
            defaults={
                "title": "Deploy to Production",
                "raw_content": (
                    "Standard procedure for deploying a new release "
                    "to the production environment."
                ),
            },
        )
        self._report("Runbook", runbook.title, rb_created)

        workflow_definition = {
            "name": "Deploy to Production",
            "steps": [
                {
                    "id": "check-health",
                    "name": "Pre-deploy health check",
                    "type": "shell",
                    "risk": "low",
                    "command": "curl -sf http://internal/health || exit 1",
                    "requiresApproval": False,
                },
                {
                    "id": "deploy",
                    "name": "Run deployment script",
                    "type": "shell",
                    "risk": "high",
                    "command": "./scripts/deploy.sh --env production",
                    "requiresApproval": True,
                },
                {
                    "id": "smoke-test",
                    "name": "Post-deploy smoke test",
                    "type": "shell",
                    "risk": "low",
                    "command": "pytest tests/smoke/ -q",
                    "requiresApproval": False,
                },
            ],
        }
        workflow, wf_created = Workflow.objects.get_or_create(
            runbook=runbook,
            version=1,
            defaults={
                "organization": org,
                "name": "deploy-production-v1",
                "status": Workflow.Status.PUBLISHED,
                "definition": workflow_definition,
            },
        )
        self._report("Workflow", workflow.name, wf_created)

        if options["with_execution"]:
            execution, ex_created = Execution.objects.get_or_create(
                workflow=workflow,
                workflow_version=workflow.version,
                defaults={
                    "organization": org,
                    "workflow_snapshot": workflow_definition,
                    "status": Execution.Status.SUCCEEDED,
                },
            )
            self._report("Execution", str(execution.id), ex_created)

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))

    def _report(self, model, name, created):
        verb = "Created" if created else "Already exists"
        self.stdout.write(f"  [{verb}] {model}: {name}")
