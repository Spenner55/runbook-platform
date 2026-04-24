"""Structured JSON log emission for runner execution lifecycle events."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record to stdout."""

    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "ts": _utcnow(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge any extra context fields attached by LoggerAdapter
        extra = getattr(record, "_extra", {})
        base.update(extra)

        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(base, default=str)


def configure_logging(level: str = "INFO", runner_id: str = "", runner_version: str = "") -> logging.Logger:
    """Set up JSON logging to stdout. Returns the root runner logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger("runner")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]
    root.propagate = False

    return root


class LogStreamer:
    """Helpers that attach stable execution/step context to structured log lines."""

    def __init__(
        self,
        base_logger: logging.Logger,
        runner_id: str = "",
        runner_version: str = "",
    ) -> None:
        self._logger = base_logger
        self._runner_id = runner_id
        self._runner_version = runner_version

    def _log(
        self,
        level: int,
        event: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        ctx: dict[str, Any] = {
            "event": event,
            "runner_id": self._runner_id,
            "runner_version": self._runner_version,
        }
        if extra:
            ctx.update(extra)

        record = self._logger.makeRecord(
            name=self._logger.name,
            level=level,
            fn="",
            lno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        record._extra = ctx  # type: ignore[attr-defined]
        self._logger.handle(record)

    # ------------------------------------------------------------------
    # Runner lifecycle
    # ------------------------------------------------------------------

    def runner_started(self) -> None:
        self._log(logging.INFO, "runner_started", "Runner process started")

    def poll_cycle_started(self) -> None:
        self._log(logging.DEBUG, "runner_poll_cycle_started", "Poll cycle started")

    def no_work_available(self, poll_after_seconds: int) -> None:
        self._log(
            logging.DEBUG,
            "runner_no_work_available",
            f"No queued executions; sleeping {poll_after_seconds}s",
            {"poll_after_seconds": poll_after_seconds},
        )

    # ------------------------------------------------------------------
    # Execution lifecycle
    # ------------------------------------------------------------------

    def execution_claim_received(self, execution_id: UUID, step_count: int, claim_token_prefix: str) -> None:
        self._log(
            logging.INFO,
            "execution_claim_received",
            f"Claimed execution {execution_id} ({step_count} step(s))",
            {
                "execution_id": str(execution_id),
                "step_count": step_count,
                "claim_token_prefix": claim_token_prefix,
            },
        )

    def execution_claim_failed(self, error: str) -> None:
        self._log(logging.ERROR, "execution_claim_failed", f"Claim failed: {error}", {"error_message": error})

    def execution_succeeded(self, execution_id: UUID) -> None:
        self._log(
            logging.INFO,
            "execution_succeeded",
            f"Execution {execution_id} succeeded",
            {"execution_id": str(execution_id), "execution_status": "succeeded"},
        )

    def execution_failed(self, execution_id: UUID, error: str = "") -> None:
        self._log(
            logging.WARNING,
            "execution_failed",
            f"Execution {execution_id} failed",
            {"execution_id": str(execution_id), "execution_status": "failed", "error_message": error},
        )

    def execution_terminal_update_failed(self, execution_id: UUID, error: str) -> None:
        self._log(
            logging.ERROR,
            "execution_terminal_update_failed",
            f"Failed to send terminal update for execution {execution_id}: {error}",
            {"execution_id": str(execution_id), "error_message": error},
        )

    # ------------------------------------------------------------------
    # Step lifecycle
    # ------------------------------------------------------------------

    def step_starting(self, execution_id: UUID, step_id: UUID, step_key: str, position: int) -> None:
        self._log(
            logging.INFO,
            "step_starting",
            f"Step {position}/{step_key} starting",
            {
                "execution_id": str(execution_id),
                "step_id": str(step_id),
                "step_key": step_key,
                "position": position,
            },
        )

    def step_succeeded(self, execution_id: UUID, step_id: UUID, step_key: str, position: int) -> None:
        self._log(
            logging.INFO,
            "step_succeeded",
            f"Step {position}/{step_key} succeeded",
            {
                "execution_id": str(execution_id),
                "step_id": str(step_id),
                "step_key": step_key,
                "position": position,
                "step_status": "succeeded",
            },
        )

    def step_failed(self, execution_id: UUID, step_id: UUID, step_key: str, position: int, error: str = "") -> None:
        self._log(
            logging.WARNING,
            "step_failed",
            f"Step {position}/{step_key} failed",
            {
                "execution_id": str(execution_id),
                "step_id": str(step_id),
                "step_key": step_key,
                "position": position,
                "step_status": "failed",
                "error_message": error,
            },
        )

    def step_intentional_failure_triggered(self, execution_id: UUID, step_id: UUID, step_key: str) -> None:
        self._log(
            logging.INFO,
            "step_intentional_failure_triggered",
            f"FAIL_STEP marker detected in step {step_key}",
            {"execution_id": str(execution_id), "step_id": str(step_id), "step_key": step_key},
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat_started(self, execution_id: UUID) -> None:
        self._log(
            logging.DEBUG,
            "heartbeat_started",
            f"Heartbeat started for execution {execution_id}",
            {"execution_id": str(execution_id)},
        )

    def heartbeat_sent(self, execution_id: UUID) -> None:
        self._log(
            logging.DEBUG,
            "heartbeat_sent",
            f"Heartbeat sent for execution {execution_id}",
            {"execution_id": str(execution_id)},
        )

    def heartbeat_failed(self, execution_id: UUID, error: str) -> None:
        self._log(
            logging.WARNING,
            "heartbeat_failed",
            f"Heartbeat failed for execution {execution_id}: {error}",
            {"execution_id": str(execution_id), "error_message": error},
        )
