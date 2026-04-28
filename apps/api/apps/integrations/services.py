import logging
import time
from typing import Any

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)
from apps.integrations.ssrf import validate_outbound_url

logger = logging.getLogger(__name__)

EVENT_EXECUTION_CREATED = "execution.created"
EVENT_EXECUTION_STARTED = "execution.started"
EVENT_EXECUTION_COMPLETED = "execution.completed"
EVENT_EXECUTION_FAILED = "execution.failed"
EVENT_EXECUTION_CANCELLED = "execution.cancelled"
EVENT_EXECUTION_STEP_FAILED = "execution_step.failed"
EVENT_EXECUTION_STEP_STARTED = "execution_step.started"
EVENT_EXECUTION_STEP_WAITING_FOR_APPROVAL = "execution_step.waiting_for_approval"
EVENT_APPROVAL_REQUESTED = "approval.requested"
EVENT_APPROVAL_DECIDED = "approval.decided"
EVENT_APPROVAL_APPROVED = "approval.approved"
EVENT_APPROVAL_REJECTED = "approval.rejected"
EVENT_ARTIFACT_UPLOADED = "artifact.uploaded"

SUPPORTED_EVENT_TYPES = {
    EVENT_EXECUTION_CREATED,
    EVENT_EXECUTION_STARTED,
    EVENT_EXECUTION_COMPLETED,
    EVENT_EXECUTION_FAILED,
    EVENT_EXECUTION_CANCELLED,
    EVENT_EXECUTION_STEP_FAILED,
    EVENT_EXECUTION_STEP_STARTED,
    EVENT_EXECUTION_STEP_WAITING_FOR_APPROVAL,
    EVENT_APPROVAL_REQUESTED,
    EVENT_APPROVAL_DECIDED,
    EVENT_APPROVAL_APPROVED,
    EVENT_APPROVAL_REJECTED,
    EVENT_ARTIFACT_UPLOADED,
}

AUDIT_INTEGRATION_CREATED = "integration.created"
AUDIT_INTEGRATION_UPDATED = "integration.updated"
AUDIT_INTEGRATION_DEACTIVATED = "integration.deactivated"

REDACTED = "[redacted]"
SECRET_KEY_FRAGMENTS = {
    "authorization",
    "claim_token",
    "cookie",
    "encrypted_credentials",
    "password",
    "private_key",
    "raw_error",
    "raw_output",
    "secret",
    "storage_key",
    "token",
    "url",
    "webhook",
}


class IntegrationService:
    http_client_factory = httpx.Client
    validate_outbound_url = staticmethod(validate_outbound_url)

    @classmethod
    def create_connection(
        cls,
        *,
        organization,
        type: str,
        name: str,
        credentials: dict,
        config: dict | None = None,
        event_types: list[str] | None = None,
        actor: AuditActor | None = None,
    ) -> IntegrationConnection:
        cls._validate_type(type)
        config = cls._clean_config(config)
        event_types = cls._clean_event_types(event_types)
        credentials = cls._clean_credentials(type, credentials)

        connection = IntegrationConnection(
            organization=organization,
            type=type,
            name=(name or "").strip(),
            config=config,
            event_types=event_types,
        )
        connection.set_credentials(credentials)
        connection.full_clean(exclude=["config"])
        connection.save()

        cls._emit_management_audit(
            connection=connection,
            event_type=AUDIT_INTEGRATION_CREATED,
            actor=actor,
            metadata={
                "type": connection.type,
                "name": connection.name,
                "event_types": connection.event_types,
                "credentials_configured": bool(connection.encrypted_credentials),
            },
        )
        return connection

    @classmethod
    def update_connection(
        cls,
        *,
        connection: IntegrationConnection,
        actor: AuditActor | None = None,
        **fields,
    ) -> IntegrationConnection:
        changed_fields = []

        if "name" in fields:
            connection.name = (fields["name"] or "").strip()
            changed_fields.append("name")
        if "config" in fields:
            connection.config = cls._clean_config(fields["config"])
            changed_fields.append("config")
        if "event_types" in fields:
            connection.event_types = cls._clean_event_types(fields["event_types"])
            changed_fields.append("event_types")
        if "credentials" in fields:
            credentials = cls._clean_credentials(connection.type, fields["credentials"])
            connection.set_credentials(credentials)
            changed_fields.append("credentials")

        connection.full_clean(exclude=["config"])
        connection.save()

        cls._emit_management_audit(
            connection=connection,
            event_type=AUDIT_INTEGRATION_UPDATED,
            actor=actor,
            metadata={
                "type": connection.type,
                "name": connection.name,
                "changed_fields": changed_fields,
                "credentials_updated": "credentials" in changed_fields,
            },
        )
        return connection

    @classmethod
    def deactivate_connection(
        cls,
        *,
        connection: IntegrationConnection,
        actor: AuditActor | None = None,
    ) -> IntegrationConnection:
        if connection.is_active:
            connection.is_active = False
            connection.save(update_fields=["is_active", "updated_at"])

        cls._emit_management_audit(
            connection=connection,
            event_type=AUDIT_INTEGRATION_DEACTIVATED,
            actor=actor,
            metadata={"type": connection.type, "name": connection.name},
        )
        return connection

    @classmethod
    def notify(
        cls, *, event_type: str, organization, context: dict | None = None
    ) -> None:
        try:
            organization_id = getattr(organization, "id", organization)
            started = time.monotonic()
            notified_count = 0
            max_per_trigger = cls._max_per_trigger()
            connections = IntegrationConnection.objects.filter(
                organization_id=organization_id,
                is_active=True,
            ).order_by("created_at", "id")

            for connection in connections:
                if not cls._matches_event_type(connection, event_type):
                    continue
                if notified_count >= max_per_trigger:
                    logger.warning(
                        "Integration notification skipped after max-per-trigger limit.",
                        extra={
                            "organization_id": str(organization_id),
                            "event_type": event_type,
                            "max_per_trigger": max_per_trigger,
                        },
                    )
                    break
                if cls._dispatch_budget_exhausted(started):
                    logger.warning(
                        "Integration notification skipped after dispatch budget.",
                        extra={
                            "organization_id": str(organization_id),
                            "event_type": event_type,
                        },
                    )
                    break
                try:
                    cls._notify_connection(
                        connection=connection,
                        event_type=event_type,
                        context=context or {},
                    )
                except Exception:
                    logger.exception(
                        "Integration notification failed for one connection.",
                        extra={
                            "integration_id": str(connection.id),
                            "event_type": event_type,
                        },
                    )
                notified_count += 1
        except Exception:
            logger.exception("Integration notification dispatch failed before completion.")

    @classmethod
    def _notify_connection(
        cls,
        *,
        connection: IntegrationConnection,
        event_type: str,
        context: dict,
    ) -> None:
        attempted_at = timezone.now()
        payload_preview = cls._payload_preview(event_type=event_type, context=context)

        try:
            credentials = connection.get_credentials()
            url = credentials.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValidationError("Integration webhook URL is required.")
            cls.validate_outbound_url(url)

            payload = cls._build_payload(
                connection=connection,
                event_type=event_type,
                context=context,
            )
            payload_preview = cls._payload_preview_from_payload(payload)
            http_status, latency_ms, error_detail = cls._dispatch_webhook(
                url=url,
                payload=payload,
                timeout_seconds=cls._timeout_seconds(),
            )
            success = bool(http_status is not None and 200 <= http_status < 300)
        except Exception as exc:
            http_status = None
            latency_ms = None
            success = False
            error_detail = cls._safe_error_detail(exc)

        cls._record_attempt(
            connection=connection,
            event_type=event_type,
            payload_preview=payload_preview,
            http_status=http_status,
            success=success,
            error_detail=error_detail,
            latency_ms=latency_ms,
            attempted_at=attempted_at,
        )

    @classmethod
    def _dispatch_webhook(
        cls,
        *,
        url: str,
        payload: dict,
        timeout_seconds: float,
    ) -> tuple[int | None, int | None, str]:
        started = time.monotonic()
        timeout = httpx.Timeout(timeout_seconds)
        try:
            with cls.http_client_factory(timeout=timeout) as client:
                response = client.post(url, json=payload)
        except httpx.TimeoutException:
            return None, cls._elapsed_ms(started), "timeout"
        except httpx.HTTPError:
            return None, cls._elapsed_ms(started), "http_error"

        error_detail = "" if 200 <= response.status_code < 300 else "non_2xx_response"
        return response.status_code, cls._elapsed_ms(started), error_detail

    @classmethod
    def _build_payload(
        cls,
        *,
        connection: IntegrationConnection,
        event_type: str,
        context: dict,
    ) -> dict:
        safe_context = cls._scrub_value(context)
        if connection.type == IntegrationConnection.Type.SLACK_WEBHOOK:
            return cls._build_slack_payload(event_type=event_type, context=safe_context)
        if connection.type == IntegrationConnection.Type.GENERIC_WEBHOOK:
            return {
                "occurred_at": timezone.now().isoformat(),
                **safe_context,
                "event_type": event_type,
            }
        return {
            "occurred_at": timezone.now().isoformat(),
            **safe_context,
            "event_type": event_type,
        }

    @classmethod
    def _build_slack_payload(cls, *, event_type: str, context: dict) -> dict:
        execution_id = (
            context.get("execution_id")
            or context.get("approval_request_id")
            or "unknown"
        )
        status = context.get("execution_status") or context.get("decision") or event_type
        workflow_name = context.get("workflow_name") or "Unknown workflow"
        organization_name = (
            context.get("organization_name") or context.get("org_name") or ""
        )

        lines = [
            f"*Event:* `{event_type}`",
            f"*Workflow:* {workflow_name}",
        ]
        if organization_name:
            lines.append(f"*Organization:* {organization_name}")
        if context.get("failed_step_name"):
            position = context.get("failed_step_position")
            suffix = f" ({position})" if position is not None else ""
            lines.append(f"*Failed step:* {context['failed_step_name']}{suffix}")
        if "has_artifacts" in context:
            artifact_label = "available" if context["has_artifacts"] else "none"
            lines.append(f"*Artifacts:* {artifact_label}")
        if context.get("decision"):
            lines.append(f"*Decision:* {context['decision']}")

        text = f"Runbook event {event_type}: {execution_id} {status}"
        return {
            "text": text,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(lines),
                    },
                }
            ],
        }

    @classmethod
    def _record_attempt(
        cls,
        *,
        connection: IntegrationConnection,
        event_type: str,
        payload_preview: dict,
        http_status: int | None,
        success: bool,
        error_detail: str,
        latency_ms: int | None,
        attempted_at,
    ) -> IntegrationDeliveryAttempt:
        attempt = IntegrationDeliveryAttempt.objects.create(
            integration=connection,
            organization=connection.organization,
            event_type=event_type,
            payload_preview=payload_preview,
            http_status=http_status,
            success=success,
            error_detail=error_detail,
            latency_ms=latency_ms,
            attempted_at=attempted_at,
        )
        connection.last_delivery_at = attempted_at
        connection.last_delivery_status = (
            IntegrationConnection.LastDeliveryStatus.SUCCESS
            if success
            else IntegrationConnection.LastDeliveryStatus.FAILED
        )
        connection.save(
            update_fields=[
                "last_delivery_at",
                "last_delivery_status",
                "updated_at",
            ]
        )
        return attempt

    @classmethod
    def _payload_preview(cls, *, event_type: str, context: dict) -> dict:
        return cls._payload_preview_from_payload({"event_type": event_type, **context})

    @classmethod
    def _payload_preview_from_payload(cls, payload: dict) -> dict:
        scrubbed = cls._scrub_value(payload)
        if isinstance(scrubbed, dict):
            return scrubbed
        return {"payload": scrubbed}

    @classmethod
    def _scrub_value(cls, value: Any):
        if isinstance(value, dict):
            safe = {}
            for key, item in value.items():
                key_text = str(key)
                if cls._is_secret_key(key_text):
                    safe[key_text] = REDACTED
                else:
                    safe[key_text] = cls._scrub_value(item)
            return safe
        if isinstance(value, list):
            return [cls._scrub_value(item) for item in value]
        if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
            return REDACTED
        return value

    @staticmethod
    def _is_secret_key(key: str) -> bool:
        lower_key = key.lower()
        return any(fragment in lower_key for fragment in SECRET_KEY_FRAGMENTS)

    @staticmethod
    def _matches_event_type(connection: IntegrationConnection, event_type: str) -> bool:
        return not connection.event_types or event_type in connection.event_types

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    @staticmethod
    def _timeout_seconds() -> float:
        return float(getattr(settings, "INTEGRATION_DISPATCH_TIMEOUT_SECONDS", 3.0))

    @staticmethod
    def _dispatch_budget_seconds() -> float:
        return float(getattr(settings, "INTEGRATION_DISPATCH_BUDGET_SECONDS", 10.0))

    @staticmethod
    def _max_per_trigger() -> int:
        return max(0, int(getattr(settings, "INTEGRATION_MAX_PER_TRIGGER", 25)))

    @classmethod
    def _dispatch_budget_exhausted(cls, started: float) -> bool:
        budget_seconds = cls._dispatch_budget_seconds()
        if budget_seconds <= 0:
            return True
        return time.monotonic() - started >= budget_seconds

    @staticmethod
    def _safe_error_detail(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return "validation_error"
        return "dispatch_error"

    @classmethod
    def _clean_credentials(cls, type: str, credentials: dict) -> dict:
        if not isinstance(credentials, dict) or not credentials:
            raise ValidationError("Integration credentials are required.")
        if type in {
            IntegrationConnection.Type.SLACK_WEBHOOK,
            IntegrationConnection.Type.GENERIC_WEBHOOK,
        }:
            url = credentials.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValidationError("Integration webhook URL is required.")
            cls.validate_outbound_url(url)
            return {"url": url.strip()}
        return dict(credentials)

    @staticmethod
    def _clean_config(config: dict | None) -> dict:
        if config is None:
            return {}
        if not isinstance(config, dict):
            raise ValidationError("Integration config must be a JSON object.")
        return dict(config)

    @classmethod
    def _clean_event_types(cls, event_types: list[str] | None) -> list[str]:
        if event_types is None:
            return []
        if not isinstance(event_types, list):
            raise ValidationError("Integration event types must be a list.")
        cleaned = []
        for event_type in event_types:
            if not isinstance(event_type, str) or not event_type.strip():
                raise ValidationError(
                    "Integration event types must be non-empty strings."
                )
            event_type = event_type.strip()
            if event_type not in SUPPORTED_EVENT_TYPES:
                raise ValidationError(
                    f"Unsupported integration event type: {event_type}."
                )
            cleaned.append(event_type)
        return cleaned

    @staticmethod
    def _validate_type(type: str) -> None:
        if type not in {
            IntegrationConnection.Type.SLACK_WEBHOOK,
            IntegrationConnection.Type.GENERIC_WEBHOOK,
        }:
            raise ValidationError("Unsupported integration type.")

    @staticmethod
    def _emit_management_audit(
        *,
        connection: IntegrationConnection,
        event_type: str,
        actor: AuditActor | None,
        metadata: dict,
    ) -> None:
        audit_actor = actor or system_actor("Integration service")
        AuditService.emit(
            organization_id=connection.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type=event_type,
            object_type=AuditEvent.ObjectType.INTEGRATION_CONNECTION,
            object_id=connection.id,
            metadata=metadata,
        )
