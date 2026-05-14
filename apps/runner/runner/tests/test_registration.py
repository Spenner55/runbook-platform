"""Tests for runner registration flow, state persistence, and identity management."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from runner.client import ApiClient
from runner.main import _check_runner_id_conflict, _ensure_registered
from runner.poller import Poller
from runner.schemas import RunnerSettings
from runner.state import RunnerState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANONICAL_ID = str(uuid4())
_BEARER_TOKEN = "per-runner-bearer-token"

_REG_RESPONSE = {
    "runner_id": _CANONICAL_ID,
    "runner_bearer_token": _BEARER_TOKEN,
}


def _make_settings(**overrides) -> RunnerSettings:
    defaults = {
        "api_base_url": "http://api:8000",
        "runner_id": "runner-local",
        "registration_token": "reg-token-abc",
    }
    defaults.update(overrides)
    return RunnerSettings(**defaults)


def _make_client(transport: httpx.MockTransport | None = None, **overrides) -> ApiClient:
    if transport is None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, json=_REG_RESPONSE)
        )
    http = httpx.Client(transport=transport)
    return ApiClient(
        base_url="http://api:8000",
        runner_id="runner-local",
        runner_token="reg-token-abc",
        http_client=http,
        **overrides,
    )


# ---------------------------------------------------------------------------
# 1. Registration persists returned runner ID and token
# ---------------------------------------------------------------------------


def test_registration_persists_runner_id_and_token(tmp_path):
    state_file = tmp_path / "runner.state.json"
    settings = _make_settings(runner_state_file=str(state_file))
    client = _make_client()

    _ensure_registered(settings, client)

    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["runner_id"] == _CANONICAL_ID
    assert data["runner_bearer_token"] == _BEARER_TOKEN


def test_registration_skipped_when_state_file_exists(tmp_path):
    state_file = tmp_path / "runner.state.json"
    existing = RunnerState(runner_id=_CANONICAL_ID, runner_bearer_token=_BEARER_TOKEN)
    existing.save(state_file)

    call_count = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=_REG_RESPONSE)

    settings = _make_settings(runner_state_file=str(state_file))
    client = _make_client(httpx.MockTransport(handler))

    _ensure_registered(settings, client)

    assert call_count == 0, "register() must not be called when state file has valid identity"


def test_state_file_not_created_when_path_not_configured():
    """When RUNNER_STATE_FILE is empty, registration result lives in memory only."""
    settings = _make_settings()  # no runner_state_file
    client = _make_client()

    _ensure_registered(settings, client)

    assert client.runner_id == _CANONICAL_ID


# ---------------------------------------------------------------------------
# 2. Claim requests use authenticated canonical identity
# ---------------------------------------------------------------------------


def test_claim_uses_canonical_runner_id_after_registration():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/register/"):
            return httpx.Response(200, json=_REG_RESPONSE)
        # claim-next
        payload = json.loads(req.content)
        captured["runner_id"] = payload.get("runner_id")
        captured["auth"] = req.headers.get("Authorization")
        return httpx.Response(200, json={"execution": None, "poll_after_seconds": 5})

    settings = _make_settings()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = ApiClient(
        base_url="http://api:8000",
        runner_id="runner-local",
        runner_token="reg-token-abc",
        http_client=http,
    )

    _ensure_registered(settings, client)
    client.claim_next()

    assert captured["runner_id"] == _CANONICAL_ID
    assert captured["auth"] == f"Bearer {_BEARER_TOKEN}"


# ---------------------------------------------------------------------------
# 3. Idle heartbeat is sent while poller is running
# ---------------------------------------------------------------------------


def test_idle_heartbeat_is_sent():
    hb_calls: list = []

    client = MagicMock()
    client.runner_heartbeat.side_effect = lambda **_: hb_calls.append(1)

    shutdown = threading.Event()
    poller = Poller(
        client=client,
        executor=MagicMock(),
        poll_interval_seconds=5,
        shutdown_event=shutdown,
        runner_heartbeat_interval_seconds=999,  # large — we mock sleep to skip it
    )

    # Patch time.sleep so the heartbeat loop doesn't actually wait, then set
    # shutdown after two iterations so the loop exits.
    call_count = 0

    def fake_sleep(_duration: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            shutdown.set()

    with patch("runner.poller.time.sleep", side_effect=fake_sleep):
        poller._run_heartbeat_loop()

    assert len(hb_calls) >= 1, "runner_heartbeat() must be called at least once while idle"


# ---------------------------------------------------------------------------
# 4. Mismatched canonical runner ID is fatal
# ---------------------------------------------------------------------------


def test_mismatched_registered_runner_id_is_fatal():
    """RUNNER_REGISTERED_ID that conflicts with canonical runner_id → SystemExit(1)."""
    settings = _make_settings(registered_runner_id="some-other-uuid-that-differs")
    client = _make_client()

    with pytest.raises(SystemExit) as exc_info:
        _ensure_registered(settings, client)

    assert exc_info.value.code == 1


def test_check_runner_id_conflict_no_conflict_passes():
    _check_runner_id_conflict("", _CANONICAL_ID, source="test")  # no configured id — OK
    _check_runner_id_conflict(_CANONICAL_ID, _CANONICAL_ID, source="test")  # match — OK


def test_check_runner_id_conflict_mismatch_raises():
    with pytest.raises(SystemExit) as exc_info:
        _check_runner_id_conflict("other-id", _CANONICAL_ID, source="test")
    assert exc_info.value.code == 1


def test_mismatched_state_file_runner_id_is_fatal(tmp_path):
    """If state file has a runner_id but RUNNER_REGISTERED_ID differs, fatal."""
    state_file = tmp_path / "runner.state.json"
    RunnerState(runner_id=_CANONICAL_ID, runner_bearer_token=_BEARER_TOKEN).save(state_file)

    settings = _make_settings(
        runner_state_file=str(state_file),
        registered_runner_id="completely-different-id",
    )
    client = _make_client()

    with pytest.raises(SystemExit) as exc_info:
        _ensure_registered(settings, client)

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 5. Execution heartbeat behavior remains unchanged
# ---------------------------------------------------------------------------


def test_execution_heartbeat_uses_claim_token():
    """client.heartbeat() must still send claim_token for execution ownership."""
    captured = {}
    execution_id = uuid4()
    claim_token = uuid4()

    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.content)
        captured["runner_id"] = payload.get("runner_id")
        captured["claim_token"] = payload.get("claim_token")
        captured["observed_status"] = payload.get("observed_status")
        return httpx.Response(
            200,
            json={
                "execution_id": str(execution_id),
                "status": "running",
                "last_heartbeat_at": "2026-01-01T00:00:00Z",
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = ApiClient(
        base_url="http://api:8000",
        runner_id="runner-local",
        runner_token="reg-token-abc",
        http_client=http,
    )
    # Simulate post-registration identity
    client.update_identity(_CANONICAL_ID, _BEARER_TOKEN)

    client.heartbeat(execution_id, claim_token, observed_status="running")

    assert captured["runner_id"] == _CANONICAL_ID
    assert captured["claim_token"] == str(claim_token)
    assert captured["observed_status"] == "running"


def test_update_identity_switches_runner_id_and_auth_header():
    client = _make_client()
    assert client.runner_id == "runner-local"

    client.update_identity("canonical-uuid-123", "new-bearer")

    assert client.runner_id == "canonical-uuid-123"
    # Verify auth header is used in requests
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["auth"] = req.headers.get("Authorization")
        captured["runner_id_header"] = req.headers.get("X-Runner-ID")
        return httpx.Response(200, json={"execution": None, "poll_after_seconds": 5})

    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    client.claim_next()

    assert captured["auth"] == "Bearer new-bearer"
    assert captured["runner_id_header"] == "canonical-uuid-123"
