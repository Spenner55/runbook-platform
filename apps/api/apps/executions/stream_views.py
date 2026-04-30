import asyncio
import json
import logging
from uuid import UUID

from asgiref.sync import sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views import View
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.executions.event_bus import (
    StreamEvent,
    execution_event_bus,
    set_asgi_event_loop,
)
from apps.executions.models import Execution
from apps.organizations.models import Membership

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 25
SSE_RETRY_MILLISECONDS = 3000
TERMINAL_STATUSES = {
    Execution.Status.SUCCEEDED,
    Execution.Status.FAILED,
    Execution.Status.CANCELLED,
}


class StreamExecutionView(View):
    """Authenticated Server-Sent Events stream for one execution."""

    async def get(self, request, execution_id):
        logger.info(
            "execution_stream.open_attempt",
            extra={"execution_id": str(execution_id)},
        )
        auth_result = await _authenticate_request(request)
        if auth_result is None:
            logger.warning(
                "execution_stream.auth_missing",
                extra={"execution_id": str(execution_id)},
            )
            return _json_error(
                "Authentication credentials were not provided.",
                status=401,
            )
        if isinstance(auth_result, JsonResponse):
            logger.warning(
                "execution_stream.auth_failed",
                extra={"execution_id": str(execution_id)},
            )
            return auth_result
        user = auth_result

        organization_id = _organization_id_from_request(request)
        if organization_id is None:
            logger.warning(
                "execution_stream.organization_missing",
                extra={"execution_id": str(execution_id), "user_id": str(user.id)},
            )
            return _json_error("X-Organization-Id header is required.", status=400)

        execution = await _get_execution(execution_id)
        if execution is None:
            logger.warning(
                "execution_stream.execution_not_found",
                extra={
                    "execution_id": str(execution_id),
                    "organization_id": organization_id,
                    "user_id": str(user.id),
                },
            )
            return _json_error("Not found.", status=404)

        if str(execution.organization_id) != organization_id:
            logger.warning(
                "execution_stream.organization_mismatch",
                extra={
                    "execution_id": str(execution.id),
                    "organization_id": organization_id,
                    "execution_organization_id": str(execution.organization_id),
                    "user_id": str(user.id),
                },
            )
            return _json_error("You are not a member of this organization.", status=403)

        is_member = await _is_member(user_id=user.id, organization_id=organization_id)
        if not is_member:
            logger.warning(
                "execution_stream.membership_rejected",
                extra={
                    "execution_id": str(execution.id),
                    "organization_id": organization_id,
                    "user_id": str(user.id),
                },
            )
            return _json_error("You are not a member of this organization.", status=403)

        logger.info(
            "execution_stream.accepted",
            extra={
                "execution_id": str(execution.id),
                "organization_id": organization_id,
                "user_id": str(user.id),
            },
        )
        response = StreamingHttpResponse(
            _event_stream(
                execution=execution,
                organization_id=organization_id,
                last_event_id=_last_event_id_from_request(request),
            ),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        response["Connection"] = "keep-alive"
        return response


async def _authenticate_request(request):
    try:
        result = await sync_to_async(_authenticate_request_sync)(request)
    except (AuthenticationFailed, NotAuthenticated) as exc:
        return _json_error(str(exc.detail), status=401)
    if result is None:
        return None
    user, _token = result
    return user


def _authenticate_request_sync(request):
    try:
        return JWTAuthentication().authenticate(request)
    finally:
        close_old_connections()


def _organization_id_from_request(request) -> str | None:
    raw_value = request.headers.get("X-Organization-Id")
    if not raw_value:
        return None
    try:
        return str(UUID(str(raw_value)))
    except (TypeError, ValueError):
        return None


def _last_event_id_from_request(request) -> str | None:
    return (
        request.headers.get("Last-Event-ID")
        or request.headers.get("Last-Event-Id")
        or request.META.get("HTTP_LAST_EVENT_ID")
    )


async def _get_execution(execution_id):
    return await sync_to_async(_get_execution_sync)(execution_id)


def _get_execution_sync(execution_id):
    try:
        return (
            Execution.objects.select_related("organization")
            .filter(pk=execution_id)
            .first()
        )
    finally:
        close_old_connections()


async def _is_member(*, user_id, organization_id) -> bool:
    return await sync_to_async(_is_member_sync)(
        user_id=user_id, organization_id=organization_id
    )


def _is_member_sync(*, user_id, organization_id) -> bool:
    try:
        return Membership.objects.filter(
            user_id=user_id, organization_id=organization_id
        ).exists()
    finally:
        close_old_connections()


async def _event_stream(
    *,
    execution: Execution,
    organization_id: str,
    last_event_id: str | None,
):
    loop = asyncio.get_running_loop()
    set_asgi_event_loop(loop)

    if execution.status in TERMINAL_STATUSES:
        yield f"retry: {SSE_RETRY_MILLISECONDS}\n\n"
        for event in _terminal_events(execution):
            logger.info(
                "execution_stream.event_sent",
                extra={
                    "execution_id": str(execution.id),
                    "organization_id": organization_id,
                    "event_type": event.event_type,
                    "event_id": event.id,
                    "terminal_snapshot": True,
                },
            )
            yield _format_sse_event(event)
        logger.info(
            "execution_stream.closed",
            extra={
                "execution_id": str(execution.id),
                "organization_id": organization_id,
                "reason": "already_terminal",
            },
        )
        return

    queue = await execution_event_bus.subscribe(
        str(execution.id), organization_id=organization_id
    )
    logger.info(
        "execution_stream.subscribed",
        extra={
            "execution_id": str(execution.id),
            "organization_id": organization_id,
        },
    )
    try:
        yield f"retry: {SSE_RETRY_MILLISECONDS}\n\n"

        for event in execution_event_bus.get_buffered_events_after(
            str(execution.id), last_event_id
        ):
            logger.info(
                "execution_stream.event_sent",
                extra={
                    "execution_id": str(execution.id),
                    "organization_id": organization_id,
                    "event_type": event.event_type,
                    "event_id": event.id,
                    "replayed": True,
                },
            )
            yield _format_sse_event(event)
            if _closes_stream(event):
                logger.info(
                    "execution_stream.closed",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                        "reason": "replayed_closed_event",
                    },
                )
                return
            if _is_terminal_status_event(event):
                close_event = _stream_closed_event(
                    execution_id=str(execution.id),
                    final_status=event.data["status"],
                )
                logger.info(
                    "execution_stream.event_sent",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                        "event_type": close_event.event_type,
                        "event_id": close_event.id,
                        "replayed": True,
                    },
                )
                yield _format_sse_event(close_event)
                logger.info(
                    "execution_stream.closed",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                        "reason": "replayed_terminal_status",
                    },
                )
                return

        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except TimeoutError:
                reconciled = await _get_execution(execution.id)
                if reconciled is not None and reconciled.status in TERMINAL_STATUSES:
                    for terminal_event in _terminal_events(reconciled):
                        logger.info(
                            "execution_stream.event_sent",
                            extra={
                                "execution_id": str(reconciled.id),
                                "organization_id": organization_id,
                                "event_type": terminal_event.event_type,
                                "event_id": terminal_event.id,
                                "terminal_snapshot": True,
                                "reconciled": True,
                            },
                        )
                        yield _format_sse_event(terminal_event)
                    logger.info(
                        "execution_stream.closed",
                        extra={
                            "execution_id": str(execution.id),
                            "organization_id": organization_id,
                            "reason": "db_terminal_reconciled",
                        },
                    )
                    return
                logger.debug(
                    "execution_stream.heartbeat_sent",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                    },
                )
                yield _format_heartbeat(str(execution.id))
                continue

            logger.info(
                "execution_stream.event_sent",
                extra={
                    "execution_id": str(execution.id),
                    "organization_id": organization_id,
                    "event_type": event.event_type,
                    "event_id": event.id,
                    "replayed": False,
                },
            )
            yield _format_sse_event(event)
            if _closes_stream(event):
                logger.info(
                    "execution_stream.closed",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                        "reason": "closed_event",
                    },
                )
                return
            if _is_terminal_status_event(event):
                close_event = _stream_closed_event(
                    execution_id=str(execution.id),
                    final_status=event.data["status"],
                )
                logger.info(
                    "execution_stream.event_sent",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                        "event_type": close_event.event_type,
                        "event_id": close_event.id,
                        "replayed": False,
                    },
                )
                yield _format_sse_event(close_event)
                logger.info(
                    "execution_stream.closed",
                    extra={
                        "execution_id": str(execution.id),
                        "organization_id": organization_id,
                        "reason": "terminal_status",
                    },
                )
                return
    finally:
        await execution_event_bus.unsubscribe(str(execution.id), queue)
        logger.info(
            "execution_stream.unsubscribed",
            extra={
                "execution_id": str(execution.id),
                "organization_id": organization_id,
            },
        )


def _terminal_events(execution: Execution) -> list[StreamEvent]:
    timestamp = (
        execution.finished_at.isoformat()
        if execution.finished_at
        else timezone.now().isoformat()
    )
    return [
        StreamEvent(
            event_type="execution.status_changed",
            data={
                "execution_id": str(execution.id),
                "status": execution.status,
                "timestamp": timestamp,
                "started_at": execution.started_at.isoformat()
                if execution.started_at
                else None,
                "finished_at": execution.finished_at.isoformat()
                if execution.finished_at
                else None,
            },
        ),
        _stream_closed_event(
            execution_id=str(execution.id),
            final_status=execution.status,
            timestamp=timestamp,
        ),
    ]


def _stream_closed_event(
    *,
    execution_id: str,
    final_status: str,
    timestamp: str | None = None,
) -> StreamEvent:
    return StreamEvent(
        event_type="stream.closed",
        data={
            "execution_id": execution_id,
            "final_status": final_status,
            "timestamp": timestamp or timezone.now().isoformat(),
            "reason": "terminal_state",
        },
    )


def _format_sse_event(event: StreamEvent) -> str:
    return (
        f"id: {event.id}\n"
        f"event: {event.event_type}\n"
        f"data: {json.dumps(event.data, cls=DjangoJSONEncoder, separators=(',', ':'))}\n\n"
    )


def _format_heartbeat(execution_id: str) -> str:
    data = {
        "execution_id": execution_id,
        "timestamp": timezone.now().isoformat(),
    }
    return (
        "event: execution.heartbeat\n"
        f"data: {json.dumps(data, cls=DjangoJSONEncoder, separators=(',', ':'))}\n\n"
    )


def _closes_stream(event: StreamEvent) -> bool:
    return event.event_type == "stream.closed"


def _is_terminal_status_event(event: StreamEvent) -> bool:
    return (
        event.event_type == "execution.status_changed"
        and event.data.get("status") in TERMINAL_STATUSES
    )


def _json_error(detail: str, *, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)
