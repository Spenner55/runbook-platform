import pytest
from django.db import IntegrityError

from apps.organizations.models import Organization
from apps.policies.models import Policy, PolicyRule


@pytest.mark.django_db
class TestPolicyModel:
    def setup_method(self):
        self.org = Organization.objects.create(name="Test Org", slug="test-org")

    def test_create_policy(self):
        policy = Policy.objects.create(
            organization=self.org,
            name="Safety Policy",
            description="Blocks risky steps.",
            is_active=True,
        )
        assert policy.id is not None
        assert policy.is_active is True
        assert str(policy) == "Safety Policy (active)"

    def test_inactive_policy_remains_queryable(self):
        policy = Policy.objects.create(
            organization=self.org, name="Old Policy", is_active=False
        )
        assert Policy.objects.filter(id=policy.id, is_active=False).exists()

    def test_cascade_delete_with_org(self):
        Policy.objects.create(organization=self.org, name="Will Be Deleted")
        self.org.delete()
        assert Policy.objects.count() == 0


@pytest.mark.django_db
class TestPolicyRuleModel:
    def setup_method(self):
        self.org = Organization.objects.create(name="Org", slug="org")
        self.policy = Policy.objects.create(organization=self.org, name="Policy")

    def test_create_rule(self):
        rule = PolicyRule.objects.create(
            policy=self.policy,
            name="High risk rule",
            priority=10,
            condition_type="risk_level",
            condition_params={"operator": "in", "values": ["high", "critical"]},
            outcome="approval_required",
        )
        assert rule.id is not None
        assert rule.is_active is True

    def test_unique_priority_within_policy(self):
        PolicyRule.objects.create(
            policy=self.policy,
            name="Rule A",
            priority=10,
            condition_type="risk_level",
            condition_params={},
            outcome="block",
        )
        with pytest.raises(IntegrityError):
            PolicyRule.objects.create(
                policy=self.policy,
                name="Rule B",
                priority=10,
                condition_type="step_type",
                condition_params={},
                outcome="auto_approve",
            )

    def test_unique_name_within_policy(self):
        PolicyRule.objects.create(
            policy=self.policy,
            name="Duplicate",
            priority=10,
            condition_type="risk_level",
            condition_params={},
            outcome="block",
        )
        with pytest.raises(IntegrityError):
            PolicyRule.objects.create(
                policy=self.policy,
                name="Duplicate",
                priority=20,
                condition_type="risk_level",
                condition_params={},
                outcome="block",
            )

    def test_same_priority_allowed_across_policies(self):
        other_policy = Policy.objects.create(organization=self.org, name="Other Policy")
        PolicyRule.objects.create(
            policy=self.policy,
            name="Rule A",
            priority=10,
            condition_type="risk_level",
            condition_params={},
            outcome="block",
        )
        # Same priority is fine on a different policy
        rule = PolicyRule.objects.create(
            policy=other_policy,
            name="Rule B",
            priority=10,
            condition_type="risk_level",
            condition_params={},
            outcome="block",
        )
        assert rule.id is not None

    def test_inactive_rule_remains_queryable(self):
        rule = PolicyRule.objects.create(
            policy=self.policy,
            name="Disabled",
            priority=5,
            condition_type="risk_level",
            condition_params={},
            outcome="block",
            is_active=False,
        )
        assert PolicyRule.objects.filter(id=rule.id, is_active=False).exists()
