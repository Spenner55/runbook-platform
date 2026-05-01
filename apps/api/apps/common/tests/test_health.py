import json
from unittest.mock import patch

import pytest
from django.core.management.base import CommandError
from django.test import RequestFactory


@pytest.fixture
def factory():
    return RequestFactory()


def _healthy(latency_ms=1.23):
    return {"status": "healthy", "latency_ms": latency_ms}


def _unhealthy(detail="connection refused"):
    return {"status": "unhealthy", "detail": detail}


def test_live_always_returns_200_without_dependency_checks(factory):
    from apps.common.health import live_view

    with (
        patch("apps.common.health._check_db", side_effect=AssertionError),
        patch("apps.common.health._check_ai", side_effect=AssertionError),
        patch("apps.common.health._check_migrations", side_effect=AssertionError),
    ):
        response = live_view(factory.get("/health/live"))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data == {"status": "live", "service": "api"}


@pytest.mark.django_db
def test_readiness_returns_200_when_db_and_migrations_are_healthy(factory):
    from apps.common.health import readiness_view

    with (
        patch("apps.common.health._check_db", return_value=_healthy()),
        patch("apps.common.health._check_migrations", return_value=_healthy()),
    ):
        response = readiness_view(factory.get("/health/ready/"))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["status"] == "ready"
    assert data["checks"]["database"]["status"] == "healthy"
    assert data["checks"]["migrations"]["status"] == "healthy"


@pytest.mark.django_db
def test_readiness_returns_503_when_db_fails(factory):
    from apps.common.health import readiness_view

    with (
        patch("apps.common.health._check_db", return_value=_unhealthy()),
        patch("apps.common.health._check_migrations", return_value=_healthy()),
    ):
        response = readiness_view(factory.get("/health/ready/"))

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["status"] == "not_ready"
    assert data["checks"]["database"]["status"] == "unhealthy"


@pytest.mark.django_db
def test_readiness_returns_503_when_migration_check_fails(factory):
    from apps.common.health import readiness_view

    with (
        patch("apps.common.health._check_db", return_value=_healthy()),
        patch(
            "apps.common.health._check_migrations",
            return_value=_unhealthy("unapplied migrations"),
        ),
    ):
        response = readiness_view(factory.get("/health/ready/"))

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["status"] == "not_ready"
    assert data["checks"]["migrations"]["status"] == "unhealthy"


@pytest.mark.django_db
def test_readiness_returns_200_when_ai_service_down(factory):
    from apps.common.health import readiness_view

    with (
        patch("apps.common.health._check_db", return_value=_healthy()),
        patch("apps.common.health._check_migrations", return_value=_healthy()),
        patch("apps.common.health._check_ai", side_effect=AssertionError),
    ):
        response = readiness_view(factory.get("/health/ready/"))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["status"] == "ready"


@pytest.mark.django_db
def test_health_returns_200_when_all_checks_pass(factory):
    from apps.common.health import detailed_health_view

    with (
        patch("apps.common.health._check_db", return_value=_healthy()),
        patch("apps.common.health._check_ai", return_value=_healthy()),
    ):
        response = detailed_health_view(factory.get("/health/"))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["status"] == "healthy"
    assert data["checks"]["database"]["status"] == "healthy"
    assert data["checks"]["ai_service"]["status"] == "healthy"


@pytest.mark.django_db
def test_health_returns_503_when_db_fails(factory):
    from apps.common.health import detailed_health_view

    with (
        patch("apps.common.health._check_db", return_value=_unhealthy()),
        patch("apps.common.health._check_ai", return_value=_healthy()),
    ):
        response = detailed_health_view(factory.get("/health/"))

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["status"] == "unhealthy"
    assert data["checks"]["database"]["status"] == "unhealthy"


@pytest.mark.django_db
def test_health_returns_503_when_ai_fails(factory):
    from apps.common.health import detailed_health_view

    with (
        patch("apps.common.health._check_db", return_value=_healthy()),
        patch("apps.common.health._check_ai", return_value=_unhealthy("timeout")),
    ):
        response = detailed_health_view(factory.get("/health/"))

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["status"] == "unhealthy"
    assert data["checks"]["ai_service"]["status"] == "unhealthy"


@pytest.mark.django_db
def test_db_check_uses_select_1():
    from apps.common.health import _check_db

    result = _check_db()
    assert result["status"] == "healthy"
    assert result["latency_ms"] >= 0


def test_migration_check_reports_unhealthy_when_migrations_are_pending():
    from apps.common.health import _check_migrations

    with patch("apps.common.health.call_command", side_effect=CommandError("pending")):
        result = _check_migrations()

    assert result == {"status": "unhealthy", "detail": "pending"}
