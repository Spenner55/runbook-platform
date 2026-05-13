"""Handler for the http_request action type (pilot.v1)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError

logger = logging.getLogger(__name__)

_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_RESPONSE_BODY_BYTES = 1_048_576  # 1 MB cap
_DEFAULT_TIMEOUT_SECONDS = 30


class HttpRequestHandler:
    """Make an HTTP request. Enforces HTTPS, method allowlist, and response body cap."""

    def validate(self, params: dict[str, Any]) -> None:
        url = params.get("url")
        if not url or not isinstance(url, str):
            raise ActionValidationError("http_request requires a non-empty 'url' param")
        if not url.startswith("https://"):
            raise ActionValidationError(
                f"http_request requires an HTTPS URL, got: {url!r}"
            )

        method = (params.get("method") or "GET").upper()
        if method not in _ALLOWED_METHODS:
            raise ActionValidationError(
                f"http_request 'method' must be one of {sorted(_ALLOWED_METHODS)}, "
                f"got {method!r}"
            )

        headers = params.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ActionValidationError(
                "http_request 'headers' must be a dict when present"
            )

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        params = ctx.step.action_snapshot.params if ctx.step.action_snapshot else {}

        if (
            ctx.execution.execution_mode == "dry_run"
            or params.get("dry_run")
            or params.get("validate_only")
        ):
            logger.info(
                "http_request: step %d/%s dry_run - skipping live request",
                ctx.step.position,
                ctx.step.name,
            )
            return ActionResult(status="succeeded", exit_code=0)

        url = params.get("url", "")
        method = (params.get("method") or "GET").upper()
        headers: dict[str, str] = params.get("headers") or {}

        if method in _MUTATING_METHODS:
            has_idempotency = ctx.step.idempotency is not None
            has_approval = ctx.step.requires_approval
            if not has_idempotency and not has_approval:
                return ActionResult(
                    status="failed",
                    exit_code=None,
                    error_message=(
                        f"http_request with mutating method {method!r} requires either "
                        "an idempotency spec or requires_approval=true on the step"
                    ),
                    failure_kind="policy_blocked",
                )

        body_param = params.get("body")
        if isinstance(body_param, str):
            content = body_param.encode()
        elif isinstance(body_param, dict):
            content = json.dumps(body_param).encode()
            if "content-type" not in {k.lower() for k in headers}:
                headers = {**headers, "Content-Type": "application/json"}
        else:
            content = None

        timeout_seconds = float(
            ctx.step.timeout_seconds
            if ctx.step.timeout_seconds and ctx.step.timeout_seconds > 0
            else _DEFAULT_TIMEOUT_SECONDS
        )

        try:
            with httpx.Client(timeout=timeout_seconds) as http:
                response = http.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=content,
                )
                _body = response.content[:_MAX_RESPONSE_BODY_BYTES]

            logger.info(
                "http_request: step %d/%s %s %s → HTTP %d (%d bytes)",
                ctx.step.position,
                ctx.step.name,
                method,
                url,
                response.status_code,
                len(_body),
            )
            expected = params.get("expected_status_codes") or [200]
            if response.status_code not in expected:
                return ActionResult(
                    status="failed",
                    exit_code=None,
                    error_message=(
                        f"HTTP status {response.status_code} did not match expected "
                        f"status codes {expected}"
                    ),
                    failure_kind="http_status_unexpected",
                )
            return ActionResult(status="succeeded", exit_code=0)

        except httpx.TimeoutException as exc:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=f"HTTP request timed out: {exc}",
                failure_kind="timeout",
            )
        except httpx.HTTPError as exc:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=f"HTTP request failed: {exc}",
                failure_kind="action_failed",
            )
