from io import StringIO
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.common.management.commands.seed_dev import Command as SeedDevCommand
from apps.common.models import BaseModel
from apps.organizations.models import Organization
from apps.policies import services as policy_services
from apps.policies.models import Policy, PolicyRule


class BaseModelTest(TestCase):
    def test_base_model_is_abstract(self):
        self.assertTrue(BaseModel._meta.abstract)

    def test_base_model_has_expected_fields(self):
        field_names = [f.name for f in BaseModel._meta.fields]
        self.assertIn("id", field_names)
        self.assertIn("created_at", field_names)
        self.assertIn("updated_at", field_names)


def test_default_api_permission_requires_authentication():
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]


class SeedDevPolicyTest(TestCase):
    def _run_seed_policy(self, org):
        command = SeedDevCommand()
        command._org = org
        command._report = lambda *args, **kwargs: None
        command._seed_policy()

    def test_seed_policy_creates_valid_rule_conditions(self):
        org = Organization.objects.create(name="Seed Org", slug="seed-org")

        self._run_seed_policy(org)

        rules = PolicyRule.objects.filter(policy__organization=org).order_by("priority")
        self.assertEqual(
            rules[0].condition_params, {"operator": "in", "values": ["high"]}
        )
        self.assertEqual(
            rules[1].condition_params,
            {"operator": "in", "values": ["low", "medium"]},
        )
        for rule in rules:
            policy_services._validate_condition_params(
                rule.condition_type, rule.condition_params
            )

    def test_seed_policy_repairs_existing_invalid_rule_conditions(self):
        org = Organization.objects.create(name="Seed Org", slug="seed-org")
        policy = Policy.objects.create(
            organization=org,
            name="High-risk steps require approval",
            is_active=True,
        )
        PolicyRule.objects.create(
            policy=policy,
            name="High risk \u2192 approval required",
            priority=10,
            condition_type=PolicyRule.ConditionType.RISK_LEVEL,
            condition_params={"risk_levels": ["high"]},
            outcome=PolicyRule.Outcome.APPROVAL_REQUIRED,
        )
        PolicyRule.objects.create(
            policy=policy,
            name="Low/medium risk \u2192 auto approve",
            priority=20,
            condition_type=PolicyRule.ConditionType.RISK_LEVEL,
            condition_params={"risk_levels": ["low", "medium"]},
            outcome=PolicyRule.Outcome.AUTO_APPROVE,
        )

        self._run_seed_policy(org)

        repaired = {
            rule.priority: rule.condition_params
            for rule in PolicyRule.objects.filter(policy=policy)
        }
        self.assertEqual(
            repaired[10],
            {"operator": "in", "values": ["high"]},
        )
        self.assertEqual(
            repaired[20],
            {"operator": "in", "values": ["low", "medium"]},
        )


class SeedDevIdempotenceTest(TestCase):
    def _run_seed_dev(self, media_root):
        out = StringIO()
        with override_settings(DEBUG=True, ARTIFACT_MEDIA_ROOT=media_root):
            call_command("seed_dev", stdout=out)

    def test_seed_dev_reruns_and_repairs_missing_children(self):
        from apps.approvals.models import ApprovalRequest
        from apps.artifacts.models import Artifact
        from apps.executions.models import Execution

        with TemporaryDirectory() as media_root:
            self._run_seed_dev(media_root)

            succeeded = Execution.objects.get(
                workflow_snapshot__seed_dev_key="deploy-succeeded"
            )
            Artifact.objects.filter(
                execution=succeeded,
                name="smoke_test.log",
            ).delete()
            succeeded.steps.filter(step_key="smoke-test").delete()

            awaiting = Execution.objects.get(
                workflow_snapshot__seed_dev_key="incident-awaiting-approval"
            )
            ApprovalRequest.objects.filter(execution=awaiting).delete()
            awaiting.steps.filter(step_key="restart-service").delete()

            queued = Execution.objects.get(
                workflow_snapshot__seed_dev_key="deploy-queued"
            )
            queued.status = Execution.Status.SUCCEEDED
            queued.save(update_fields=["status"])

            self._run_seed_dev(media_root)
            self._run_seed_dev(media_root)

            succeeded.refresh_from_db()
            awaiting.refresh_from_db()
            queued.refresh_from_db()
            self.assertEqual(succeeded.steps.count(), 3)
            self.assertEqual(queued.status, Execution.Status.QUEUED)
            self.assertEqual(
                Artifact.objects.filter(
                    execution=succeeded,
                    name="smoke_test.log",
                ).count(),
                1,
            )
            self.assertEqual(awaiting.steps.count(), 2)
            self.assertEqual(
                ApprovalRequest.objects.filter(
                    execution=awaiting,
                    status=ApprovalRequest.Status.PENDING,
                ).count(),
                1,
            )

    def test_seed_dev_tolerates_duplicate_legacy_executions(self):
        from apps.executions.models import Execution
        from apps.organizations.models import Organization
        from apps.workflows.models import Workflow

        with TemporaryDirectory() as media_root:
            self._run_seed_dev(media_root)

            org = Organization.objects.get(slug="acme-platform-eng")
            workflow = Workflow.objects.get(name="deploy-production-v1", version=1)
            Execution.objects.create(
                organization=org,
                workflow=workflow,
                workflow_version=workflow.version,
                workflow_snapshot=workflow.definition,
                status=Execution.Status.SUCCEEDED,
            )
            Execution.objects.filter(
                organization=org,
                workflow=workflow,
                workflow_version=workflow.version,
                status=Execution.Status.SUCCEEDED,
            ).update(workflow_snapshot=workflow.definition)

            self._run_seed_dev(media_root)

            duplicates = Execution.objects.filter(
                organization=org,
                workflow=workflow,
                workflow_version=workflow.version,
                status=Execution.Status.SUCCEEDED,
            )
            self.assertEqual(duplicates.count(), 2)
            self.assertEqual(
                duplicates.filter(
                    workflow_snapshot__seed_dev_key="deploy-succeeded"
                ).count(),
                1,
            )
