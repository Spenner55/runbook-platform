import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.executions.models import Execution, ExecutionStep
from apps.policies.models import Policy, PolicyEvaluation, PolicyRule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------


def create_policy(
    *,
    organization,
    name: str,
    description: str = "",
    is_active: bool = True,
    created_by_label: str = "",
    actor: AuditActor | None = None,
) -> Policy:
    if (
        is_active
        and Policy.objects.filter(
            organization=organization, name=name, is_active=True
        ).exists()
    ):
        raise DomainConflictError(
            code="duplicate_active_policy_name",
            detail=f"An active policy named '{name}' already exists for this organization.",
        )
    with transaction.atomic():
        policy = Policy.objects.create(
            organization=organization,
            name=name,
            description=description,
            is_active=is_active,
            created_by_label=created_by_label,
        )
        _emit_policy_audit(
            policy=policy,
            event_type="policy.created",
            actor=actor,
            metadata={"policy_id": str(policy.id), "is_active": policy.is_active},
        )
        return policy


def update_policy(
    *, policy: Policy, actor: AuditActor | None = None, **changes
) -> Policy:
    allowed = {"name", "description", "is_active", "updated_by_label"}
    unknown = set(changes) - allowed
    if unknown:
        raise DomainValidationError(
            code="invalid_policy_fields",
            detail=f"Cannot update fields: {', '.join(unknown)}",
        )

    new_name = changes.get("name", policy.name)
    new_is_active = changes.get("is_active", policy.is_active)

    # Guard: reactivating or renaming to an existing active name
    if new_is_active and (
        new_name != policy.name or (not policy.is_active and new_is_active)
    ):
        qs = Policy.objects.filter(
            organization=policy.organization, name=new_name, is_active=True
        )
        if policy.pk:
            qs = qs.exclude(pk=policy.pk)
        if qs.exists():
            raise DomainConflictError(
                code="duplicate_active_policy_name",
                detail=f"An active policy named '{new_name}' already exists for this organization.",
            )

    with transaction.atomic():
        policy = Policy.objects.select_for_update().get(pk=policy.pk)
        previous_is_active = policy.is_active
        for field, value in changes.items():
            setattr(policy, field, value)
        policy.save(update_fields=list(changes.keys()) + ["updated_at"])
        event_type = (
            "policy.deactivated"
            if previous_is_active and policy.is_active is False
            else "policy.updated"
        )
        _emit_policy_audit(
            policy=policy,
            event_type=event_type,
            actor=actor,
            metadata={
                "policy_id": str(policy.id),
                "changed_fields": sorted(changes.keys()),
                "previous_is_active": previous_is_active,
                "new_is_active": policy.is_active,
            },
        )
        return policy


# ---------------------------------------------------------------------------
# Rule CRUD
# ---------------------------------------------------------------------------


def create_rule(
    *,
    policy: Policy,
    name: str,
    priority: int,
    condition_type: str,
    condition_params: dict,
    outcome: str,
    description: str = "",
    reason: str = "",
    is_active: bool = True,
    actor: AuditActor | None = None,
) -> PolicyRule:
    if priority <= 0:
        raise DomainValidationError(
            code="invalid_rule_priority",
            detail="Rule priority must be greater than 0.",
        )
    _validate_condition_params(condition_type, condition_params)
    _validate_outcome(outcome)

    if PolicyRule.objects.filter(policy=policy, priority=priority).exists():
        raise DomainConflictError(
            code="duplicate_rule_priority",
            detail=f"A rule with priority {priority} already exists in this policy.",
        )
    if PolicyRule.objects.filter(policy=policy, name=name).exists():
        raise DomainConflictError(
            code="duplicate_rule_name",
            detail=f"A rule named '{name}' already exists in this policy.",
        )

    with transaction.atomic():
        rule = PolicyRule.objects.create(
            policy=policy,
            name=name,
            description=description,
            is_active=is_active,
            priority=priority,
            condition_type=condition_type,
            condition_params=condition_params,
            outcome=outcome,
            reason=reason,
        )
        _emit_policy_rule_audit(
            rule=rule,
            event_type="policy_rule.created",
            actor=actor,
            metadata={
                "policy_id": str(policy.id),
                "rule_id": str(rule.id),
                "condition_type": rule.condition_type,
                "outcome": rule.outcome,
                "priority": rule.priority,
                "is_active": rule.is_active,
            },
        )
        return rule


def update_rule(
    *, rule: PolicyRule, actor: AuditActor | None = None, **changes
) -> PolicyRule:
    allowed = {
        "name",
        "description",
        "is_active",
        "priority",
        "condition_type",
        "condition_params",
        "outcome",
        "reason",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise DomainValidationError(
            code="invalid_rule_fields",
            detail=f"Cannot update fields: {', '.join(unknown)}",
        )

    new_priority = changes.get("priority", rule.priority)
    new_name = changes.get("name", rule.name)
    new_condition_type = changes.get("condition_type", rule.condition_type)
    new_condition_params = changes.get("condition_params", rule.condition_params)
    new_outcome = changes.get("outcome", rule.outcome)

    if "priority" in changes and new_priority != rule.priority:
        if new_priority <= 0:
            raise DomainValidationError(
                code="invalid_rule_priority",
                detail="Rule priority must be greater than 0.",
            )
        if (
            PolicyRule.objects.filter(policy=rule.policy, priority=new_priority)
            .exclude(pk=rule.pk)
            .exists()
        ):
            raise DomainConflictError(
                code="duplicate_rule_priority",
                detail=f"A rule with priority {new_priority} already exists in this policy.",
            )

    if "name" in changes and new_name != rule.name:
        if (
            PolicyRule.objects.filter(policy=rule.policy, name=new_name)
            .exclude(pk=rule.pk)
            .exists()
        ):
            raise DomainConflictError(
                code="duplicate_rule_name",
                detail=f"A rule named '{new_name}' already exists in this policy.",
            )

    if "condition_type" in changes or "condition_params" in changes:
        _validate_condition_params(new_condition_type, new_condition_params)

    if "outcome" in changes:
        _validate_outcome(new_outcome)

    with transaction.atomic():
        rule = (
            PolicyRule.objects.select_for_update()
            .select_related("policy")
            .get(pk=rule.pk)
        )
        previous_is_active = rule.is_active
        for field, value in changes.items():
            setattr(rule, field, value)
        rule.save(update_fields=list(changes.keys()) + ["updated_at"])
        event_type = (
            "policy_rule.deactivated"
            if previous_is_active and rule.is_active is False
            else "policy_rule.updated"
        )
        _emit_policy_rule_audit(
            rule=rule,
            event_type=event_type,
            actor=actor,
            metadata={
                "policy_id": str(rule.policy_id),
                "rule_id": str(rule.id),
                "changed_fields": sorted(changes.keys()),
                "previous_is_active": previous_is_active,
                "new_is_active": rule.is_active,
            },
        )
        return rule


def deactivate_rule(*, rule: PolicyRule, actor: AuditActor | None = None) -> PolicyRule:
    return update_rule(rule=rule, actor=actor, is_active=False)


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


def evaluate_step_policy(
    *,
    execution: Execution,
    step: ExecutionStep,
    evaluated_at=None,
) -> PolicyEvaluation:
    if evaluated_at is None:
        evaluated_at = timezone.now()

    # Tenant consistency guard
    if str(step.execution_id) != str(execution.id):
        raise DomainValidationError(
            code="step_execution_mismatch",
            detail="Step does not belong to the given execution.",
        )

    context = _build_evaluation_context(execution, step, evaluated_at)
    condition_context = {**context, "evaluated_at": evaluated_at}

    try:
        active_policies = list(
            Policy.objects.filter(
                organization=execution.organization,
                is_active=True,
            ).prefetch_related(
                "rules",
            )
        )

        all_active_rules = []
        for policy in active_policies:
            for rule in policy.rules.all():
                if rule.is_active:
                    all_active_rules.append((policy, rule))

        # Deterministic global sort: (priority, policy.created_at, policy.id, rule.id)
        all_active_rules.sort(
            key=lambda pr: (pr[1].priority, pr[0].created_at, pr[0].id, pr[1].id)
        )

        for policy, rule in all_active_rules:
            try:
                _validate_condition_params(rule.condition_type, rule.condition_params)
            except DomainValidationError as exc:
                logger.error(
                    "Policy rule %s has invalid condition params during evaluation: %s",
                    rule.id,
                    exc.detail,
                )
                return _persist_evaluation_error(
                    execution=execution,
                    step=step,
                    policy=policy,
                    rule=rule,
                    evaluated_at=evaluated_at,
                    context=context,
                    error_code="invalid_condition_params",
                    error_message=str(exc.detail),
                )

            try:
                matched = _evaluate_condition(
                    rule.condition_type, rule.condition_params, condition_context
                )
            except Exception as exc:
                logger.error(
                    "Condition evaluation failed for rule %s: %s",
                    rule.id,
                    str(exc),
                )
                return _persist_evaluation_error(
                    execution=execution,
                    step=step,
                    policy=policy,
                    rule=rule,
                    evaluated_at=evaluated_at,
                    context=context,
                    error_code="condition_evaluation_error",
                    error_message=str(exc),
                )

            if matched:
                outcome = rule.outcome
                effective_outcome = _apply_requires_approval_floor(outcome, step)
                return _create_policy_evaluation_with_audit(
                    organization=execution.organization,
                    execution=execution,
                    step=step,
                    policy=policy,
                    rule=rule,
                    matched=True,
                    outcome=outcome,
                    effective_outcome=effective_outcome,
                    decision_source=PolicyEvaluation.DecisionSource.POLICY_RULE,
                    condition_type=rule.condition_type,
                    condition_params_snapshot=dict(rule.condition_params),
                    context_snapshot=context,
                    reason=rule.reason,
                    evaluated_at=evaluated_at,
                )

        # No rule matched — fall back to workflow default
        outcome = (
            PolicyRule.Outcome.APPROVAL_REQUIRED
            if step.requires_approval
            else PolicyRule.Outcome.AUTO_APPROVE
        )
        return _create_policy_evaluation_with_audit(
            organization=execution.organization,
            execution=execution,
            step=step,
            policy=None,
            rule=None,
            matched=False,
            outcome=outcome,
            effective_outcome=outcome,
            decision_source=PolicyEvaluation.DecisionSource.WORKFLOW_DEFAULT,
            condition_type="",
            condition_params_snapshot={},
            context_snapshot=context,
            reason="No matching policy rule; using workflow default.",
            evaluated_at=evaluated_at,
        )

    except Exception as exc:
        logger.error(
            "Unexpected error during policy evaluation for step %s: %s",
            step.id,
            str(exc),
        )
        try:
            return persist_policy_evaluation_error(
                execution=execution,
                step=step,
                error_code="policy_evaluation_error",
                error_message=str(exc),
                evaluated_at=evaluated_at,
                context=context,
            )
        except Exception:
            logger.exception(
                "Could not persist fail-closed policy evaluation for step %s", step.id
            )
            raise


def persist_policy_evaluation_error(
    *,
    execution: Execution,
    step: ExecutionStep,
    error_code: str,
    error_message: str,
    evaluated_at=None,
    context: dict | None = None,
) -> PolicyEvaluation:
    if evaluated_at is None:
        evaluated_at = timezone.now()
    if context is None:
        context = _build_evaluation_context(execution, step, evaluated_at)

    return _persist_evaluation_error(
        execution=execution,
        step=step,
        policy=None,
        rule=None,
        evaluated_at=evaluated_at,
        context=context,
        error_code=error_code,
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# Condition validation
# ---------------------------------------------------------------------------

_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


_ENUM_CONDITION_TYPES = frozenset({
    PolicyRule.ConditionType.RISK_LEVEL,
    PolicyRule.ConditionType.STEP_TYPE,
    PolicyRule.ConditionType.ACTION_TYPE,
    PolicyRule.ConditionType.ACTION_VERSION,
    PolicyRule.ConditionType.EXECUTION_MODE,
    PolicyRule.ConditionType.IDEMPOTENCY_MODE,
    PolicyRule.ConditionType.MUTATES_TARGET,
})


def _validate_condition_params(condition_type: str, condition_params: dict) -> None:
    if condition_type not in (ct.value for ct in PolicyRule.ConditionType):
        raise DomainValidationError(
            code="unknown_condition_type",
            detail=f"Unknown condition type: '{condition_type}'.",
        )
    if condition_type in _ENUM_CONDITION_TYPES:
        _validate_enum_condition(condition_params)
    elif condition_type == PolicyRule.ConditionType.TIME_WINDOW:
        _validate_time_window_condition(condition_params)


def _validate_enum_condition(params: dict) -> None:
    operator = params.get("operator")
    if operator not in ("equals", "in"):
        raise DomainValidationError(
            code="invalid_condition_params",
            detail="operator must be 'equals' or 'in'.",
        )
    if operator == "in":
        values = params.get("values")
        if not isinstance(values, list) or len(values) == 0:
            raise DomainValidationError(
                code="invalid_condition_params",
                detail="'values' must be a non-empty list when operator is 'in'.",
            )
        if not all(isinstance(v, str) for v in values):
            raise DomainValidationError(
                code="invalid_condition_params",
                detail="All values must be strings.",
            )
    else:
        value = params.get("value")
        if not isinstance(value, str) or not value:
            raise DomainValidationError(
                code="invalid_condition_params",
                detail="'value' must be a non-empty string when operator is 'equals'.",
            )


def _validate_time_window_condition(params: dict) -> None:
    tz_name = params.get("timezone")
    if not tz_name:
        raise DomainValidationError(
            code="invalid_condition_params", detail="'timezone' is required."
        )
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        raise DomainValidationError(
            code="invalid_condition_params",
            detail=f"'{tz_name}' is not a valid IANA timezone.",
        )

    days = params.get("days_of_week")
    if not isinstance(days, list) or len(days) == 0:
        raise DomainValidationError(
            code="invalid_condition_params",
            detail="'days_of_week' must be a non-empty list.",
        )
    invalid_days = [d for d in days if d not in _VALID_DAYS]
    if invalid_days:
        raise DomainValidationError(
            code="invalid_condition_params",
            detail=f"Invalid days_of_week values: {invalid_days}. Use mon/tue/wed/thu/fri/sat/sun.",
        )

    start_time = params.get("start_time")
    end_time = params.get("end_time")
    for field_name, val in [("start_time", start_time), ("end_time", end_time)]:
        if not isinstance(val, str):
            raise DomainValidationError(
                code="invalid_condition_params",
                detail=f"'{field_name}' must be a string in HH:MM format.",
            )
        parts = val.split(":")
        if len(parts) != 2:
            raise DomainValidationError(
                code="invalid_condition_params",
                detail=f"'{field_name}' must be in HH:MM format.",
            )
        try:
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except ValueError:
            raise DomainValidationError(
                code="invalid_condition_params",
                detail=f"'{field_name}' is not a valid 24-hour HH:MM time.",
            )

    if start_time >= end_time:
        raise DomainValidationError(
            code="invalid_condition_params",
            detail="'start_time' must be before 'end_time'.",
        )

    match_when = params.get("match_when")
    if match_when not in ("inside", "outside"):
        raise DomainValidationError(
            code="invalid_condition_params",
            detail="'match_when' must be 'inside' or 'outside'.",
        )


def _validate_outcome(outcome: str) -> None:
    if outcome not in (o.value for o in PolicyRule.Outcome):
        raise DomainValidationError(
            code="invalid_outcome",
            detail=f"Invalid outcome: '{outcome}'. Must be approval_required, auto_approve, or block.",
        )


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

_DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _evaluate_condition(
    condition_type: str, condition_params: dict, context: dict
) -> bool:
    if condition_type == PolicyRule.ConditionType.RISK_LEVEL:
        return _evaluate_enum_condition(condition_params, context.get("risk_level", ""))
    if condition_type == PolicyRule.ConditionType.STEP_TYPE:
        return _evaluate_enum_condition(condition_params, context.get("step_type", ""))
    if condition_type == PolicyRule.ConditionType.TIME_WINDOW:
        return _evaluate_time_window_condition(
            condition_params, context.get("evaluated_at")
        )
    if condition_type == PolicyRule.ConditionType.ACTION_TYPE:
        return _evaluate_enum_condition(condition_params, context.get("action_type", ""))
    if condition_type == PolicyRule.ConditionType.ACTION_VERSION:
        return _evaluate_enum_condition(condition_params, context.get("action_version", ""))
    if condition_type == PolicyRule.ConditionType.EXECUTION_MODE:
        return _evaluate_enum_condition(condition_params, context.get("execution_mode", ""))
    if condition_type == PolicyRule.ConditionType.IDEMPOTENCY_MODE:
        return _evaluate_enum_condition(condition_params, context.get("idempotency_mode", ""))
    if condition_type == PolicyRule.ConditionType.MUTATES_TARGET:
        return _evaluate_enum_condition(condition_params, context.get("mutates_target", ""))
    return False


def _evaluate_enum_condition(params: dict, actual_value: str) -> bool:
    operator = params.get("operator")
    if operator == "equals":
        return actual_value == params.get("value")
    if operator == "in":
        return actual_value in params.get("values", [])
    return False


def _evaluate_time_window_condition(params: dict, evaluated_at) -> bool:
    tz = ZoneInfo(params["timezone"])
    if hasattr(evaluated_at, "astimezone"):
        local_dt = evaluated_at.astimezone(tz)
    else:
        parsed_dt = parse_datetime(str(evaluated_at))
        if parsed_dt is None:
            raise ValueError("evaluated_at must be a datetime or ISO datetime string.")
        if timezone.is_naive(parsed_dt):
            parsed_dt = timezone.make_aware(parsed_dt, ZoneInfo("UTC"))
        local_dt = parsed_dt.astimezone(tz)

    day_name = local_dt.strftime("%a").lower()
    current_time = local_dt.strftime("%H:%M")
    in_window = (
        day_name in params["days_of_week"]
        and params["start_time"] <= current_time < params["end_time"]
    )
    match_when = params.get("match_when", "inside")
    return in_window if match_when == "inside" else not in_window


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_requires_approval_floor(outcome: str, step: ExecutionStep) -> str:
    if step.requires_approval and outcome == PolicyRule.Outcome.AUTO_APPROVE:
        return PolicyRule.Outcome.APPROVAL_REQUIRED
    return outcome


def _build_evaluation_context(
    execution: Execution, step: ExecutionStep, evaluated_at
) -> dict:
    snapshot = step.step_snapshot or {}
    action = snapshot.get("action") or {}
    retry = snapshot.get("retry") or {}
    idempotency = snapshot.get("idempotency") or {}
    dry_run = snapshot.get("dryRun") or {}
    workflow_snapshot = execution.workflow_snapshot or {}

    # Serialize mutates_target as a string so enum condition can compare it.
    mutates_target_raw = snapshot.get("mutatesTarget")
    if mutates_target_raw is True:
        mutates_target = "true"
    elif mutates_target_raw is False:
        mutates_target = "false"
    else:
        mutates_target = ""

    return {
        "organization_id": str(execution.organization_id),
        "execution_id": str(execution.id),
        "step_id": str(step.id),
        "step_key": step.step_key,
        "step_type": step.step_type,
        "risk_level": step.risk_level,
        "requires_approval": step.requires_approval,
        "evaluated_at": evaluated_at.isoformat()
        if hasattr(evaluated_at, "isoformat")
        else str(evaluated_at),
        "workflow_id": str(execution.workflow_id) if execution.workflow_id else None,
        # v2 action facts — empty for v1 where the snapshot fields are absent
        "schema_version": workflow_snapshot.get("schemaVersion", ""),
        "catalog_version": workflow_snapshot.get("catalogVersion", ""),
        "execution_mode": execution.execution_mode,
        "action_type": action.get("type", ""),
        "action_version": action.get("version", ""),
        "timeout_seconds": snapshot.get("timeoutSeconds"),
        "retry_max_attempts": retry.get("maxAttempts"),
        "idempotency_mode": idempotency.get("mode", ""),
        "declared_secret_keys": list(snapshot.get("secrets") or []),
        "declared_artifact_keys": [
            a.get("key", "") for a in (snapshot.get("artifacts") or [])
        ],
        "mutates_target": mutates_target,
        "dry_run_supported": dry_run.get("supported") if dry_run else None,
    }


def _persist_evaluation_error(
    *,
    execution,
    step,
    policy,
    rule,
    evaluated_at,
    context,
    error_code,
    error_message,
) -> PolicyEvaluation:
    return _create_policy_evaluation_with_audit(
        organization=execution.organization,
        execution=execution,
        step=step,
        policy=policy,
        rule=rule,
        matched=False,
        outcome="block",
        effective_outcome="block",
        decision_source=PolicyEvaluation.DecisionSource.POLICY_RULE,
        condition_type=rule.condition_type if rule else "",
        condition_params_snapshot=dict(rule.condition_params) if rule else {},
        context_snapshot=context,
        reason="Policy evaluation failed; step blocked for safety.",
        error_code=error_code,
        error_message=error_message,
        evaluated_at=evaluated_at,
    )


def _create_policy_evaluation_with_audit(**fields) -> PolicyEvaluation:
    with transaction.atomic():
        evaluation = PolicyEvaluation.objects.create(**fields)
        from apps.changes import services as change_services  # avoid circular

        change_services.link_policy_evaluation(
            execution=fields["execution"],
            policy_evaluation=evaluation,
        )
        AuditService.emit(
            organization_id=evaluation.organization_id,
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id="",
            actor_label="Django system",
            event_type="policy.evaluated",
            object_type=AuditEvent.ObjectType.POLICY_EVALUATION,
            object_id=evaluation.id,
            metadata={
                "execution_id": str(evaluation.execution_id),
                "step_id": str(evaluation.step_id),
                "policy_id": str(evaluation.policy_id) if evaluation.policy_id else "",
                "rule_id": str(evaluation.rule_id) if evaluation.rule_id else "",
                "matched": evaluation.matched,
                "outcome": evaluation.outcome,
                "effective_outcome": evaluation.effective_outcome,
                "decision_source": evaluation.decision_source,
                "reason": evaluation.reason,
                "error_code": evaluation.error_code,
                "error_message": evaluation.error_message,
            },
        )
        return evaluation


def _emit_policy_audit(
    *, policy: Policy, event_type: str, actor: AuditActor | None, metadata: dict
) -> None:
    audit_actor = actor or system_actor("Policy service")
    AuditService.emit(
        organization_id=policy.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.POLICY,
        object_id=policy.id,
        metadata=metadata,
    )


def _emit_policy_rule_audit(
    *, rule: PolicyRule, event_type: str, actor: AuditActor | None, metadata: dict
) -> None:
    audit_actor = actor or system_actor("Policy service")
    AuditService.emit(
        organization_id=rule.policy.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.POLICY_RULE,
        object_id=rule.id,
        metadata=metadata,
    )
