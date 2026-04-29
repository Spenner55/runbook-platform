# AI Parsing Safety Guide

## Overview

The AI parsing layer is **disabled by default**. No LLM calls are made, no API key is
required, and all tests pass without any external dependencies. Enabling LLM parsing
is an explicit, opt-in human decision.

---

## Default behaviour

| Flag | Default | Effect |
|---|---|---|
| `AI_USE_LLM_PARSER` | `false` | Deterministic regex parser is used. No OpenAI calls. |
| `AI_ENABLE_LLM_TESTS` | `false` | Tests marked `@pytest.mark.llm` are skipped. |
| `OPENAI_API_KEY` | *(empty)* | Not required. Missing key does not fail tests or startup. |
| `AI_PARSE_MODEL` | *(empty)* | Not required. No model is assumed. |

---

## How to enable LLM parsing (local dev only)

Complete **all four steps** in order. Skipping any one will result in a clear error.

### Step 1 — Set your API key

```bash
# In your local .env file (never commit this)
OPENAI_API_KEY=sk-...
```

### Step 2 — Choose a model

Model selection is intentionally left to the operator. Choose based on your cost and
quality requirements.

```bash
# In your local .env file
AI_PARSE_MODEL=gpt-4o        # highest quality, higher cost
# AI_PARSE_MODEL=gpt-4o-mini  # lower cost, acceptable quality for most runbooks
```

### Step 3 — Enable LLM parsing

```bash
# In your local .env file
AI_USE_LLM_PARSER=true
```

### Step 4 — Restart the AI service

```bash
docker compose restart ai
```

### Verification

```bash
curl -s http://localhost:8001/health | jq .
```

---

## How to run LLM integration tests

> **Cost warning**: each test invocation makes real API calls to OpenAI.
> Do **not** enable this in CI without explicit budget approval and spending limits set
> on your OpenAI account.

```bash
# In your shell (or .env.test — never .env.example or CI secrets)
export OPENAI_API_KEY=sk-...
export AI_ENABLE_LLM_TESTS=true

docker compose exec ai pytest -m llm
```

Without these two variables, any test decorated with `@pytest.mark.llm` is **skipped**,
not failed.

---

## Fail-safe behaviour

| Scenario | Result |
|---|---|
| `AI_USE_LLM_PARSER=false` | Deterministic parser runs. No error. |
| `AI_USE_LLM_PARSER=true`, key set | LLM parser runs (once implemented). |
| `AI_USE_LLM_PARSER=true`, key missing | `RuntimeError` with a clear message. Service fails fast at parse time, not silently. |
| `AI_ENABLE_LLM_TESTS=false`, `@pytest.mark.llm` test collected | Test is skipped with a clear reason message. |
| `AI_ENABLE_LLM_TESTS=true`, key missing | Test runs and will fail at the OpenAI call. Set your key. |

---

## CI safety checklist

- [ ] `OPENAI_API_KEY` is **not** in CI environment variables (verify in your CI secrets).
- [ ] `AI_ENABLE_LLM_TESTS` is **not** set to `true` in CI config.
- [ ] `AI_USE_LLM_PARSER` is **not** set to `true` in CI config.
- [ ] Default `pytest` run passes with zero skipped-due-to-error tests.

---

## Cost implications

OpenAI charges per token. A single runbook parse with `gpt-4o` costs roughly:

| Runbook size | Approximate cost |
|---|---|
| Short (~500 words) | ~$0.005 |
| Medium (~2,000 words) | ~$0.02 |
| Long (~10,000 words) | ~$0.10 |

Enable spending limits on your OpenAI account before running LLM tests in any shared
environment.
