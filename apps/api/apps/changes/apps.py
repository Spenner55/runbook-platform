from django.apps import AppConfig
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed, post_save, pre_save


class ChangesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.changes"

    def ready(self):
        from apps.audit.services import system_actor
        from apps.changes.models import OperationProfile
        from apps.changes.services import emit_operation_profile_audit
        from apps.workflows.models import Workflow

        def remember_profile_active_state(sender, instance, **kwargs):
            if not instance.pk:
                instance._previous_is_active = None
                return
            previous = sender.objects.filter(pk=instance.pk).only("is_active").first()
            instance._previous_is_active = (
                previous.is_active if previous is not None else None
            )

        def audit_profile_save(sender, instance, created, **kwargs):
            previous_is_active = getattr(instance, "_previous_is_active", None)
            if created:
                event_type = "operation_profile.created"
            elif previous_is_active and not instance.is_active:
                event_type = "operation_profile.deactivated"
            else:
                event_type = "operation_profile.updated"
            emit_operation_profile_audit(
                profile=instance,
                event_type=event_type,
                actor=getattr(
                    instance,
                    "_audit_actor",
                    system_actor("Operation profile ORM"),
                ),
            )

        def validate_allowed_workflow_org(sender, instance, action, pk_set, **kwargs):
            if action != "pre_add" or not pk_set:
                return
            invalid = Workflow.objects.filter(pk__in=pk_set).exclude(
                organization_id=instance.organization_id
            )
            if invalid.exists():
                raise ValidationError(
                    "Operation profile workflows must belong to the same organization."
                )

        def audit_allowed_workflow_change(sender, instance, action, **kwargs):
            if action not in {"post_add", "post_remove", "post_clear"}:
                return
            emit_operation_profile_audit(
                profile=instance,
                event_type="operation_profile.updated",
                actor=getattr(
                    instance,
                    "_audit_actor",
                    system_actor("Operation profile ORM"),
                ),
                metadata={"allowed_workflows_changed": True},
            )

        pre_save.connect(
            remember_profile_active_state,
            sender=OperationProfile,
            dispatch_uid="changes_remember_operation_profile_active_state",
            weak=False,
        )
        post_save.connect(
            audit_profile_save,
            sender=OperationProfile,
            dispatch_uid="changes_audit_operation_profile_save",
            weak=False,
        )
        m2m_changed.connect(
            validate_allowed_workflow_org,
            sender=OperationProfile.allowed_workflows.through,
            dispatch_uid="changes_validate_operation_profile_workflow_org",
            weak=False,
        )
        m2m_changed.connect(
            audit_allowed_workflow_change,
            sender=OperationProfile.allowed_workflows.through,
            dispatch_uid="changes_audit_operation_profile_allowed_workflows",
            weak=False,
        )
