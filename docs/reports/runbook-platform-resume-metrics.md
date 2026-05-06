# Runbook Platform Resume Metrics Report

## Executive Summary

- 4 implemented application services: Django API, React web, FastAPI AI service, and Python runner (`find apps -maxdepth 1 -mindepth 1 -type d`).
- 6 Docker Compose services, including Postgres, PgBouncer, API, AI, runner, and web (`docker-compose.yml` static parse).
- 63 public Django API operations by static view/viewset inspection, plus 12 internal runner/change/artifact operations (Medium Confidence because Django was not importable locally).
- 4 AI service routes, including 3 domain operations: parse, enrich, summarize (`apps/ai/app/api/routes/*.py`, `apps/ai/app/main.py`).
- 12 Django apps, 24 concrete model classes, 40 migrations, 34 model-declared constraints, 59 model-declared indexes, and 21 JSON fields.
- 23 concrete Django models inherit UUID primary keys from `BaseModel`; 19 concrete models are organization-scoped.
- 8 change-management/governance models: operation profiles, change records, targets, execution bindings, windows, freeze rules, target locks, and dispatch eligibility checks.
- 20 audited object types and 5 audit actor types are implemented in `AuditEvent`; audit metadata scrubber covers 29 forbidden keys and rejects 5 highly sensitive key families.
- 15 custom Prometheus collectors across API and AI service, plus API and AI `/metrics` endpoints.
- 1,170 Python test functions across API, runner, and AI suites, plus 135 frontend Vitest cases.
- 10 CI jobs, including web build/lint/format/test, Python lint, API tests, migration checks, runner tests, AI tests, Python dependency audit, npm audit, secret scan, and container scan.
- 42 Makefile operational targets, including local lifecycle, tests, linting, production checks, migration checks, security scanning, and hardening aggregation.

## Strongest Resume Metrics

| Metric | Value | Confidence | Evidence | Resume-Friendly Wording |
| --- | ---: | --- | --- | --- |
| Application services | 4 | High | `find apps -maxdepth 1 -mindepth 1 -type d` -> `api`, `web`, `ai`, `runner` | Built a 4-service runbook automation platform spanning Django APIs, React UI, FastAPI AI boundary, and a Python execution runner. |
| Docker Compose services | 6 | High | Static parse of `docker-compose.yml` services: `postgres`, `pgbouncer`, `api`, `ai`, `runner`, `web` | Designed local platform topology with 6 Compose services, including database pooling, API, AI, runner, and web tiers. |
| Public Django API operations | 63 | Medium | Static AST count of APIView HTTP methods, DRF viewset mixins, and `@action` routes in `apps/api/apps/**/views.py` | Implemented a broad REST API surface of roughly 63 public operations across organizations, runbooks, workflows, executions, approvals, policies, audit, integrations, changes, and artifacts. |
| Internal runner/change/artifact operations | 12 | High | Static AST count in `apps/api/apps/executions/internal_views.py`, `apps/api/apps/artifacts/internal_views.py`, and internal change views | Built 12 internal orchestration endpoints for runner claiming, heartbeats, step lifecycle updates, approvals, artifact upload, and change execution callbacks. |
| Django apps | 12 | High | `find apps/api/apps -name apps.py` | Structured backend into 12 Django apps with explicit domain boundaries. |
| Concrete domain model classes | 24 | High | AST count from `apps/api/apps/*/models.py`, excluding abstract `BaseModel` | Modeled 24 concrete domain entities covering execution, governance, audit, integrations, artifacts, users, and organizations. |
| Model-declared constraints | 34 | High | AST count of `models.UniqueConstraint` and `models.CheckConstraint` in model files | Added 34 model-level database constraints, including 11 uniqueness constraints and 23 check constraints. |
| Model-declared indexes | 59 | High | AST count of `models.Index` in model files | Tuned relational access patterns with 59 declared database indexes. |
| Organization-scoped models | 19 | High | AST field scan for concrete models with `organization` fields | Implemented multi-tenant data modeling across 19 organization-scoped models. |
| Change-management/governance models | 8 | High | `apps/api/apps/changes/models.py` classes | Built 8 governance models for change records, operation profiles, dispatch eligibility, freeze windows, and target locks. |
| Audit object types | 20 | High | `AuditEvent.ObjectType` in `apps/api/apps/audit/models.py` | Implemented audit coverage across 20 object types with typed actor and object metadata. |
| Sensitive audit metadata controls | 29 forbidden keys, 5 rejected keys | High | AST count of `FORBIDDEN_METADATA_KEYS` and `REJECTED_METADATA_KEYS` in `apps/api/apps/audit/services.py` | Hardened audit logging with metadata scrubbing for 29 sensitive key names and hard rejection for 5 token/snapshot key families. |
| Custom Prometheus collectors | 15 | High | AST count of `Counter`/`Histogram` in `apps/api/apps/common/metrics.py` and `apps/ai/app/main.py` | Added 15 custom Prometheus metrics for execution lifecycle, step transitions, approvals, integrations, artifacts, watchdog recovery, and AI operations. |
| CI jobs | 10 | High | Static parse of `.github/workflows/ci.yml` jobs | Established a 10-job CI pipeline covering build, lint, format, tests, migrations, dependency audits, secret scanning, and container scanning. |
| Python test functions | 1,170 | High | AST count of `test_*` functions under `apps/api`, `apps/runner`, and `apps/ai` | Backed the platform with 1,170 Python test functions across API, runner, and AI services. |
| Frontend test cases | 135 | High | Regex count of `test(`/`it(` in `apps/web/src/**/*.test.*` | Added 135 frontend test cases for protected routes, API-driven screens, and streaming fallback behavior. |

## Full Metric Inventory

### Architecture

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Application services | 4 | High | `find apps -maxdepth 1 -mindepth 1 -type d` | API, web, AI, runner. |
| Docker Compose services | 6 | High | Static parse of `docker-compose.yml` | Includes Postgres and PgBouncer, not only app services. |
| Application Dockerfiles | 4 | High | `find apps -name Dockerfile` | One Dockerfile each for API, AI, runner, web. |
| Shared package areas | 3 | High | `find packages -maxdepth 2 -type d` | `contracts`, `sdk`, `workflow-schema`. |
| Makefile operational targets | 42 | High | `rg -n "^[A-Za-z0-9_.-]+:.*##" Makefile \| wc -l` | Includes one explicitly destructive local reset target; do not frame all as production-safe. |
| Architecture/API/runner/runbook docs | 30 | High | `find docs/architecture docs/api docs/runner docs/runbooks -type f -name '*.md'` | Docs support interview prep but were not used as proof for implemented features unless code matched. |

### API Surface

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Public Django API operations | 63 | Medium | Static AST count of APIView methods, DRF mixins, and `@action` decorators in `apps/api/apps/**/views.py` | Django dependencies were not installed, so this was not resolver-expanded at runtime. |
| Internal runner/change/artifact operations | 12 | High | AST count from `apps/api/apps/executions/internal_views.py`, `apps/api/apps/artifacts/internal_views.py`, internal change views | Includes runner claim/heartbeat/step/approval/complete, artifact upload, and change execution callbacks. |
| Auth operations | 4 | High | `apps/api/apps/users/views.py` | Login, refresh, logout, me. |
| State-transition/action endpoints | 18 | Medium | Static view/action count: runbook mark-ready/archive, workflow publish/archive/review, execution cancel, approvals decide, changes submit/window/preflight, freeze deactivate, internal lifecycle callbacks | Counts operation-style endpoints, not ordinary CRUD list/detail. |
| SSE/live streaming endpoints | 1 | High | `apps/api/config/api_v1_urls.py`, `apps/api/apps/executions/stream_views.py` | `/api/v1/executions/<uuid>/stream/`. |
| API health/readiness endpoints | 3 | High | `apps/api/config/urls.py` | `/health/live`, `/health/ready/`, `/health/`. |
| API metrics endpoints | 1 | High | `apps/api/config/urls.py` | `/metrics/`. |
| AI service routes | 4 | High | `apps/ai/app/api/routes/*.py`, `apps/ai/app/main.py` | `/health`, `/parse/runbook`, `/enrich/workflow`, `/summarize/execution`. |
| AI service domain operations | 3 | High | `apps/ai/app/api/routes/parse.py`, `enrich.py`, `summarize.py` | Parse, enrich, summarize. |

### Backend/Data Model

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Django apps | 12 | High | `find apps/api/apps -name apps.py` | Includes `common` infrastructure app. |
| Concrete model classes | 24 | High | AST count from `apps/api/apps/*/models.py` | Excludes abstract `BaseModel`. |
| Migrations | 40 | High | `find apps/api/apps -path '*/migrations/[0-9]*.py'` | Counted migration files only, excluding `__init__.py`. |
| Model-declared constraints | 34 | High | AST count of `models.UniqueConstraint` and `models.CheckConstraint` | 11 unique + 23 check constraints. |
| Unique constraints | 11 | High | AST count of `models.UniqueConstraint` | Model-declared constraints only. |
| Check constraints | 23 | High | AST count of `models.CheckConstraint` | Model-declared constraints only. |
| Model-declared indexes | 59 | High | AST count of `models.Index` | Does not include implicit FK/unique indexes. |
| JSON fields | 21 | High | AST count of `models.JSONField` | Includes workflow definitions, snapshots, metadata, dispatch checks, and policy contexts. |
| Concrete UUID primary-key models | 24 | High | AST count: 23 `BaseModel` concrete subclasses + `User` explicit UUID PK | All concrete models use UUID primary keys directly or by inheritance. |
| Organization-scoped models | 19 | High | AST field scan for concrete models with `organization` FK/field | Strong multi-tenant modeling signal. |
| API service-layer modules | 11 | High | `find apps/api/apps -name services.py` | One per primary backend domain except `common`. |
| Immutable snapshot/hash/checksum fields | 18 | High | AST field-name scan for `snapshot`, `sha256`, `hash`, `checksum` | Useful wording: immutable snapshot/hash controls, not formal evidence sealing. |

### Execution/Runner

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Runner-owned internal operations | 8 | High | `apps/api/apps/executions/internal_views.py`, `apps/api/apps/artifacts/internal_views.py` | Claim next, heartbeat, step start, approval status, step update, complete, step artifact upload, execution artifact upload. |
| Change execution internal callbacks | 4 | High | `apps/api/apps/changes/urls.py`, `apps/api/apps/changes/views.py` | Bind, accepted, started, finished. |
| Execution lifecycle statuses | 6 | High | `Execution.Status` in `apps/api/apps/executions/models.py` | Queued, claimed, running, succeeded, failed, cancelled. |
| Step lifecycle statuses | 6 | High | `ExecutionStep.Status` in `apps/api/apps/executions/models.py` | Pending, waiting_for_approval, running, succeeded, failed, skipped. |
| Runner test files | 9 | High | `find apps/runner/runner/tests -name 'test*.py'` | Runner-only suite. |
| Runner Python test functions | 121 | High | AST count under `apps/runner` | Includes client, executor, poller, orchestration, schema, artifact, change binding, and shutdown tests. |
| Heartbeat/recovery paths | 5 | Medium | `rg "recover|stuck|heartbeat|watchdog|promote_due_scheduled"` | Runner heartbeat thread, heartbeat API, stuck execution recovery, expired approval recovery, scheduled change promotion during claim-next. |
| Watchdog/recovery management command | 1 | High | `apps/api/apps/executions/management/commands/check_stuck_executions.py` | Recovers stuck executions and expired approvals. |
| Claim-token ownership guards | 3 core guard sites | Medium | `apps/api/apps/executions/services.py`, `apps/api/apps/changes/services.py`, `apps/api/apps/executions/internal_views.py` | `_validate_runner_ownership`, `assert_execution_change_binding_ready`, and internal view guard path. Do not overstate as a formal capability count. |

### Governance/Audit

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Audit actor types | 5 | High | `AuditEvent.ActorType` | User, runner, system, API client, unknown. |
| Audited object types | 20 | High | `AuditEvent.ObjectType` | Covers organizations, runbooks, workflows, executions, approval, policies, artifacts, integrations, and change-management objects. |
| Direct literal audit event types | 26 | Medium | AST scan of direct `AuditService.emit(event_type="...")` calls | Additional dynamic wrapper emitters exist; this is the literal direct-emission floor. |
| Approval subject workflows | 2 | High | `ApprovalRequest.SubjectType` | Execution step and change record approvals. |
| Approval request statuses | 4 | High | `ApprovalRequest.Status` | Pending, approved, rejected, timed out. |
| Approval decision outcomes | 3 | High | `ApprovalDecision.Decision` | Approved, rejected, timed out. |
| Policy outcomes | 3 | High | `PolicyRule.Outcome` | Approval required, auto approve, block. |
| Policy condition types | 3 | High | `PolicyRule.ConditionType` | Risk level, step type, time window. |
| Change-management domain models | 8 | High | `apps/api/apps/changes/models.py` | OperationProfile, ChangeRecord, ChangeTarget, ChangeExecutionBinding, ChangeWindow, FreezeRule, TargetLock, DispatchEligibilityCheck. |
| Change lifecycle statuses | 12 | High | `ChangeRecord.Status` | Draft through closed/rejected/canceled/expired. |
| Freeze/window/target-lock control models | 3 | High | `ChangeWindow`, `FreezeRule`, `TargetLock` | Governance controls exist in code; do not claim enterprise policy adoption. |
| Sensitive audit metadata forbidden keys | 29 | High | `FORBIDDEN_METADATA_KEYS` in `apps/api/apps/audit/services.py` | Keys are scrubbed from nested metadata. |
| Sensitive audit metadata rejected keys | 5 | High | `REJECTED_METADATA_KEYS` in `apps/api/apps/audit/services.py` | Dispatch tokens and request snapshots are hard-rejected. |

### Security

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Auth mechanisms | 2 | High | `apps.users.authentication.CachedJWTAuthentication`; `RunnerBearerTokenAuthentication` | User JWT auth and internal runner bearer token auth. |
| Role types | 4 | High | `MembershipRole` | Owner, admin, operator, viewer. |
| Organization membership/role helper functions | 6 | High | `apps/api/apps/common/permissions.py` | Membership lookup, member/admin/operator role checks, and role assertion helpers. |
| Organization-scoped permission classes | 5 | High | `apps/api/apps/common/permissions.py` | Member, admin/owner, operator, read-only member, runner principal. |
| Static organization-check references | 70+ | Medium | `rg "assert_organization_|require_organization|IsOrganization"` | High coverage signal; not normalized to unique endpoints. |
| Rate-limited public endpoints | 3 | High | `@ratelimit` in `apps/api/apps/users/views.py` and `apps/api/apps/workflows/views.py` | Login, refresh, workflow create. |
| Production required secret/env validations | 6 | High | `apps/api/config/settings/prod.py` | Secret key, DB URL, runner token, change dispatch secret, Fernet key, Prometheus token when metrics enabled. |
| Production security header/cookie controls | 11 | High | `apps/api/config/settings/prod.py` | SSL redirect, HSTS settings, nosniff, secure/HTTP-only cookies, frame denial, referrer policy, CSP directives. |
| SSRF guard categories | 8 | High | `apps/api/apps/integrations/ssrf.py` | HTTPS-only, no userinfo, blocked ports, unsafe hostnames, localhost suffixes, metadata IPs, DNS resolution, public-address validation. |
| Encrypted credential fields | 1 | High | `IntegrationConnection.encrypted_credentials` | Fernet-backed binary credential field. |
| Token/secret validation paths | 6 | Medium | `rg "RUNNER_REGISTRATION_TOKEN|CHANGE_DISPATCH_TOKEN_SECRET|compare_digest|RefreshToken|PROMETHEUS_METRICS_TOKEN"` | Runner token, JWT refresh, metrics bearer token, dispatch token HMAC, claim token mismatch, production env validation. |

### Testing/Quality

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| API test files | 71 | High | `find apps/api -name 'test*.py'` excluding migrations | Includes config tests. |
| Runner test files | 9 | High | `find apps/runner/runner/tests -name 'test*.py'` | Runner-only tests. |
| AI service test files | 8 | High | `find apps/ai/tests -name 'test*.py'` | AI service tests. |
| Frontend test files | 18 | High | `find apps/web/src -name '*.test.*'` | Vitest/RTL tests. |
| Python test functions | 1,170 | High | AST count of `test_*` functions under API, runner, AI | API 987, runner 121, AI 62. |
| Frontend test cases | 135 | High | Regex count of `test(`/`it(` in frontend test files | Includes execution streaming tests. |
| CI jobs | 10 | High | `.github/workflows/ci.yml` | Static workflow parse. |
| Audit/security scan CI jobs | 4 | High | `.github/workflows/ci.yml` | Python dependency audit, npm audit, secret scan, container scan. |
| Dependency/security scanning tools | 4 | High | `.github/workflows/ci.yml`, `Makefile` | pip-audit, npm audit, gitleaks, Trivy. |
| Lint/format/type/build/test gates | 8 | High | `.github/workflows/ci.yml`, `apps/web/package.json` | `tsc -b`, Vite build, ESLint, Prettier check, Vitest, compileall, Ruff check, Ruff format check. |
| Migration/production readiness CI gates | 3 | High | `.github/workflows/ci.yml` | Django deploy check, makemigrations dry-run check, migrate check. |

### Frontend

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| Frontend pages/screens | 18 | High | `find apps/web/src/routes -name '*Page.tsx'` | Includes login plus protected product pages. |
| Protected product routes | 17 | High | Manual/static count from `apps/web/src/app/router.tsx` under `<ProtectedRoute />` | Excludes the protected index redirect and login. |
| Protected route entries including redirect | 18 | High | `apps/web/src/app/router.tsx` | Includes index redirect to `/runbooks`. |
| Feature API modules | 11 | High | `find apps/web/src/features -path '*/api/*.ts'` | One per feature area. |
| Feature hook modules | 38 | High | `find apps/web/src/features -path '*/hooks/*'` | Includes query/mutation hooks and streaming hooks. |
| TypeScript/TSX source files | 113 | High | `find apps/web/src -name '*.ts' -o -name '*.tsx'` | Includes tests and support files. |
| SSE/polling fallback test cases | 6 | Medium | `rg "stream.closed|polling fallback|streaming unavailable|premature stream"` in frontend tests | Counted by scenario references in execution stream/detail tests. |

### AI/LLM

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| AI service routes | 4 | High | `apps/ai/app/api/routes/*.py` | Health plus parse/enrich/summarize. |
| AI domain operations | 3 | High | `parse.py`, `enrich.py`, `summarize.py` | Parse runbook, enrich workflow, summarize execution. |
| Deterministic fallback operations | 3 | High | `workflow_parser.py`, `workflow_enricher.py`, `execution_summarizer.py` | Regex parser/default steps, keyword enrichment, template summarization. |
| OpenAI/LLM-gated paths | 3 | High | `AI_USE_LLM_PARSER` checks in AI services | Parse requires API key when enabled; enrich/summarize call LLM only when gate and key are present. |
| Django-side AI client operations | 3 | High | `RunbookAiClient` methods in `apps/api/apps/runbooks/ai_client.py` | Parse, enrich, summarize over HTTP with timeouts and contract validation. |
| AI response validation/mapping functions | 3 | High | `_validate_and_map_candidate`, `_validate_and_map_enrichment`, `_validate_and_map_summary` | Validates AI boundary shape before workflow service use. |
| AI tests | 62 Python functions | High | AST count under `apps/ai/tests` | Does not include Django AI integration tests. |

### DevOps/Observability

| Metric | Value | Confidence | Evidence | Notes/caveats |
| --- | ---: | --- | --- | --- |
| API health/readiness endpoints | 3 | High | `apps/api/config/urls.py` | Live, ready, detailed health. |
| AI health endpoint | 1 | High | `apps/ai/app/api/routes/health.py` | Includes optional OpenAI health behavior when LLM parser is enabled. |
| API/AI metrics endpoints | 3 | High | API `/metrics/`; AI Instrumentator `/metrics`; AI trailing slash `/metrics/` | Endpoint count includes AI slash compatibility route. |
| Custom Prometheus collectors | 15 | High | AST count of `Counter`/`Histogram` | API 9, AI 6. |
| Structured logging/request ID components | 4 | High | `apps/api/apps/common/middleware.py`, `apps/ai/app/main.py`, `apps/runner/runner/log_streamer.py`, `apps/runner/runner/client.py` | API middleware, AI middleware, runner JSON logger, runner request ID headers. |
| Request ID propagation points | 4 | High | `rg "X-Request-ID|request_id"` in API, AI, runner | API inbound/outbound, AI inbound/outbound, runner client headers, Django AI client headers. |
| Operational runbooks | 14 | High | `find docs/runbooks -type f -name '*.md'` | Documentation only; use as operational maturity signal, not proof of production operation. |
| Hardening Makefile aggregate | 1 | High | `hardening-check: check-prod check-migrations security-scan` | Local aggregate wraps production, migration, and security checks. |
| Security/dependency scan commands | 6 command invocations | High | `Makefile: security-scan` | API pip-audit, AI pip-audit, runner pip-audit, npm audit, gitleaks, Trivy. |

## Resume Bullet Candidate Bank

### Backend Engineer

- Built a Django REST backend with 12 domain apps, 24 concrete models, 40 migrations, 34 model-declared constraints, and 59 indexes.
- Implemented a multi-tenant data model spanning 19 organization-scoped models with UUID primary keys across all concrete entities.
- Developed a 63-operation public API surface across runbooks, workflows, executions, approvals, policies, audit, integrations, artifacts, and change records.
- Added audit infrastructure covering 20 object types and 5 actor types, with metadata scrubbing for 29 sensitive key names.
- Backed backend behavior with 987 API test functions and CI gates for tests, production settings, migration drift, lint, formatting, and dependency audits.

### Full-Stack Engineer

- Built a 4-service runbook platform with Django APIs, React product UI, FastAPI AI service, and Python runner orchestration.
- Delivered 18 React pages, 17 protected product routes, 11 feature API modules, and 38 feature hook modules backed by TanStack Query.
- Implemented execution live updates with SSE plus polling fallback, with frontend tests covering stream closure and fallback behavior.
- Added 135 frontend test cases and CI gates for TypeScript build, linting, formatting, and Vitest.

### Platform Engineer

- Designed a local platform topology with 6 Docker Compose services, including Postgres, PgBouncer, API, AI, runner, and web.
- Built 12 internal orchestration operations for runner claim, heartbeat, step lifecycle, approval polling, artifact upload, and change execution callbacks.
- Implemented runner heartbeat, stuck execution recovery, expired approval recovery, and an operational watchdog command.
- Added 15 custom Prometheus metrics across execution lifecycle, step transitions, approvals, integrations, artifact uploads, watchdog recovery, and AI operations.
- Established a 10-job CI workflow with build, lint, format, tests, migration checks, production deploy checks, dependency audits, secret scan, and container scan.

### Security/Governance Engineer

- Modeled change governance with 8 domain entities covering operation profiles, change records, execution bindings, windows, freeze rules, target locks, and dispatch eligibility checks.
- Implemented 3 policy condition types and 3 policy outcomes to support approval-required, auto-approve, and block decisions.
- Added SSRF protections for outbound integrations, including HTTPS-only enforcement, blocked internal ports, metadata IP blocks, DNS resolution checks, and public-address validation.
- Secured integration credentials with a Fernet-backed encrypted credential field and response serializers that exclude plaintext and encrypted secrets.
- Added production fail-fast validations for required secrets, database URL, runner tokens, dispatch signing secret, Fernet key, and metrics bearer token when metrics are enabled.

### AI Platform Engineer

- Built a FastAPI AI boundary with 3 domain operations: runbook parsing, workflow enrichment, and execution summarization.
- Designed AI calls as opt-in LLM paths gated by `AI_USE_LLM_PARSER` and `OPENAI_API_KEY`, with deterministic fallbacks for all 3 operations.
- Added Django-side AI client contract validation for parse, enrich, and summarize responses before data enters workflow services.
- Propagated request IDs across Django, FastAPI AI, and runner/client boundaries for traceability.
- Covered AI behavior with 62 AI service test functions plus Django AI integration tests for client contract and workflow transformation behavior.

## Claims To Avoid

- Do not claim production users, customer adoption, revenue, uptime, SLOs, or production traffic. No repository evidence proves those.
- Do not claim SOC 2, ISO 27001, HIPAA, PCI, or formal compliance certification. The repo shows compliance-readiness patterns, not certification.
- Do not claim cloud deployment is live. AWS/production docs and blueprints exist, but this audit did not find proof of a deployed environment.
- Do not claim benchmarked performance improvements. The repo includes indexes, PgBouncer, caching, and metrics, but no before/after benchmark evidence.
- Do not claim real sandbox isolation beyond the current runner implementation unless separately proven in code and tests.
- Do not claim the runner is horizontally distributed in production. Code supports runner/API orchestration, claim tokens, and heartbeats, but not proven production scale.
- Do not claim external LLM use is always active. LLM paths are opt-in and gated; deterministic fallbacks are the safe claim.
- Do not claim immutable evidence bundles or sealed compliance artifacts. The code has snapshot/hash fields and audit immutability tests, but not formal evidence sealing.
- Do not count blueprint documents as implemented features unless implementation exists in application code.
- Do not claim security scans are passing now; this audit inspected CI/Makefile definitions and did not execute scans.

## Commands Run

The audit used read-only shell commands plus static inline Python/AST scripts. No network calls, destructive commands, or external services were used.

```bash
pwd && rg --files -g '!node_modules' -g '!**/.venv/**' -g '!**/__pycache__/**' | sed -n '1,200p'
find . -maxdepth 3 -type d | sort | sed -n '1,200p'
git status --short
rg --files apps/api apps/web apps/ai apps/runner packages .github docs/architecture docs/runbooks docs/runner docs/api | sort
sed -n '1,220p' docker-compose.yml
sed -n '1,260p' Makefile
find .github/workflows -maxdepth 1 -type f -name '*.yml' -o -name '*.yaml' | sort
sed -n '1,260p' apps/api/config/api_v1_urls.py
sed -n '1,260p' apps/api/config/urls.py
sed -n '1,260p' apps/ai/app/main.py
sed -n '1,260p' .github/workflows/ci.yml
find apps -name Dockerfile -print | sort | wc -l
rg -n "^[A-Za-z0-9_.-]+:.*##" Makefile
rg -n "^  [A-Za-z0-9_-]+:" .github/workflows/ci.yml
python - <<'PY'  # static parse of docker-compose services
DJANGO_SETTINGS_MODULE=config.settings.test PYTHONPATH=apps/api python - <<'PY'  # attempted Django resolver import; failed because django is not installed
rg -n "router\.register|path\(|@action|class .*ViewSet|class .*APIView|class .*View\(" apps/api apps/ai/app/api/routes apps/ai/app/main.py
rg -n "class .*(models\.Model|TimeStamped|UUID|Base)|models\.(UUIDField|JSONField)|constraints =|models\.(UniqueConstraint|CheckConstraint|Index)\(" apps/api/apps -g 'models.py'
rg -n "class .*\(.*TextChoices|class .*\(.*IntegerChoices|AUDIT|EVENT|OBJECT|STATUS|Role|Outcome|Condition|TextChoices|IntegerChoices" apps/api/apps apps/runner/runner apps/ai/app -g '*.py'
find docs/runbooks -type f -name '*.md' | sort | wc -l
find docs/runbooks -type f -name '*.md' | sort
sed -n '1,260p' apps/api/apps/executions/views.py
sed -n '1,430p' apps/api/apps/executions/internal_views.py
sed -n '1,240p' apps/api/apps/changes/urls.py
sed -n '1,240p' apps/api/apps/artifacts/urls.py
python - <<'PY'  # AST count for models, constraints, indexes, JSON fields, enums, migrations, and tests
sed -n '1,180p' apps/api/apps/organizations/views.py
sed -n '1,190p' apps/api/apps/runbooks/views.py
sed -n '1,210p' apps/api/apps/workflows/views.py
sed -n '1,260p' apps/api/apps/users/views.py
python - <<'PY'  # AST count for public/internal API operations
python - <<'PY'  # AST count for internal APIView methods
for f in apps/ai/app/api/routes/*.py; do printf '%s\n' "$f"; rg -n "@router\.(get|post|put|patch|delete)|def .*\(" "$f"; done
rg -n "Counter\(|Histogram\(|Gauge\(|Summary\(|metrics_view|prometheus|runbook_" apps/api/apps apps/ai/app apps/runner/runner -g '*.py'
rg -n "request_id|X-Request-ID|structlog|logging|Middleware|process_request|process_response" apps/api/apps apps/ai/app apps/runner/runner -g '*.py'
rg -n "ratelimit|RATE_LIMIT|Rate" apps/api/apps apps/api/config -g '*.py'
sed -n '1,220p' apps/api/apps/common/authentication.py
sed -n '1,240p' apps/api/apps/common/permissions.py
sed -n '1,240p' apps/api/apps/integrations/ssrf.py
sed -n '1,220p' apps/api/apps/integrations/crypto.py
sed -n '1,180p' apps/api/config/settings/prod.py
rg -n "MIDDLEWARE|REST_FRAMEWORK|SIMPLE_JWT|AUTHENTICATION|JWT|CSPMiddleware|RequestIDMiddleware|PROMETHEUS|RUNNER_TOKENS" apps/api/config/settings/base.py apps/api/config/settings/prod.py
rg -n "assert_organization_|IsOrganization|is_organization_member|get_user_membership|require_organization|require_matching" apps/api/apps -g '*.py'
rg -n "credentials|encrypted|encrypt_credentials|decrypt_credentials|config_encrypted|BinaryField" apps/api/apps/integrations -g '*.py'
rg -n "RUNNER_REGISTRATION_TOKEN|CHANGE_DISPATCH_TOKEN_SECRET|RUNNER_TOKENS|compare_digest|RefreshToken|JWTAuthentication|InvalidToken|TokenError|PROMETHEUS_METRICS_TOKEN" apps/api apps/runner -g '*.py'
sed -n '1,260p' apps/web/src/app/router.tsx
find apps/web/src/routes -type f -name '*Page.tsx' | sort | wc -l
find apps/web/src/features -type f -path '*/api/*.ts' | sort | wc -l
find apps/web/src/features -type f -path '*/hooks/*.ts' -o -path '*/hooks/*.tsx' | sort | wc -l
rg -n "useQuery|useMutation|QueryClient|EventSource|poll|setTimeout|ReadableStream|stream" apps/web/src -g '*.ts' -g '*.tsx'
find apps/web/src -type f \( -name '*.tsx' -o -name '*.ts' \) | sort | wc -l
find apps/web/src -type f \( -name '*.tsx' -o -name '*.ts' \) | sort
sed -n '1,220p' apps/ai/app/services/workflow_parser.py
sed -n '1,180p' apps/ai/app/services/workflow_enricher.py
sed -n '1,160p' apps/ai/app/services/execution_summarizer.py
sed -n '1,260p' apps/ai/app/services/llm_client.py
rg -n "field_validator|model_validator|ValidationError|max_length|max_items|min_length|AI_MAX_INPUT_CHARS|OPENAI_API_KEY|AI_USE_LLM_PARSER|response_format|model_validate|json.loads" apps/ai/app apps/api/apps/runbooks apps/api/apps/workflows -g '*.py'
sed -n '1,180p' apps/ai/app/core/config.py
sed -n '1,480p' apps/api/apps/runbooks/ai_client.py
sed -n '1,280p' apps/api/apps/workflows/internal_clients.py
python - <<'PY'  # AST scan of assigned event constants and literal event_type kwargs
sed -n '1,240p' apps/api/apps/audit/services.py
rg -n "log_event\(|audit_event|AuditEvent\.objects" apps/api/apps -g '*.py'
rg -n "AuditService|audit_services|audit_emit|from apps.audit|import .*audit|emit\(" apps/api/apps -g '*.py' -g '!**/tests/**' -g '!**/migrations/**'
python - <<'PY'  # AST scan of direct AuditService.emit event types
sed -n '680,750p' apps/api/apps/policies/services.py
sed -n '520,560p' apps/api/apps/integrations/services.py
sed -n '220,260p;1868,1905p;2048,2075p;2290,2310p' apps/api/apps/changes/services.py
sed -n '600,620p' apps/api/apps/approvals/services.py && sed -n '948,980p;1148,1165p' apps/api/apps/executions/services.py && sed -n '240,260p' apps/api/apps/workflows/services.py
python - <<'PY'  # AST field-name scan for snapshot/hash/checksum fields
python - <<'PY'  # AST count of forbidden/rejected audit metadata keys
rg -n "recover|stuck|heartbeat|watchdog|promote_due_scheduled|approval_timeout|expired" apps/api/apps/executions apps/api/apps/approvals apps/api/apps/changes apps/runner/runner -g '*.py'
rg -n "claim_token|_validate_runner_ownership|assert_execution_change_binding_ready|dispatch_token|hmac|compare_digest" apps/api/apps/executions apps/api/apps/changes apps/runner/runner -g '*.py'
sed -n '1,220p' apps/api/apps/executions/management/commands/check_stuck_executions.py
sed -n '1,260p' apps/runner/runner/poller.py
find apps/api/apps -name 'services.py' -print | sort | wc -l
find apps/api/apps -name 'services.py' -print | sort
find apps/ai/app/services -type f -name '*.py' ! -name '__init__.py' -print | sort | wc -l
find apps/runner/runner -maxdepth 1 -type f -name '*.py' ! -name '__init__.py' -print | sort | wc -l
find packages -type f | sort | wc -l
find packages -maxdepth 2 -type d | sort
find packages -type f | sort
find docs/architecture docs/api docs/runner docs/runbooks -type f -name '*.md' | sort | wc -l
rg -n "^[A-Za-z0-9_.-]+:.*##" Makefile | wc -l
rg -n "pip-audit|npm audit|gitleaks|trivy|ruff|format|pytest|vitest|check --deploy|makemigrations --check|migrate --check|compileall|npm run build|npm run lint|format:check" .github/workflows/ci.yml Makefile
find . -path './node_modules' -prune -o -name Dockerfile -print | sort
find apps -maxdepth 1 -mindepth 1 -type d | sort
python - <<'PY'  # AST count of custom Prometheus collectors
cat apps/web/package.json
```

## Methodology

Metrics were counted from implemented files under `apps/api`, `apps/web`, `apps/ai`, `apps/runner`, `packages`, `docker-compose.yml`, `Makefile`, `.github/workflows`, and operational docs. Blueprint documents were read only as context and were not used as proof for implemented features.

Confidence levels:

- High Confidence: exact filesystem count, AST parse, or direct static count from implementation files.
- Medium Confidence: static route/operation count where runtime framework expansion could not be imported locally, or where the count groups related call paths rather than a framework-native registry.
- Estimated: avoided where possible; no production usage, adoption, uptime, revenue, or performance claims were inferred.

The Django URL resolver was not available because `django` is not installed in the current shell environment. API counts therefore use static AST inspection of viewsets, APIViews, decorators, URL modules, and internal view files. Test counts were static counts only; test suites were not executed.
