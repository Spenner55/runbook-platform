from django.db.models import Q

from apps.approvals.models import ApprovalRequest
from apps.artifacts.models import Artifact
from apps.audit.models import AuditEvent
from apps.changes.models import (
    BreakglassSession,
    ChangeClosure,
    ChangeException,
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    RetroReview,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
)
from apps.evidence.models import (
    EvidenceBundle,
    EvidenceExport,
    EvidenceRetentionPolicy,
    LegalHold,
)
from apps.policies.models import PolicyEvaluation


def evidence_bundles_for_organization(organization):
    return EvidenceBundle.objects.filter(organization=organization)


def evidence_exports_for_organization(organization):
    return EvidenceExport.objects.filter(organization=organization)


def legal_holds_for_organization(organization):
    return LegalHold.objects.filter(organization=organization)


def active_legal_holds_for_change(change_record):
    return LegalHold.objects.filter(
        change_record=change_record,
        status=LegalHold.Status.ACTIVE,
    ).order_by("placed_at", "id")


def default_retention_policy_for_organization(organization):
    return EvidenceRetentionPolicy.objects.filter(
        organization=organization,
        is_default=True,
        is_active=True,
    ).first()


def closed_change_records_for_organization(organization):
    return ChangeRecord.objects.filter(
        organization=organization,
        status=ChangeRecord.Status.CLOSED,
    )


def change_targets_for_bundle(change_record):
    return ChangeTarget.objects.filter(
        organization=change_record.organization,
        change_record=change_record,
    ).order_by("position", "id")


def execution_binding_for_bundle(change_record):
    return (
        ChangeExecutionBinding.objects.select_related("execution")
        .filter(organization=change_record.organization, change_record=change_record)
        .first()
    )


def approval_requests_for_bundle(change_record, *, exceptions=None, execution=None):
    query = Q(subject_type=ApprovalRequest.SubjectType.CHANGE_RECORD)
    query &= Q(subject_id=change_record.id)
    if change_record.approval_request_id:
        query |= Q(id=change_record.approval_request_id)
    if execution is not None:
        query |= Q(execution=execution)
    exception_ids = [exc.id for exc in exceptions or []]
    if exception_ids:
        query |= Q(
            subject_type=ApprovalRequest.SubjectType.CHANGE_EXCEPTION,
            subject_id__in=exception_ids,
        )
        query |= Q(change_exceptions__id__in=exception_ids)

    return (
        ApprovalRequest.objects.select_related("decision")
        .filter(organization=change_record.organization)
        .filter(query)
        .distinct()
        .order_by("requested_at", "created_at", "id")
    )


def policy_evaluations_for_bundle(change_record, *, exceptions=None, execution=None):
    query = Q()
    if change_record.policy_evaluation_id:
        query |= Q(id=change_record.policy_evaluation_id)
    if execution is not None:
        query |= Q(execution=execution)
    exception_evaluation_ids = [
        exc.policy_evaluation_id
        for exc in exceptions or []
        if exc.policy_evaluation_id is not None
    ]
    if exception_evaluation_ids:
        query |= Q(id__in=exception_evaluation_ids)

    if not query:
        return PolicyEvaluation.objects.none()

    return (
        PolicyEvaluation.objects.select_related("policy", "rule", "execution", "step")
        .filter(organization=change_record.organization)
        .filter(query)
        .distinct()
        .order_by("evaluated_at", "created_at", "id")
    )


def verification_plan_for_bundle(change_record):
    return (
        VerificationPlan.objects.filter(
            organization=change_record.organization,
            change_record=change_record,
        )
        .order_by("created_at", "id")
        .first()
    )


def verification_checks_for_bundle(change_record):
    return VerificationCheck.objects.filter(
        organization=change_record.organization,
        change_record=change_record,
    ).order_by("position", "created_at", "id")


def verification_results_for_bundle(change_record):
    return (
        VerificationResult.objects.select_related("verification_check", "artifact")
        .filter(organization=change_record.organization, change_record=change_record)
        .order_by("submitted_at", "created_at", "id")
    )


def closure_for_bundle(change_record):
    return (
        ChangeClosure.objects.filter(
            organization=change_record.organization,
            change_record=change_record,
        )
        .order_by("closed_at", "created_at", "id")
        .first()
    )


def exceptions_for_bundle(change_record):
    return (
        ChangeException.objects.select_related(
            "approval_request",
            "policy_evaluation",
            "verification_check",
            "artifact",
        )
        .filter(organization=change_record.organization, change_record=change_record)
        .order_by("requested_at", "created_at", "id")
    )


def breakglass_sessions_for_bundle(change_record):
    return BreakglassSession.objects.filter(
        organization=change_record.organization,
        change_record=change_record,
    ).order_by("started_at", "created_at", "id")


def retro_reviews_for_bundle(change_record):
    return RetroReview.objects.filter(
        organization=change_record.organization,
        change_record=change_record,
    ).order_by("due_at", "created_at", "id")


def artifacts_for_bundle(
    change_record,
    *,
    execution=None,
    verification_results=None,
    exceptions=None,
):
    query = Q()
    if execution is not None:
        query |= Q(execution=execution)

    artifact_ids = [
        result.artifact_id
        for result in verification_results or []
        if result.artifact_id is not None
    ]
    artifact_ids.extend(
        exc.artifact_id for exc in exceptions or [] if exc.artifact_id is not None
    )
    if artifact_ids:
        query |= Q(id__in=artifact_ids)

    if not query:
        return Artifact.objects.none()

    return (
        Artifact.objects.select_related("execution", "step")
        .filter(query)
        .distinct()
        .order_by("uploaded_at", "created_at", "id")
    )


def audit_events_for_bundle(change_record, *, related_object_ids, source_cutoff_at):
    return (
        AuditEvent.objects.filter(
            organization_id=change_record.organization_id,
            object_id__in=list(related_object_ids),
            occurred_at__lte=source_cutoff_at,
        )
        .exclude(
            object_type__in=[
                AuditEvent.ObjectType.EVIDENCE_BUNDLE,
                AuditEvent.ObjectType.EVIDENCE_BUNDLE_ITEM,
                AuditEvent.ObjectType.EVIDENCE_EXPORT,
            ]
        )
        .order_by("occurred_at", "created_at", "id")
    )
