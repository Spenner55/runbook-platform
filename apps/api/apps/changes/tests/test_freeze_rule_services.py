"""FreezeRule service and API tests."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status as http_status

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import selectors, services
from apps.changes.models import FreezeRule
from apps.organizations.models import Membership, MembershipRole


def _now():
    return timezone.now()


def _actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _freeze_kwargs(org, **overrides):
    base = {
        "organization": org,
        "name": "Holiday Freeze",
        "behavior": FreezeRule.Behavior.BLOCK,
        "starts_at": _now() + timedelta(days=1),
        "ends_at": _now() + timedelta(days=3),
        "scope_type": FreezeRule.ScopeType.ALL_PRODUCTION,
        "requires_exception_reference": False,
        "actor": _actor(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# create_freeze_rule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateFreezeRule:
    def test_creates_active_block_rule(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        assert rule.pk is not None
        assert rule.is_active is True
        assert rule.behavior == FreezeRule.Behavior.BLOCK
        assert rule.organization == org

    def test_creates_allow_with_exception_rule(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
                requires_exception_reference=True,
            )
        )
        assert rule.behavior == FreezeRule.Behavior.ALLOW_WITH_EXCEPTION
        assert rule.requires_exception_reference is True

    def test_target_type_scope(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_TYPE,
                target_type="server",
            )
        )
        assert rule.scope_type == FreezeRule.ScopeType.TARGET_TYPE
        assert rule.target_type == "server"

    def test_target_identifier_scope_normalizes(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
                target_type="server",
                target_identifier="Prod-Server-01",
            )
        )
        assert rule.normalized_identifier == "prod-server-01"

    def test_ends_before_starts_raises(self, org):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="ends_at must be after"):
            services.create_freeze_rule(
                **_freeze_kwargs(
                    org,
                    starts_at=_now() + timedelta(hours=2),
                    ends_at=_now() + timedelta(hours=1),
                )
            )

    def test_allow_with_exception_without_ref_raises(self, org):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="requires_exception_reference"):
            services.create_freeze_rule(
                **_freeze_kwargs(
                    org,
                    behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
                    requires_exception_reference=False,
                )
            )

    def test_target_type_scope_without_target_type_raises(self, org):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="target_type is required"):
            services.create_freeze_rule(
                **_freeze_kwargs(
                    org,
                    scope_type=FreezeRule.ScopeType.TARGET_TYPE,
                    target_type="",
                )
            )

    def test_target_identifier_scope_without_identifier_raises(self, org):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(
            DomainValidationError, match="target_identifier is required"
        ):
            services.create_freeze_rule(
                **_freeze_kwargs(
                    org,
                    scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
                    target_identifier="",
                )
            )

    def test_emits_audit_event(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        event = AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.FREEZE_RULE,
            object_id=rule.id,
            event_type="freeze_rule.created",
        ).first()
        assert event is not None


# ---------------------------------------------------------------------------
# update_freeze_rule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUpdateFreezeRule:
    def test_updates_name_and_description(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        updated = services.update_freeze_rule(
            rule=rule, actor=_actor(), name="Updated Name", description="New desc"
        )
        assert updated.name == "Updated Name"
        assert updated.description == "New desc"

    def test_updates_time_range(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        new_start = _now() + timedelta(days=5)
        new_end = _now() + timedelta(days=7)
        updated = services.update_freeze_rule(
            rule=rule, actor=_actor(), starts_at=new_start, ends_at=new_end
        )
        assert updated.starts_at == new_start
        assert updated.ends_at == new_end

    def test_inactive_rule_raises(self, org):
        from apps.common.exceptions import DomainValidationError

        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        services.deactivate_freeze_rule(rule=rule, actor=_actor())
        with pytest.raises(DomainValidationError, match="inactive"):
            services.update_freeze_rule(rule=rule, actor=_actor(), name="X")

    def test_invalid_time_range_raises(self, org):
        from apps.common.exceptions import DomainValidationError

        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        with pytest.raises(DomainValidationError, match="ends_at must be after"):
            services.update_freeze_rule(
                rule=rule,
                actor=_actor(),
                starts_at=_now() + timedelta(days=5),
                ends_at=_now() + timedelta(days=4),
            )

    def test_emits_audit_event(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        services.update_freeze_rule(rule=rule, actor=_actor(), name="New Name")
        event = AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.FREEZE_RULE,
            object_id=rule.id,
            event_type="freeze_rule.updated",
        ).first()
        assert event is not None

    def test_normalizes_identifier_on_update(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
                target_type="server",
                target_identifier="prod-01",
            )
        )
        updated = services.update_freeze_rule(
            rule=rule, actor=_actor(), target_identifier="PROD-02"
        )
        assert updated.normalized_identifier == "prod-02"


# ---------------------------------------------------------------------------
# deactivate_freeze_rule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeactivateFreezeRule:
    def test_deactivates_active_rule(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        result = services.deactivate_freeze_rule(rule=rule, actor=_actor())
        assert result.is_active is False

    def test_idempotent_on_already_inactive(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        services.deactivate_freeze_rule(rule=rule, actor=_actor())
        result = services.deactivate_freeze_rule(rule=rule, actor=_actor())
        assert result.is_active is False

    def test_emits_audit_event(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        services.deactivate_freeze_rule(rule=rule, actor=_actor())
        event = AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.FREEZE_RULE,
            object_id=rule.id,
            event_type="freeze_rule.deactivated",
        ).first()
        assert event is not None

    def test_does_not_emit_audit_when_already_inactive(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        services.deactivate_freeze_rule(rule=rule, actor=_actor())
        count_before = AuditEvent.objects.filter(
            event_type="freeze_rule.deactivated", object_id=rule.id
        ).count()
        services.deactivate_freeze_rule(rule=rule, actor=_actor())
        count_after = AuditEvent.objects.filter(
            event_type="freeze_rule.deactivated", object_id=rule.id
        ).count()
        assert count_after == count_before


# ---------------------------------------------------------------------------
# get_active_matching_freeze_rules
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetActiveMatchingFreezeRules:
    def test_matches_all_production_scope(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=org,
                target_type="server",
                target_identifier="prod-01",
                at=_now() + timedelta(days=2),
            )
        )
        assert rule in matches

    def test_matches_target_type_scope(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_TYPE,
                target_type="server",
            )
        )
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=org,
                target_type="server",
                at=_now() + timedelta(days=2),
            )
        )
        assert rule in matches

    def test_does_not_match_wrong_target_type(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_TYPE,
                target_type="database",
            )
        )
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=org,
                target_type="server",
                at=_now() + timedelta(days=2),
            )
        )
        assert rule not in matches

    def test_matches_target_identifier_scope(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
                target_type="server",
                target_identifier="prod-01",
            )
        )
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=org,
                target_identifier="PROD-01",
                at=_now() + timedelta(days=2),
            )
        )
        assert rule in matches

    def test_inactive_rule_excluded(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        services.deactivate_freeze_rule(rule=rule, actor=_actor())
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=org,
                at=_now() + timedelta(days=2),
            )
        )
        assert rule not in matches

    def test_expired_rule_excluded(self, org):
        rule = services.create_freeze_rule(
            **_freeze_kwargs(
                org,
                starts_at=_now() - timedelta(days=5),
                ends_at=_now() - timedelta(days=1),
            )
        )
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=org,
                at=_now(),
            )
        )
        assert rule not in matches

    def test_different_org_excluded(self, org, org_factory):
        other_org = org_factory("other")
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        matches = list(
            services.get_active_matching_freeze_rules(
                organization=other_org,
                at=_now() + timedelta(days=2),
            )
        )
        assert rule not in matches


# ---------------------------------------------------------------------------
# selectors
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFreezeRuleSelectors:
    def test_list_all_rules_for_org(self, org):
        r1 = services.create_freeze_rule(**_freeze_kwargs(org, name="Rule A"))
        r2 = services.create_freeze_rule(**_freeze_kwargs(org, name="Rule B"))
        rules = list(selectors.list_freeze_rules_for_org(organization=org))
        assert r1 in rules
        assert r2 in rules

    def test_list_excludes_other_org(self, org, org_factory):
        other = org_factory("other2")
        rule = services.create_freeze_rule(**_freeze_kwargs(other))
        rules = list(selectors.list_freeze_rules_for_org(organization=org))
        assert rule not in rules

    def test_get_freeze_rule(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        fetched = selectors.get_freeze_rule(rule_id=rule.id, organization=org)
        assert fetched.id == rule.id

    def test_get_freeze_rule_wrong_org_returns_none(self, org, org_factory):
        other = org_factory("other3")
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        assert selectors.get_freeze_rule(rule_id=rule.id, organization=other) is None


# ---------------------------------------------------------------------------
# API views
# ---------------------------------------------------------------------------


def _admin_client(org):
    from uuid import uuid4

    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"admin-{uuid4()}@example.com", password="pass"
    )
    Membership.objects.create(organization=org, user=user, role=MembershipRole.ADMIN)
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


def _viewer_client(org):
    from uuid import uuid4

    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=f"viewer-{uuid4()}@example.com", password="pass"
    )
    Membership.objects.create(organization=org, user=user, role=MembershipRole.VIEWER)
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


BASE_URL = "/api/v1/freeze-rules/"


@pytest.mark.django_db
class TestFreezeRuleListCreateAPI:
    def test_list_returns_rules(self, org):
        services.create_freeze_rule(**_freeze_kwargs(org, name="Rule A"))
        client = _admin_client(org)
        resp = client.get(BASE_URL)
        assert resp.status_code == http_status.HTTP_200_OK
        assert len(resp.data["results"]) == 1

    def test_viewer_can_list(self, org):
        services.create_freeze_rule(**_freeze_kwargs(org))
        client = _viewer_client(org)
        resp = client.get(BASE_URL)
        assert resp.status_code == http_status.HTTP_200_OK

    def test_create_block_rule(self, org):
        client = _admin_client(org)
        payload = {
            "name": "Holiday Freeze",
            "behavior": "block",
            "starts_at": (_now() + timedelta(days=1)).isoformat(),
            "ends_at": (_now() + timedelta(days=3)).isoformat(),
            "scope_type": "all_production",
        }
        resp = client.post(BASE_URL, data=payload, format="json")
        assert resp.status_code == http_status.HTTP_201_CREATED
        assert resp.data["behavior"] == "block"
        assert resp.data["is_active"] is True

    def test_viewer_cannot_create(self, org):
        client = _viewer_client(org)
        payload = {
            "name": "X",
            "behavior": "block",
            "starts_at": (_now() + timedelta(days=1)).isoformat(),
            "ends_at": (_now() + timedelta(days=3)).isoformat(),
            "scope_type": "all_production",
        }
        resp = client.post(BASE_URL, data=payload, format="json")
        assert resp.status_code == http_status.HTTP_403_FORBIDDEN

    def test_create_invalid_time_range_returns_400(self, org):
        client = _admin_client(org)
        payload = {
            "name": "Bad",
            "behavior": "block",
            "starts_at": (_now() + timedelta(days=3)).isoformat(),
            "ends_at": (_now() + timedelta(days=1)).isoformat(),
            "scope_type": "all_production",
        }
        resp = client.post(BASE_URL, data=payload, format="json")
        assert resp.status_code == http_status.HTTP_400_BAD_REQUEST

    def test_unauthenticated_returns_401(self):
        from rest_framework.test import APIClient

        client = APIClient()
        resp = client.get(BASE_URL)
        assert resp.status_code == http_status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestFreezeRuleDetailAPI:
    def test_get_returns_rule(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        client = _admin_client(org)
        resp = client.get(f"{BASE_URL}{rule.id}/")
        assert resp.status_code == http_status.HTTP_200_OK
        assert str(resp.data["id"]) == str(rule.id)

    def test_get_not_found_returns_404(self, org):
        import uuid

        client = _admin_client(org)
        resp = client.get(f"{BASE_URL}{uuid.uuid4()}/")
        assert resp.status_code == http_status.HTTP_404_NOT_FOUND

    def test_patch_updates_name(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        client = _admin_client(org)
        resp = client.patch(
            f"{BASE_URL}{rule.id}/", data={"name": "Updated"}, format="json"
        )
        assert resp.status_code == http_status.HTTP_200_OK
        assert resp.data["name"] == "Updated"

    def test_viewer_cannot_patch(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        client = _viewer_client(org)
        resp = client.patch(f"{BASE_URL}{rule.id}/", data={"name": "X"}, format="json")
        assert resp.status_code == http_status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestFreezeRuleDeactivateAPI:
    def test_deactivate_sets_inactive(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        client = _admin_client(org)
        resp = client.post(f"{BASE_URL}{rule.id}/deactivate/")
        assert resp.status_code == http_status.HTTP_200_OK
        assert resp.data["is_active"] is False

    def test_deactivate_not_found_returns_404(self, org):
        import uuid

        client = _admin_client(org)
        resp = client.post(f"{BASE_URL}{uuid.uuid4()}/deactivate/")
        assert resp.status_code == http_status.HTTP_404_NOT_FOUND

    def test_viewer_cannot_deactivate(self, org):
        rule = services.create_freeze_rule(**_freeze_kwargs(org))
        client = _viewer_client(org)
        resp = client.post(f"{BASE_URL}{rule.id}/deactivate/")
        assert resp.status_code == http_status.HTTP_403_FORBIDDEN
