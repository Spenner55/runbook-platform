"""Runner entry point — load config, wire components, start poll loop."""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import httpx

from runner.client import RUNNER_API_TIMEOUT, ApiClient
from runner.executor import Executor
from runner.log_streamer import LogStreamer, configure_logging
from runner.poller import Poller
from runner.schemas import RunnerSettings
from runner.state import RunnerState

_HARD_SHUTDOWN_TIMEOUT_SECONDS = 60

_root_logger = logging.getLogger("runner")


def _install_sigterm_handler(
    shutdown_event: threading.Event,
) -> None:
    """Set SIGTERM to flag shutdown and start a hard-exit watchdog."""

    def _handle(signum: int, frame: object) -> None:
        _root_logger.critical(
            "SIGTERM received — stopping after current work drains (hard timeout: %ds)",
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


def _ensure_registered(settings: RunnerSettings, api_client: ApiClient) -> None:
    """
    Resolve the canonical runner identity and update the client in-place.

    Order of precedence:
    1. State file (runner_id + bearer_token persisted from a previous registration)
    2. RUNNER_BEARER_TOKEN + RUNNER_REGISTERED_ID env vars (manual / legacy)
    3. Call the registration endpoint using the registration token

    Exits with code 1 if RUNNER_REGISTERED_ID is set but conflicts with the
    canonical runner_id resolved by the server.
    """
    state_path = Path(settings.runner_state_file) if settings.runner_state_file else None

    # --- 1. Try state file ---
    state = RunnerState.load(state_path) if state_path else RunnerState()
    if state.is_registered:
        canonical_runner_id = state.runner_id
        bearer_token = state.runner_bearer_token
        _root_logger.info(
            "Loaded persisted runner identity: runner_id=%s", canonical_runner_id
        )
        _check_runner_id_conflict(settings.registered_runner_id, canonical_runner_id, source="state file")
        api_client.update_identity(canonical_runner_id, bearer_token)
        return

    # --- 2. Try env-configured bearer token (manual / legacy mode) ---
    if settings.runner_bearer_token and settings.registered_runner_id:
        canonical_runner_id = settings.registered_runner_id
        _root_logger.info(
            "Using env-configured runner identity: runner_id=%s", canonical_runner_id
        )
        api_client.update_identity(canonical_runner_id, settings.runner_bearer_token)
        return

    # --- 3. Register with the API ---
    display_name = settings.runner_display_name or settings.runner_id
    fingerprint = (
        settings.runner_install_fingerprint
        or hashlib.sha256(settings.runner_id.encode()).hexdigest()
    )
    hostname = os.uname().nodename

    _root_logger.info(
        "Registering runner display_name=%r hostname=%s", display_name, hostname
    )
    reg_result = api_client.register(
        display_name=display_name,
        fingerprint_sha256=fingerprint,
        hostname=hostname,
        labels={},
        capabilities=[],
    )

    canonical_runner_id = reg_result.get("runner_id", "")
    bearer_token = reg_result.get("runner_bearer_token", "")

    if not canonical_runner_id or not bearer_token:
        _root_logger.critical(
            "Registration response missing runner_id or runner_bearer_token — aborting"
        )
        raise SystemExit(1)

    _check_runner_id_conflict(settings.registered_runner_id, canonical_runner_id, source="registration response")

    # Persist so next startup skips registration
    if state_path:
        new_state = RunnerState(runner_id=canonical_runner_id, runner_bearer_token=bearer_token)
        new_state.save(state_path)
        _root_logger.info(
            "Runner registered as %s — state persisted to %s", canonical_runner_id, state_path
        )
    else:
        _root_logger.info(
            "Runner registered as %s (no state file configured — identity is in-memory only)",
            canonical_runner_id,
        )

    api_client.update_identity(canonical_runner_id, bearer_token)


def _check_runner_id_conflict(
    configured_id: str, canonical_id: str, *, source: str
) -> None:
    """Raise SystemExit(1) if an explicitly configured runner ID doesn't match the canonical one."""
    if configured_id and configured_id != canonical_id:
        _root_logger.critical(
            "RUNNER_REGISTERED_ID=%s conflicts with canonical runner_id=%s from %s — aborting",
            configured_id,
            canonical_id,
            source,
        )
        raise SystemExit(1)


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

    # Initialise client with the registration token; _ensure_registered will
    # switch it to the per-runner bearer token before any other calls are made.
    with httpx.Client(timeout=RUNNER_API_TIMEOUT) as http_client:
        api_client = ApiClient(
            base_url=settings.api_base_url,
            runner_id=settings.runner_id,
            runner_token=settings.registration_token or settings.runner_bearer_token,
            runner_version=settings.runner_version,
            http_client=http_client,
            api_retries_enabled=settings.api_retries_enabled,
            retry_sleep=shutdown_event.wait,
        )

        _ensure_registered(settings, api_client)

        executor = Executor(client=api_client, settings=settings)
        poller = Poller(
            client=api_client,
            executor=executor,
            poll_interval_seconds=settings.poll_interval_seconds,
            shutdown_event=shutdown_event,
            runner_heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        )

        poller.run_forever()


if __name__ == "__main__":
    main()
