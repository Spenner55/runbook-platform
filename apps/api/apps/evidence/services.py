import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Max
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.changes.models import (
    ChangeClosure,
    ChangeRecord,
    VerificationResult,
)
from apps.evidence import selectors
from apps.evidence.models import EvidenceBundle, EvidenceBundleItem


def assert_bundle_mutable(bundle) -> None:
    if bundle.is_sealed:
        raise ValidationError(
            "Sealed evidence bundles are immutable.",
            code="evidence_bundle_immutable",
        )


SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class _Section:
    item_type: str
    item_key: str
    canonical_path: str
    payload: dict | list
    required: bool = True
    present: bool = True
    valid: bool = True
    missing_reason: str = ""
    validation_errors: tuple[dict, ...] = ()
    source_type: str = ""
    source_id: str = ""
    source_updated_at: datetime | None = None
    source_metadata: dict | None = None


def create_evidence_bundle_for_change(
    *,
    change_record,
    created_by=None,
    actor: AuditActor | None = None,
) -> EvidenceBundle:
    """Materialize a deterministic evidence bundle projection for a closed change."""

    with transaction.atomic():
        change = (
            ChangeRecord.objects.select_for_update()
            .select_related("operation_profile", "workflow")
            .get(pk=change_record.pk)
        )
        if change.status != ChangeRecord.Status.CLOSED:
            raise ValidationError(
                "Evidence bundles can only be materialized for closed changes.",
                code="evidence_change_not_closed",
            )

        compiled_at = timezone.now()
        source_cutoff_at = compiled_at
        latest_version = (
            EvidenceBundle.objects.select_for_update()
            .filter(change_record=change)
            .aggregate(max_version=Max("version"))["max_version"]
            or 0
        )
        previous_bundle = (
            EvidenceBundle.objects.filter(change_record=change)
            .order_by("-version", "-created_at")
            .first()
        )
        bundle = EvidenceBundle.objects.create(
            organization=change.organization,
            change_record=change,
            version=latest_version + 1,
            status=EvidenceBundle.Status.COMPILING,
            completeness_status=EvidenceBundle.CompletenessStatus.INCOMPLETE,
            source_cutoff_at=source_cutoff_at,
            compiled_at=compiled_at,
            previous_bundle=previous_bundle,
            created_by=created_by,
        )

        _materialize_items(bundle=bundle, change=change)

        bundle.refresh_from_db()
        _emit_bundle_materialized(bundle=bundle, actor=actor)
        return bundle


def materialize_evidence_bundle(*args, **kwargs) -> EvidenceBundle:
    return create_evidence_bundle_for_change(*args, **kwargs)


def create_evidence_bundle(*args, **kwargs) -> EvidenceBundle:
    return create_evidence_bundle_for_change(*args, **kwargs)


def _materialize_items(*, bundle: EvidenceBundle, change: ChangeRecord) -> None:
    assert_bundle_mutable(bundle)

    targets = list(selectors.change_targets_for_bundle(change))
    verification_plan = selectors.verification_plan_for_bundle(change)
    verification_checks = list(selectors.verification_checks_for_bundle(change))
    verification_results = list(selectors.verification_results_for_bundle(change))
    closure = selectors.closure_for_bundle(change)
    exceptions = list(selectors.exceptions_for_bundle(change))
    breakglass_sessions = list(selectors.breakglass_sessions_for_bundle(change))
    retro_reviews = list(selectors.retro_reviews_for_bundle(change))
    execution_binding = selectors.execution_binding_for_bundle(change)
    execution = execution_binding.execution if execution_binding is not None else None
    execution_steps = (
        list(execution.steps.order_by("position", "created_at", "id"))
        if execution is not None
        else []
    )
    approvals = list(
        selectors.approval_requests_for_bundle(
            change,
            exceptions=exceptions,
            execution=execution,
        )
    )
    policy_evaluations = list(
        selectors.policy_evaluations_for_bundle(
            change,
            exceptions=exceptions,
            execution=execution,
        )
    )
    artifacts = list(
        selectors.artifacts_for_bundle(
            change,
            execution=execution,
            verification_results=verification_results,
            exceptions=exceptions,
        )
    )

    related_object_ids = _related_object_ids(
        change=change,
        targets=targets,
        execution_binding=execution_binding,
        execution=execution,
        execution_steps=execution_steps,
        approvals=approvals,
        policy_evaluations=policy_evaluations,
        verification_plan=verification_plan,
        verification_checks=verification_checks,
        verification_results=verification_results,
        closure=closure,
        exceptions=exceptions,
        breakglass_sessions=breakglass_sessions,
        retro_reviews=retro_reviews,
        artifacts=artifacts,
    )
    audit_events = list(
        selectors.audit_events_for_bundle(
            change,
            related_object_ids=related_object_ids,
            source_cutoff_at=bundle.source_cutoff_at,
        )
    )

    sections = [
        _change_snapshot_section(bundle, change, targets),
        _approvals_section(bundle, change, approvals),
        _policy_decisions_section(bundle, change, policy_evaluations),
        _execution_section(bundle, change, execution_binding, execution, execution_steps),
        _audit_section(bundle, change, audit_events),
        _artifacts_section(bundle, change, artifacts),
        _verification_results_section(
            bundle,
            change,
            verification_plan,
            verification_checks,
            verification_results,
        ),
        _closure_section(bundle, change, closure),
    ]
    exception_section = _exceptions_section(
        bundle,
        change,
        exceptions,
        breakglass_sessions,
        retro_reviews,
    )
    if exception_section is not None:
        sections.append(exception_section)
    external_reference_section = _external_references_section(
        bundle,
        change,
        verification_results,
        verification_checks,
        retro_reviews,
    )
    if external_reference_section is not None:
        sections.append(external_reference_section)

    position = 0
    for section in sections:
        position += 1
        _create_section_item(bundle, section, position=position)

    for event_position, event in enumerate(audit_events, start=1):
        position += 1
        _create_audit_event_item(bundle, event, position=position, event_position=event_position)

    for artifact in artifacts:
        position += 1
        _create_artifact_item(bundle, change, artifact, position=position)

    _create_missing_verification_items(
        bundle=bundle,
        verification_checks=verification_checks,
        verification_results=verification_results,
        start_position=position,
    )

    _finalize_bundle_materialization(bundle, audit_events)


def _section_payload(bundle: EvidenceBundle, change: ChangeRecord, *, items):
    return {
        "schema_version": SCHEMA_VERSION,
        "organization_id": change.organization_id,
        "change_record_id": change.id,
        "bundle_id": bundle.id,
        "bundle_version": bundle.version,
        "generated_at": bundle.compiled_at,
        "items": items,
    }


def _change_snapshot_section(bundle, change, targets):
    item = {
        "id": change.id,
        "status": change.status,
        "title": change.title,
        "summary": change.summary,
        "justification": change.justification,
        "requested_by_id": change.requested_by_id,
        "submitted_by_id": change.submitted_by_id,
        "operation_profile_id": change.operation_profile_id,
        "operation_profile_key_snapshot": change.operation_profile_key_snapshot,
        "workflow_id": change.workflow_id,
        "workflow_version_snapshot": change.workflow_version_snapshot,
        "workflow_definition_sha256": change.workflow_definition_sha256,
        "requested_inputs_sha256": change.requested_inputs_sha256,
        "request_snapshot_sha256": change.request_snapshot_sha256,
        "approval_request_id": change.approval_request_id,
        "policy_evaluation_id": change.policy_evaluation_id,
        "policy_decision_snapshot": change.policy_decision_snapshot,
        "scheduled_for": change.scheduled_for,
        "submitted_at": change.submitted_at,
        "approved_at": change.approved_at,
        "dispatchable_at": change.dispatchable_at,
        "running_at": change.running_at,
        "verification_pending_at": change.verification_pending_at,
        "verification_failed_at": change.verification_failed_at,
        "verified_at": change.verified_at,
        "closed_at": change.closed_at,
        "terminal_reason": change.terminal_reason,
        "is_emergency": change.is_emergency,
        "emergency_declared_by_id": change.emergency_declared_by_id,
        "emergency_declared_at": change.emergency_declared_at,
        "emergency_reason_sha256": _hash_text(change.emergency_reason),
        "retro_review_required": change.retro_review_required,
        "retro_review_due_at": change.retro_review_due_at,
        "retro_review_blocking_status": change.retro_review_blocking_status,
        "freeze_exception_reference": change.freeze_exception_reference,
        "freeze_exception_recorded_by_id": change.freeze_exception_recorded_by_id,
        "freeze_exception_recorded_at": change.freeze_exception_recorded_at,
        "target_count": len(targets),
        "targets": [_serialize_target(target) for target in targets],
        "created_at": change.created_at,
        "updated_at": change.updated_at,
    }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
        item_key="change_snapshot",
        canonical_path="change/change_record.json",
        payload=_section_payload(bundle, change, items=[item]),
        source_type="changes.ChangeRecord",
        source_id=str(change.id),
        source_updated_at=change.updated_at,
        source_metadata={"status": change.status, "target_count": len(targets)},
    )


def _approvals_section(bundle, change, approvals):
    items = []
    for approval in approvals:
        decision = _approval_decision_for(approval)
        items.append(
            {
                "id": approval.id,
                "subject_type": approval.subject_type,
                "subject_id": approval.subject_id,
                "execution_id": approval.execution_id,
                "step_id": approval.step_id,
                "status": approval.status,
                "requested_by_runner_id": approval.requested_by_runner_id,
                "requested_at": approval.requested_at,
                "timeout_seconds": approval.timeout_seconds,
                "expires_at": approval.expires_at,
                "resolved_at": approval.resolved_at,
                "decision": _serialize_approval_decision(decision),
                "created_at": approval.created_at,
                "updated_at": approval.updated_at,
            }
        )
    return _Section(
        item_type=EvidenceBundleItem.ItemType.APPROVAL,
        item_key="approvals",
        canonical_path="controls/approvals.json",
        payload=_section_payload(bundle, change, items=items),
        source_metadata={"approval_count": len(items)},
    )


def _policy_decisions_section(bundle, change, policy_evaluations):
    items = []
    for evaluation in policy_evaluations:
        items.append(
            {
                "id": evaluation.id,
                "execution_id": evaluation.execution_id,
                "step_id": evaluation.step_id,
                "policy_id": evaluation.policy_id,
                "rule_id": evaluation.rule_id,
                "matched": evaluation.matched,
                "outcome": evaluation.outcome,
                "effective_outcome": evaluation.effective_outcome,
                "decision_source": evaluation.decision_source,
                "condition_type": evaluation.condition_type,
                "condition_params_snapshot": evaluation.condition_params_snapshot,
                "context_snapshot": evaluation.context_snapshot,
                "reason": evaluation.reason,
                "error_code": evaluation.error_code,
                "error_message": evaluation.error_message,
                "evaluated_at": evaluation.evaluated_at,
                "created_at": evaluation.created_at,
                "updated_at": evaluation.updated_at,
            }
        )
    return _Section(
        item_type=EvidenceBundleItem.ItemType.POLICY_DECISION,
        item_key="policy_decisions",
        canonical_path="controls/policy_decisions.json",
        payload=_section_payload(bundle, change, items=items),
        source_metadata={"policy_evaluation_count": len(items)},
    )


def _execution_section(bundle, change, binding, execution, steps):
    present = execution is not None
    missing_reason = "" if present else "missing_execution"
    item = None
    if execution is not None:
        item = {
            "binding": _serialize_binding(binding),
            "execution": {
                "id": execution.id,
                "workflow_id": execution.workflow_id,
                "workflow_version": execution.workflow_version,
                "status": execution.status,
                "started_at": execution.started_at,
                "finished_at": execution.finished_at,
                "claimed_by_runner_id": execution.claimed_by_runner_id,
                "claimed_at": execution.claimed_at,
                "last_heartbeat_at": execution.last_heartbeat_at,
                "created_at": execution.created_at,
                "updated_at": execution.updated_at,
            },
            "steps": [_serialize_execution_step(step) for step in steps],
        }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXECUTION,
        item_key="execution",
        canonical_path="execution/execution.json",
        payload=_section_payload(bundle, change, items=[] if item is None else [item]),
        present=present,
        missing_reason=missing_reason,
        source_type="executions.Execution" if execution is not None else "",
        source_id=str(execution.id) if execution is not None else "",
        source_updated_at=execution.updated_at if execution is not None else None,
        source_metadata={"step_count": len(steps), "status": getattr(execution, "status", None)},
    )


def _audit_section(bundle, change, audit_events):
    events = [_serialize_audit_event(event) for event in audit_events]
    return _Section(
        item_type=EvidenceBundleItem.ItemType.AUDIT_EVENT,
        item_key="audit_trail",
        canonical_path="audit/audit_trail.ndjson",
        payload=events,
        source_metadata={"audit_event_count": len(events)},
    )


def _artifacts_section(bundle, change, artifacts):
    items = []
    invalid_errors = []
    for artifact in artifacts:
        validation_errors = _artifact_validation_errors(change, artifact)
        invalid_errors.extend(validation_errors)
        items.append(
            {
                "id": artifact.id,
                "execution_id": artifact.execution_id,
                "step_id": artifact.step_id,
                "kind": artifact.kind,
                "name": artifact.name,
                "original_name": artifact.original_name,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
                "checksum_sha256": artifact.checksum_sha256,
                "storage_key": artifact.storage_key,
                "uploaded_by_runner_id": artifact.uploaded_by_runner_id,
                "upload_status": artifact.upload_status,
                "uploaded_at": artifact.uploaded_at,
                "content_disposition": artifact.content_disposition,
                "bundle_path": _artifact_bundle_path(artifact),
                "valid": not validation_errors,
                "validation_errors": validation_errors,
            }
        )
    return _Section(
        item_type=EvidenceBundleItem.ItemType.ARTIFACT,
        item_key="artifacts_index",
        canonical_path="artifacts/index.json",
        payload=_section_payload(bundle, change, items=items),
        valid=not invalid_errors,
        validation_errors=tuple(invalid_errors),
        source_metadata={"artifact_count": len(items)},
    )


def _verification_results_section(
    bundle,
    change,
    verification_plan,
    verification_checks,
    verification_results,
):
    items = {
        "plan": None,
        "checks": [_serialize_verification_check(check) for check in verification_checks],
        "results": [_serialize_verification_result(result) for result in verification_results],
    }
    if verification_plan is not None:
        items["plan"] = {
            "id": verification_plan.id,
            "mode": verification_plan.mode,
            "status": verification_plan.status,
            "generated_from_profile_sha256": verification_plan.generated_from_profile_sha256,
            "required_check_count": verification_plan.required_check_count,
            "optional_check_count": verification_plan.optional_check_count,
            "satisfied_required_count": verification_plan.satisfied_required_count,
            "failed_required_count": verification_plan.failed_required_count,
            "generated_at": verification_plan.generated_at,
            "activated_at": verification_plan.activated_at,
            "satisfied_at": verification_plan.satisfied_at,
            "failed_at": verification_plan.failed_at,
        }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
        item_key="verification_results",
        canonical_path="verification/results.json",
        payload=_section_payload(bundle, change, items=[items]),
        present=verification_plan is not None,
        missing_reason="" if verification_plan is not None else "missing_verification_plan",
        source_type="changes.VerificationPlan" if verification_plan is not None else "",
        source_id=str(verification_plan.id) if verification_plan is not None else "",
        source_updated_at=verification_plan.updated_at if verification_plan is not None else None,
        source_metadata={
            "required_check_count": len([check for check in verification_checks if check.required]),
            "result_count": len(verification_results),
        },
    )


def _closure_section(bundle, change, closure):
    present = closure is not None
    item = None if closure is None else _serialize_closure(closure)
    return _Section(
        item_type=EvidenceBundleItem.ItemType.CLOSURE,
        item_key="closure",
        canonical_path="closure/closure.json",
        payload=_section_payload(bundle, change, items=[] if item is None else [item]),
        present=present,
        missing_reason="" if present else "missing_closure",
        source_type="changes.ChangeClosure" if present else "",
        source_id=str(closure.id) if present else "",
        source_updated_at=closure.updated_at if present else None,
        source_metadata={"outcome": closure.outcome if present else None},
    )


def _exceptions_section(bundle, change, exceptions, breakglass_sessions, retro_reviews):
    if not exceptions and not breakglass_sessions and not retro_reviews and not change.is_emergency:
        return None
    items = {
        "change_emergency": {
            "is_emergency": change.is_emergency,
            "emergency_declared_by_id": change.emergency_declared_by_id,
            "emergency_declared_at": change.emergency_declared_at,
            "retro_review_required": change.retro_review_required,
            "retro_review_due_at": change.retro_review_due_at,
            "retro_review_blocking_status": change.retro_review_blocking_status,
        },
        "exceptions": [_serialize_exception(exc) for exc in exceptions],
        "breakglass_sessions": [_serialize_breakglass(session) for session in breakglass_sessions],
        "retro_reviews": [_serialize_retro_review(review) for review in retro_reviews],
    }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXCEPTION,
        item_key="exceptions",
        canonical_path="exceptions/exceptions.json",
        payload=_section_payload(bundle, change, items=[items]),
        required=False,
        source_metadata={
            "exception_count": len(exceptions),
            "breakglass_count": len(breakglass_sessions),
            "retro_review_count": len(retro_reviews),
        },
    )


def _external_references_section(
    bundle,
    change,
    verification_results,
    verification_checks,
    retro_reviews,
):
    references = []
    for result in verification_results:
        if result.external_reference:
            references.append(
                {
                    "source_type": "changes.VerificationResult",
                    "source_id": result.id,
                    "reference": result.external_reference,
                }
            )
    for check in verification_checks:
        if check.external_reference_config:
            references.append(
                {
                    "source_type": "changes.VerificationCheck",
                    "source_id": check.id,
                    "reference": check.external_reference_config,
                }
            )
    for review in retro_reviews:
        if review.remediation_reference:
            references.append(
                {
                    "source_type": "changes.RetroReview",
                    "source_id": review.id,
                    "reference": review.remediation_reference,
                }
            )
    if not references:
        return None
    references.sort(key=lambda item: (item["source_type"], str(item["source_id"])))
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXTERNAL_REFERENCE,
        item_key="external_references",
        canonical_path="references/external_references.json",
        payload=_section_payload(bundle, change, items=references),
        required=False,
        source_metadata={"external_reference_count": len(references)},
    )


def _create_section_item(bundle, section: _Section, *, position: int) -> EvidenceBundleItem:
    payload_bytes = (
        canonical_ndjson_bytes(section.payload)
        if section.canonical_path.endswith(".ndjson")
        else canonical_json_bytes(section.payload)
    )
    return EvidenceBundleItem.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        item_type=section.item_type,
        item_key=section.item_key,
        canonical_path=section.canonical_path,
        position=position,
        required=section.required,
        present=section.present,
        valid=section.valid,
        missing_reason=section.missing_reason,
        validation_errors=list(section.validation_errors),
        source_type=section.source_type,
        source_id=section.source_id,
        source_updated_at=section.source_updated_at,
        source_metadata=section.source_metadata or {},
        content_sha256=sha256_hexdigest(payload_bytes),
        content_size_bytes=len(payload_bytes),
        mime_type="application/x-ndjson"
        if section.canonical_path.endswith(".ndjson")
        else "application/json",
    )


def _create_audit_event_item(bundle, event, *, position: int, event_position: int):
    payload_bytes = canonical_json_bytes(_serialize_audit_event(event))
    return EvidenceBundleItem.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        item_type=EvidenceBundleItem.ItemType.AUDIT_EVENT,
        item_key=f"audit_event:{event.id}",
        canonical_path="audit/audit_trail.ndjson",
        json_pointer=f"/events/{event_position - 1}",
        position=position,
        required=True,
        present=True,
        valid=True,
        source_type="audit.AuditEvent",
        source_id=str(event.id),
        source_updated_at=event.updated_at,
        source_metadata={
            "event_type": event.event_type,
            "object_type": event.object_type,
            "object_id": str(event.object_id),
            "occurred_at": _normalize(event.occurred_at),
            "event_position": event_position,
        },
        content_sha256=sha256_hexdigest(payload_bytes),
        content_size_bytes=len(payload_bytes),
        mime_type="application/json",
    )


def _create_artifact_item(bundle, change, artifact, *, position: int):
    validation_errors = _artifact_validation_errors(change, artifact)
    return EvidenceBundleItem.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        item_type=EvidenceBundleItem.ItemType.ARTIFACT,
        item_key=f"artifact:{artifact.id}",
        canonical_path=_artifact_bundle_path(artifact),
        position=position,
        required=True,
        present=True,
        valid=not validation_errors,
        validation_errors=validation_errors,
        source_type="artifacts.Artifact",
        source_id=str(artifact.id),
        source_updated_at=artifact.updated_at,
        source_metadata={
            "name": artifact.name,
            "kind": artifact.kind,
            "checksum_sha256": artifact.checksum_sha256,
            "upload_status": artifact.upload_status,
        },
        artifact=artifact if artifact.organization_id == bundle.organization_id else None,
        content_sha256=artifact.checksum_sha256 if _checksum_is_valid(artifact.checksum_sha256) else "",
        content_size_bytes=artifact.size_bytes,
        mime_type=artifact.mime_type,
    )


def _create_missing_verification_items(
    *,
    bundle,
    verification_checks,
    verification_results,
    start_position,
) -> None:
    accepted_result_check_ids = {
        result.verification_check_id
        for result in verification_results
        if result.validation_status == VerificationResult.ValidationStatus.ACCEPTED
    }
    position = start_position
    for check in verification_checks:
        if not check.required or check.id in accepted_result_check_ids:
            continue
        position += 1
        EvidenceBundleItem.objects.create(
            organization=bundle.organization,
            bundle=bundle,
            item_type=EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
            item_key=f"missing_verification_result:{check.id}",
            canonical_path="verification/results.json",
            json_pointer=f"/missing_required/{check.key}",
            position=position,
            required=True,
            present=False,
            valid=True,
            missing_reason="missing_required_verification_result",
            source_type="changes.VerificationCheck",
            source_id=str(check.id),
            source_updated_at=check.updated_at,
            source_metadata={"check_key": check.key, "check_type": check.check_type},
            content_sha256=sha256_hexdigest(canonical_json_bytes({"missing": str(check.id)})),
            content_size_bytes=len(canonical_json_bytes({"missing": str(check.id)})),
            mime_type="application/json",
        )


def _finalize_bundle_materialization(bundle, audit_events) -> None:
    items = list(
        EvidenceBundleItem.objects.filter(bundle=bundle).order_by(
            "position", "item_type", "item_key"
        )
    )
    completeness_report, completeness_status = _completeness_from_items(items)
    snapshot_payload = [
        {
            "item_type": item.item_type,
            "item_key": item.item_key,
            "canonical_path": item.canonical_path,
            "json_pointer": item.json_pointer,
            "position": item.position,
            "required": item.required,
            "present": item.present,
            "valid": item.valid,
            "missing_reason": item.missing_reason,
            "validation_errors": item.validation_errors,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "source_updated_at": item.source_updated_at,
            "content_sha256": item.content_sha256,
            "content_size_bytes": item.content_size_bytes,
        }
        for item in items
    ]
    audit_high_watermark = {}
    if audit_events:
        last_event = audit_events[-1]
        audit_high_watermark = {
            "occurred_at": _normalize(last_event.occurred_at),
            "created_at": _normalize(last_event.created_at),
            "id": str(last_event.id),
        }
    bundle.completeness_report = completeness_report
    bundle.completeness_status = completeness_status
    bundle.source_snapshot_sha256 = sha256_hexdigest(canonical_json_bytes(snapshot_payload))
    bundle.source_high_watermark = {"audit": audit_high_watermark}
    bundle.save(
        update_fields=[
            "completeness_report",
            "completeness_status",
            "source_snapshot_sha256",
            "source_high_watermark",
            "updated_at",
        ]
    )


def _completeness_from_items(items):
    sections = []
    missing_required = []
    invalid_items = []
    for item in items:
        report_item = {
            "item_type": item.item_type,
            "item_key": item.item_key,
            "canonical_path": item.canonical_path,
            "json_pointer": item.json_pointer,
            "position": item.position,
            "required": item.required,
            "present": item.present,
            "valid": item.valid,
            "missing_reason": item.missing_reason,
            "validation_errors": item.validation_errors,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "content_sha256": item.content_sha256,
        }
        sections.append(report_item)
        if item.required and not item.present:
            missing_required.append(report_item)
        if not item.valid:
            invalid_items.append(report_item)

    if invalid_items:
        status = EvidenceBundle.CompletenessStatus.INVALID
    elif missing_required:
        status = EvidenceBundle.CompletenessStatus.INCOMPLETE
    else:
        status = EvidenceBundle.CompletenessStatus.COMPLETE
    return (
        {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "summary": {
                "total_items": len(items),
                "missing_required_count": len(missing_required),
                "invalid_count": len(invalid_items),
            },
            "missing_required": missing_required,
            "invalid": invalid_items,
            "sections": sections,
        },
        status,
    )


def _emit_bundle_materialized(*, bundle, actor: AuditActor | None) -> None:
    actor = actor or system_actor("Evidence materialization")
    AuditService.emit(
        organization_id=bundle.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_bundle.materialized",
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        metadata={
            "change_record_id": str(bundle.change_record_id),
            "version": bundle.version,
            "completeness_status": bundle.completeness_status,
            "item_count": bundle.items.count(),
            "source_snapshot_sha256": bundle.source_snapshot_sha256,
        },
    )


def _related_object_ids(**sources):
    ids = {sources["change"].id}
    for key, value in sources.items():
        if key == "change" or value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for obj in values:
            if obj is not None:
                ids.add(obj.id)
            decision = _approval_decision_for(obj)
            if decision is not None:
                ids.add(decision.id)
    return ids


def _serialize_target(target):
    return {
        "id": target.id,
        "position": target.position,
        "target_type": target.target_type,
        "target_identifier": target.target_identifier,
        "normalized_identifier": target.normalized_identifier,
        "display_name": target.display_name,
        "environment": target.environment,
        "metadata": target.metadata,
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


def _serialize_approval_decision(decision):
    if decision is None:
        return None
    return {
        "id": decision.id,
        "decision": decision.decision,
        "source_type": decision.source_type,
        "decided_by_user_id": decision.decided_by_user_id,
        "decided_by_label": decision.decided_by_label,
        "decided_by_label_source": decision.decided_by_label_source,
        "notes_sha256": _hash_text(decision.notes),
        "decided_at": decision.decided_at,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
    }


def _approval_decision_for(approval):
    try:
        return approval.decision
    except (AttributeError, ObjectDoesNotExist):
        return None


def _serialize_binding(binding):
    if binding is None:
        return None
    return {
        "id": binding.id,
        "operation_profile_key": binding.operation_profile_key,
        "requested_inputs_sha256": binding.requested_inputs_sha256,
        "dispatch_token_expires_at": binding.dispatch_token_expires_at,
        "reserved_at": binding.reserved_at,
        "bound_at": binding.bound_at,
        "bound_by_runner_id": binding.bound_by_runner_id,
        "execution_accepted_at": binding.execution_accepted_at,
        "execution_started_at": binding.execution_started_at,
        "execution_finished_at": binding.execution_finished_at,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def _serialize_execution_step(step):
    return {
        "id": step.id,
        "position": step.position,
        "step_key": step.step_key,
        "name": step.name,
        "step_type": step.step_type,
        "risk_level": step.risk_level,
        "requires_approval": step.requires_approval,
        "status": step.status,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "exit_code": step.exit_code,
        "error_message": step.error_message,
        "created_at": step.created_at,
        "updated_at": step.updated_at,
    }


def _serialize_verification_check(check):
    return {
        "id": check.id,
        "position": check.position,
        "key": check.key,
        "name": check.name,
        "description": check.description,
        "check_type": check.check_type,
        "required": check.required,
        "status": check.status,
        "verification_key": check.verification_key,
        "source_step_key": check.source_step_key,
        "artifact_kind": check.artifact_kind,
        "artifact_name_pattern": check.artifact_name_pattern,
        "expected_checksum_sha256": check.expected_checksum_sha256,
        "external_reference_config": check.external_reference_config,
        "last_result_id": check.last_result_id,
        "satisfied_at": check.satisfied_at,
        "failed_at": check.failed_at,
        "created_at": check.created_at,
        "updated_at": check.updated_at,
    }


def _serialize_verification_result(result):
    return {
        "id": result.id,
        "verification_check_id": result.verification_check_id,
        "source": result.source,
        "outcome": result.outcome,
        "validation_status": result.validation_status,
        "submitted_by_id": result.submitted_by_id,
        "runner_id": result.runner_id,
        "verification_key": result.verification_key,
        "artifact_id": result.artifact_id,
        "artifact_checksum_sha256": result.artifact_checksum_sha256,
        "external_reference": result.external_reference,
        "manual_attestation_sha256": _hash_text(result.manual_attestation_text),
        "observed_value": result.observed_value,
        "validation_errors": result.validation_errors,
        "submitted_at": result.submitted_at,
        "validated_at": result.validated_at,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
    }


def _serialize_closure(closure: ChangeClosure):
    return {
        "id": closure.id,
        "outcome": closure.outcome,
        "closed_by_id": closure.closed_by_id,
        "independent_reviewer_id": closure.independent_reviewer_id,
        "summary": closure.summary,
        "verification_plan_id": closure.verification_plan_id,
        "verification_summary": closure.verification_summary,
        "execution_summary": closure.execution_summary,
        "closed_at": closure.closed_at,
        "created_at": closure.created_at,
        "updated_at": closure.updated_at,
    }


def _serialize_exception(exc):
    return {
        "id": exc.id,
        "exception_type": exc.exception_type,
        "status": exc.status,
        "reason_sha256": _hash_text(exc.reason),
        "scope_sha256": sha256_hexdigest(canonical_json_bytes(exc.scope_json)),
        "requested_by_id": exc.requested_by_id,
        "requested_at": exc.requested_at,
        "approval_request_id": exc.approval_request_id,
        "approved_by_id": exc.approved_by_id,
        "approved_at": exc.approved_at,
        "rejected_at": exc.rejected_at,
        "expires_at": exc.expires_at,
        "resolved_at": exc.resolved_at,
        "resolution_note_sha256": _hash_text(exc.resolution_note),
        "policy_evaluation_id": exc.policy_evaluation_id,
        "verification_check_id": exc.verification_check_id,
        "artifact_id": exc.artifact_id,
        "created_at": exc.created_at,
        "updated_at": exc.updated_at,
    }


def _serialize_breakglass(session):
    return {
        "id": session.id,
        "status": session.status,
        "scope_sha256": session.scope_sha256,
        "reason_sha256": _hash_text(session.reason),
        "activated_by_id": session.activated_by_id,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "ended_at": session.ended_at,
        "ended_by_id": session.ended_by_id,
        "end_reason": session.end_reason,
        "review_due_at": session.review_due_at,
        "review_status": session.review_status,
        "last_heartbeat_at": session.last_heartbeat_at,
        "activation_ip_hash": session.activation_ip_hash,
        "activation_user_agent": session.activation_user_agent,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _serialize_retro_review(review):
    return {
        "id": review.id,
        "breakglass_session_id": review.breakglass_session_id,
        "change_exception_id": review.change_exception_id,
        "status": review.status,
        "disposition": review.disposition,
        "reviewed_by_id": review.reviewed_by_id,
        "reviewed_at": review.reviewed_at,
        "due_at": review.due_at,
        "summary_sha256": _hash_text(review.summary),
        "remediation_required": review.remediation_required,
        "remediation_reference": review.remediation_reference,
        "control_failure_category": review.control_failure_category,
        "evidence_sha256": sha256_hexdigest(canonical_json_bytes(review.evidence_json)),
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


def _serialize_audit_event(event):
    return {
        "id": event.id,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "actor_label": event.actor_label,
        "event_type": event.event_type,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "organization_id": event.organization_id,
        "metadata": event.metadata,
        "occurred_at": event.occurred_at,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def _artifact_validation_errors(change, artifact):
    errors = []
    if artifact.organization_id != change.organization_id:
        errors.append(
            {
                "code": "cross_org_artifact_reference",
                "artifact_id": str(artifact.id),
                "artifact_organization_id": str(artifact.organization_id),
                "expected_organization_id": str(change.organization_id),
            }
        )
    if artifact.execution.organization_id != change.organization_id:
        errors.append(
            {
                "code": "cross_org_artifact_execution",
                "artifact_id": str(artifact.id),
                "execution_id": str(artifact.execution_id),
            }
        )
    if not _checksum_is_valid(artifact.checksum_sha256):
        errors.append(
            {
                "code": "invalid_artifact_checksum",
                "artifact_id": str(artifact.id),
            }
        )
    if artifact.upload_status != artifact.UploadStatus.AVAILABLE:
        errors.append(
            {
                "code": "artifact_unavailable",
                "artifact_id": str(artifact.id),
                "upload_status": artifact.upload_status,
            }
        )
    return errors


def _artifact_bundle_path(artifact):
    safe_name = "".join(
        char if char.isalnum() or char in {".", "-", "_"} else "_"
        for char in artifact.name
    ).strip("._")
    if not safe_name:
        safe_name = "artifact"
    return f"artifacts/files/{artifact.id}/{safe_name}"


def _checksum_is_valid(value):
    return isinstance(value, str) and len(value) == 64 and value == value.lower() and all(
        char in "0123456789abcdef" for char in value
    )


def _hash_text(value: str) -> str:
    if not value:
        return ""
    return sha256_hexdigest(str(value).encode("utf-8"))


def sha256_hexdigest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_ndjson_bytes(values) -> bytes:
    lines = [canonical_json_bytes(value).decode("utf-8") for value in values]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _normalize(value):
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, UTC)
        value = value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "pk") and hasattr(value, "_meta"):
        return _normalize(model_to_dict(value))
    return value
