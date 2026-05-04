"""Read-only selectors for the changes app."""

from apps.changes.models import ChangeRecord, OperationProfile


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
        )
        .prefetch_related("targets")
        .first()
    )
