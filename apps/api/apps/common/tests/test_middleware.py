import uuid

import pytest
from django.test import RequestFactory

from apps.common.middleware import RequestIDMiddleware


def _make_middleware(response_factory=None):
    if response_factory is None:
        from django.http import HttpResponse

        response_factory = lambda req: HttpResponse("ok")  # noqa: E731
    return RequestIDMiddleware(response_factory)


@pytest.fixture
def factory():
    return RequestFactory()


def test_generates_request_id_when_absent(factory):
    middleware = _make_middleware()
    request = factory.get("/")
    response = middleware(request)

    assert hasattr(request, "request_id")
    uuid.UUID(request.request_id)  # raises if not a valid UUID
    assert response["X-Request-ID"] == request.request_id


def test_preserves_incoming_request_id(factory):
    middleware = _make_middleware()
    incoming_id = str(uuid.uuid4())
    request = factory.get("/", HTTP_X_REQUEST_ID=incoming_id)
    response = middleware(request)

    assert request.request_id == incoming_id
    assert response["X-Request-ID"] == incoming_id


def test_different_requests_get_different_ids(factory):
    middleware = _make_middleware()
    r1 = factory.get("/")
    r2 = factory.get("/")
    middleware(r1)
    middleware(r2)

    assert r1.request_id != r2.request_id
