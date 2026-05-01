"""Runner entry point — load config, wire components, start poll loop."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

import httpx

from runner.client import RUNNER_API_TIMEOUT, ApiClient
from runner.executor import Executor
from runner.log_streamer import LogStreamer, configure_logging
from runner.poller import Poller
from runner.schemas import RunnerSettings

_HARD_SHUTDOWN_TIMEOUT_SECONDS = 60

_root_logger = logging.getLogger("runner")


def _install_sigterm_handler(
    shutdown_event: threading.Event,
) -> None:
    """Set SIGTERM to flag shutdown and start a hard-exit watchdog."""

    def _handle(signum: int, frame: object) -> None:
        _root_logger.critical(
            "SIGTERM received — stopping after current work drains "
            "(hard timeout: %ds)",
            _HARD_SHUTDOWN_TIMEOUT_SECONDS,
        )
        shutdown_event.set()

        def _force_exit() -> None:
            time.sleep(_HARD_SHUTDOWN_TIMEOUT_SECONDS)
            _root_logger.critical(
                "Hard shutdown timeout (%ds) reached — forcing exit. "
                "Any stuck execution will be recovered by the Django watchdog.",
                _HARD_SHUTDOWN_TIMEOUT_SECONDS,
            )
            os._exit(1)

        t = threading.Thread(target=_force_exit, daemon=True, name="shutdown-watchdog")
        t.start()

    signal.signal(signal.SIGTERM, _handle)


def main() -> None:
    try:
        settings = RunnerSettings.from_env()
    except Exception as exc:
        print(f"CRITICAL startup validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

    settings.validate_for_startup()

    base_logger = configure_logging(
        level=settings.log_level,
        runner_id=settings.runner_id,
        runner_version=settings.runner_version,
    )
    log = LogStreamer(
        base_logger=base_logger,
        runner_id=settings.runner_id,
        runner_version=settings.runner_version,
    )

    log.runner_started()

    shutdown_event = threading.Event()
    _install_sigterm_handler(shutdown_event)

    with httpx.Client(timeout=RUNNER_API_TIMEOUT) as http_client:
        api_client = ApiClient(
            base_url=settings.api_base_url,
            runner_id=settings.runner_id,
            runner_token=settings.registration_token,
            runner_version=settings.runner_version,
            http_client=http_client,
            api_retries_enabled=settings.api_retries_enabled,
            retry_sleep=shutdown_event.wait,
        )
        executor = Executor(client=api_client)
        poller = Poller(
            client=api_client,
            executor=executor,
            poll_interval_seconds=settings.poll_interval_seconds,
            shutdown_event=shutdown_event,
        )

        poller.run_forever()


if __name__ == "__main__":
    main()
