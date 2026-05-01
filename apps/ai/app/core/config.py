"""
AI service runtime configuration.

All values are read from environment variables.
Defaults are safe: LLM is disabled, no API key assumed.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Safety gate: set to true only when OPENAI_API_KEY is also provided.
    AI_USE_LLM_PARSER: bool = False

    # Enables @pytest.mark.llm tests. Never set true in CI unless costs are accepted.
    AI_ENABLE_LLM_TESTS: bool = False

    # Must be set manually by the operator before enabling LLM parsing.
    OPENAI_API_KEY: str = ""

    # Model selection is a human decision — no default is intentional.
    AI_PARSE_MODEL: str = ""

    # Health checks use a non-generative OpenAI endpoint and cache the result
    # briefly so container health probes do not amplify provider traffic.
    AI_HEALTH_OPENAI_TIMEOUT_SECONDS: float = 2.0
    AI_HEALTH_OPENAI_CACHE_SECONDS: float = 30.0

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
