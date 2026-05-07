"""Read-only selectors for the changes app."""

from apps.changes.models import (
    ChangeRecord,
    DispatchEligibilityCheck,
    FreezeRule,
    OperationProfile,
    RetroReview,
)


def get_active_profiles_for_org(*, organization):
    return (
        OperationProfile.objects.filter(organization=organization, is_active=True)
        .prefetch_related("allowed_workflows")
        .order_by("name")
    )


def get_change_record(*, change_id, organization):
    return (
        ChangeRecord.objects.filter(pk=change_id, organization=organization)
        .select_related(
            "operation_profile",
            "workflow",
            "requested_by",
            "submitted_by",
            "approval_request",
            "policy_evaluation",
        )
        .prefetch_related("targets")
        .first()
    )


def list_change_records_for_org(*, organization):
    return (
        ChangeRecord.objects.filter(organization=organization)
        .select_related(
            "operation_profile",
            "workflow",
            "requested_by",
            "submitted_by",
            "approval_request",
            "policy_evaluation",
            "execution_binding",
            "execution_binding__execution",
            "window",
        )
        .prefetch_related("targets")
    )


def get_change_record_with_binding(*, change_id, organization):
    return (
        ChangeRecord.objects.filter(pk=change_id, organization=organization)
        .select_related(
            "operation_profile",
            "workflow",
            "requested_by",
            "submitted_by",
            "approval_request",
            "policy_evaluation",
            "execution_binding",
            "execution_binding__execution",
            "window",
        )
        .prefetch_related("targets")
        .first()
    )


def list_freeze_rules_for_org(*, organization):
    return (
        FreezeRule.objects.filter(organization=organization)
        .select_related("created_by", "updated_by")
        .order_by("-starts_at")
    )


def get_freeze_rule(*, rule_id, organization):
    return (
        FreezeRule.objects.filter(pk=rule_id, organization=organization)
        .select_related("created_by", "updated_by")
        .first()
    )


def get_latest_dispatch_preflight(*, change_id, organization):
    return (
        DispatchEligibilityCheck.objects.filter(
            change_record_id=change_id,
            organization=organization,
        )
        .order_by("-checked_at")
        .first()
    )


def list_dispatch_preflights_for_change(*, change_id, organization):
    return DispatchEligibilityCheck.objects.filter(
        change_record_id=change_id,
        organization=organization,
    ).order_by("-checked_at")


def list_retro_reviews_for_change(*, change_id, organization):
    return (
        RetroReview.objects.filter(
            change_record_id=change_id, organization=organization
        )
        .select_related("breakglass_session", "change_exception", "reviewed_by")
        .order_by("-due_at")
    )


def list_retro_review_inbox(*, organization):
    """Return pending retro-reviews org-wide, ordered by due_at ascending."""
    return (
        RetroReview.objects.filter(
            organization=organization, status=RetroReview.Status.PENDING
        )
        .select_related("change_record", "breakglass_session", "change_exception")
        .order_by("due_at")
    )


def get_retro_review(*, review_id, change_id, organization):
    return (
        RetroReview.objects.filter(
            pk=review_id, change_record_id=change_id, organization=organization
        )
        .select_related("breakglass_session", "change_exception", "reviewed_by")
        .first()
    )
