from fastapi.testclient import TestClient

from app.api.routes import health as health_route
from app.core.config import settings
from app.main import app

client = TestClient(app)


def _reset_settings() -> None:
    settings.AI_USE_LLM_PARSER = False
    settings.OPENAI_API_KEY = ""
    settings.AI_PARSE_MODEL = ""
    settings.AI_HEALTH_OPENAI_TIMEOUT_SECONDS = 2.0
    settings.AI_HEALTH_OPENAI_CACHE_SECONDS = 30.0
    health_route._clear_openai_health_cache()


def test_health_reports_disabled_openai_when_llm_parser_is_off():
    _reset_settings()

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ai"
    assert body["checks"]["openai"] == {
        "status": "disabled",
        "mode": "disabled",
        "detail": "LLM parsing is disabled.",
    }


def test_health_reports_degraded_when_llm_parser_is_missing_config():
    _reset_settings()
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "test-key"

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["openai"]["status"] == "not_configured"
    assert body["checks"]["openai"]["mode"] == "configured"
    assert "AI_PARSE_MODEL" in body["checks"]["openai"]["detail"]
    assert "test-key" not in body["checks"]["openai"]["detail"]


def test_health_reports_openai_connectivity_success(monkeypatch):
    _reset_settings()
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_PARSE_MODEL = "gpt-test"

    class FakeModels:
        def list(self):
            return object()

    def build_fake_openai_client():
        return type("FakeOpenAI", (), {"models": FakeModels()})()

    monkeypatch.setattr(health_route, "_build_openai_client", build_fake_openai_client)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["openai"] == {
        "status": "ok",
        "mode": "connectivity_checked",
        "detail": "OpenAI models endpoint reachable.",
    }


def test_health_reports_degraded_when_openai_connectivity_fails(monkeypatch):
    _reset_settings()
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "secret-test-key"
    settings.AI_PARSE_MODEL = "gpt-test"

    class FakeModels:
        def list(self):
            raise RuntimeError("secret-test-key failed")

    def build_fake_openai_client():
        return type("FakeOpenAI", (), {"models": FakeModels()})()

    monkeypatch.setattr(health_route, "_build_openai_client", build_fake_openai_client)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["openai"] == {
        "status": "degraded",
        "mode": "connectivity_checked",
        "detail": "OpenAI connectivity check failed: RuntimeError.",
    }


def test_health_caches_openai_connectivity_result(monkeypatch):
    _reset_settings()
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_PARSE_MODEL = "gpt-test"

    calls = 0

    class FakeModels:
        def list(self):
            nonlocal calls
            calls += 1
            return object()

    def build_fake_openai_client():
        return type("FakeOpenAI", (), {"models": FakeModels()})()

    monkeypatch.setattr(health_route, "_build_openai_client", build_fake_openai_client)

    assert client.get("/health").json()["checks"]["openai"]["status"] == "ok"
    assert client.get("/health").json()["checks"]["openai"]["status"] == "ok"
    assert calls == 1


def test_health_does_not_call_generation_or_parser_code(monkeypatch):
    _reset_settings()
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_PARSE_MODEL = "gpt-test"

    class ForbiddenChatCompletions:
        def create(self, **_kwargs):
            raise AssertionError("health must not call chat completions")

        def parse(self, **_kwargs):
            raise AssertionError("health must not call structured completions")

    class ForbiddenChat:
        completions = ForbiddenChatCompletions()

    class FakeModels:
        def list(self):
            return object()

    def build_fake_openai_client():
        return type(
            "FakeOpenAI",
            (),
            {
                "chat": ForbiddenChat(),
                "models": FakeModels(),
            },
        )()

    monkeypatch.setattr(health_route, "_build_openai_client", build_fake_openai_client)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["checks"]["openai"]["mode"] == "connectivity_checked"
