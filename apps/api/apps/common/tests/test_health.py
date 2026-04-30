import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory


@pytest.fixture
def factory():
    return RequestFactory()


@pytest.mark.django_db
def test_health_returns_200_when_all_ok(factory):
    from apps.common.health import detailed_health_view

    with patch("apps.common.health._check_db", return_value=(True, "ok")), patch(
        "apps.common.health._check_ai", return_value=(True, "ok")
    ):
        response = detailed_health_view(factory.get("/health/"))

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["healthy"] is True
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["ai"] == "ok"


@pytest.mark.django_db
def test_health_returns_503_when_db_fails(factory):
    from apps.common.health import detailed_health_view

    with patch(
        "apps.common.health._check_db", return_value=(False, "connection refused")
    ), patch("apps.common.health._check_ai", return_value=(True, "ok")):
        response = detailed_health_view(factory.get("/health/"))

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["healthy"] is False
    assert data["checks"]["db"] == "connection refused"


@pytest.mark.django_db
def test_health_returns_503_when_ai_fails(factory):
    from apps.common.health import detailed_health_view

    with patch("apps.common.health._check_db", return_value=(True, "ok")), patch(
        "apps.common.health._check_ai", return_value=(False, "timeout")
    ):
        response = detailed_health_view(factory.get("/health/"))

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["healthy"] is False
    assert data["checks"]["ai"] == "timeout"


@pytest.mark.django_db
def test_db_check_uses_select_1():
    from apps.common.health import _check_db

    ok, status = _check_db()
    assert ok is True
    assert status == "ok"
