# Repository-to-Startup Analysis Report

## 1. Executive Summary

This repository is a real early-stage vertical slice of a governed runbook-to-workflow execution platform. It is not just a scaffold: Django persists organizations, runbooks, workflows, executions, execution steps, runner claims, runner ownership, heartbeats, and step results. The React frontend can drive the basic flow. The runner polls Django internal APIs and reports progress without database access. The FastAPI AI service is stateless and advisory.

The product today is **demo-capable but not sellable**. The core architecture is correctly shaped for a future multi-tenant platform, but the monetizable enterprise controls are not implemented yet: authentication, authorization, tenant isolation, approval gates, audit trails, artifacts, real command execution, real AI parsing, production deployment, billing, and supportability.

Best category: **governed runbook execution platform for SRE/platform teams**, with AI-assisted runbook parsing as an accelerator, not the core source of truth.

One-sentence pitch:

> Runbook Platform turns operational procedures into governed, executable workflows with approvals, policy enforcement, audit evidence, and runner-based execution controlled by Django.

The biggest technical leverage is the clean service boundary design already present in `apps/api`, `apps/runner`, `apps/ai`, and `apps/web`. The biggest business blocker is that the current product cannot yet credibly promise security, accountability, or reliability to a paying operations team.

This analysis was originally performed read-only. No source files were modified during the analysis pass. At that time, the working tree already contained uncommitted documentation changes, mostly Phase 10 blueprint files.

## 2. Repository and System Overview

Top-level structure:

| Area | Purpose | Current state |
|---|---|---|
| `apps/api` | Django + DRF control plane | Implemented vertical slice for orgs, runbooks, workflows, executions |
| `apps/web` | React + TypeScript + Vite UI | Basic product flow implemented |
| `apps/runner` | Python worker | Polls Django, claims work, simulates steps, heartbeats |
| `apps/ai` | FastAPI advisory AI service | Deterministic parser; enrich/summarize placeholders |
| `packages/workflow-schema` | Canonical schema scaffold | Minimal JSON schema |
| `packages/contracts` | Shared contract scaffold | Duplicate workflow schema placeholder |
| `packages/sdk` | Future shared SDK | Placeholder only |
| `infra` | Docker/AWS/scripts placeholders | AWS not scaffolded; Docker lives mostly at app/root level |
| `docs/blueprints` | Implementation and Phase 10 roadmaps | Very detailed, including Phase 10 platform expansion plans |
| `docs/audits` | Architecture audits | Useful but partly stale versus current implementation |
| `.github/workflows/ci.yml` | CI | Web build/lint/test, Python lint, API tests, runner tests, AI tests |

Important evidence:

- Monorepo and product statement: `README.md`
- Architecture rules: `CLAUDE.md`, `memory/architecture_conventions.md`
- Phase status: `memory/project_phases.md`
- Runtime topology: `docker-compose.yml`
- Local operations: `Makefile`
- API routing: `apps/api/config/api_v1_urls.py`
- CI: `.github/workflows/ci.yml`

Documentation drift exists:

- `apps/api/README.md`, `apps/web/README.md`, and some older audits describe earlier scaffold states.
- `docs/api/rest-api-v1.md` still describes some older error shapes, while code uses the normalized `{"errors": [...]}` envelope.
- `docs/api/internal-runner-api.md` documents `outcome` for completion, but code and runner use `final_status`.

## 3. Architecture Reconstruction

The implemented design matches the intended control-plane pattern.

### Django API

Django owns durable state, orchestration, public APIs, and runner APIs.

Implemented apps in `INSTALLED_APPS`:

- `apps.common`
- `apps.organizations`
- `apps.runbooks`
- `apps.workflows`
- `apps.executions`

Planned/stub apps exist but are not installed:

- `apps.approvals`
- `apps.policies`
- `apps.audit`
- `apps.artifacts`
- `apps.integrations`
- `apps.users`

Core models:

- `Organization`: global `name`, `slug`; evidence: `apps/api/apps/organizations/models.py`
- `Runbook`: org-scoped source document with `draft`, `ready`, `archived`; evidence: `apps/api/apps/runbooks/models.py`
- `Workflow`: versioned workflow definition with `draft`, `published`, `superseded`, `archived`; evidence: `apps/api/apps/workflows/models.py`
- `Execution`: immutable workflow snapshot, status, runner ownership, claim token, heartbeat timestamps; evidence: `apps/api/apps/executions/models.py`
- `ExecutionStep`: materialized step rows with copied step snapshot and status lifecycle; evidence: `apps/api/apps/executions/models.py`

Service layer is real:

- `create_runbook`, `mark_runbook_ready`, `archive_runbook`: `apps/api/apps/runbooks/services.py`
- `create_workflow`, `publish_workflow`, `archive_workflow`: `apps/api/apps/workflows/services.py`
- `create_execution`, `claim_next_execution`, `heartbeat_execution`, `update_execution_step`, `complete_execution`: `apps/api/apps/executions/services.py`

Public API surface:

- `/api/v1/organizations/`
- `/api/v1/runbooks/`
- `/api/v1/runbooks/{id}/mark-ready/`
- `/api/v1/runbooks/{id}/archive/`
- `/api/v1/workflows/`
- `/api/v1/workflows/{id}/publish/`
- `/api/v1/workflows/{id}/archive/`
- `/api/v1/executions/`
- `/api/v1/executions/{id}/cancel/`

Internal runner API surface:

- `/api/v1/internal/executions/claim-next/`
- `/api/v1/internal/executions/{id}/heartbeat/`
- `/api/v1/internal/executions/{id}/steps/{step_id}/update/`
- `/api/v1/internal/executions/{id}/complete/`

Evidence: `apps/api/config/api_v1_urls.py`, `apps/api/apps/executions/internal_views.py`.

### Intended Flow

The implemented flow is:

1. User creates organization.
2. User creates runbook.
3. User generates workflow from runbook.
4. Django calls FastAPI AI parser through `RunbookAiClient`.
5. Django validates/maps returned candidate into canonical workflow JSON.
6. User publishes workflow.
7. User creates execution from published workflow.
8. Django snapshots workflow and materializes `ExecutionStep` rows.
9. Runner polls `claim-next`.
10. Django locks and claims oldest queued execution with `select_for_update(skip_locked=True)`.
11. Runner heartbeats while active.
12. Runner marks each step running, then succeeded/failed.
13. Django transitions parent execution to `running`, then terminal.
14. Frontend polls execution detail until terminal.

Evidence:

- Flow docs: `docs/architecture/execution-flow.md`
- Runner docs: `docs/runner/execution-loop.md`
- Backend implementation: `apps/api/apps/executions/services.py`
- Runner implementation: `apps/runner/runner/poller.py`, `apps/runner/runner/executor.py`
- Frontend polling: `apps/web/src/features/executions/hooks/useExecutionDetail.ts`

### Runner

The runner owns execution mechanics, but not state authority.

Current maturity:

- Polls Django.
- Claims one execution at a time.
- Processes steps sequentially.
- Starts heartbeat thread.
- Reports step status and final status.
- Simulates work with `time.sleep(0.5)`.
- Treats `FAIL_STEP` in command as deliberate failure.
- Does not execute real subprocesses.
- Does not sandbox.
- Does not upload artifacts.

Evidence:

- `apps/runner/runner/client.py`
- `apps/runner/runner/poller.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/artifact_uploader.py`

### AI Service

The AI service is correctly advisory.

Current maturity:

- FastAPI app exposes `/health`, `/parse/runbook`, `/enrich/workflow`, `/summarize/failure`.
- `/parse/runbook` is typed and deterministic.
- Parser extracts numbered list items and returns fallback steps.
- `/enrich` and `/summarize` are placeholders.
- `OPENAI_API_KEY` exists in `.env.example` but is unused.

Evidence:

- `apps/ai/app/main.py`
- `apps/ai/app/api/routes/parse.py`
- `apps/ai/app/services/workflow_parser.py`
- `apps/ai/app/api/routes/enrich.py`
- `apps/ai/app/api/routes/summarize.py`

### Frontend

The frontend consumes Django only.

Current routes:

- `/organizations`
- `/runbooks?organizationId=...`
- `/workflows/new?runbookId=...`
- `/workflows/:workflowId`
- `/executions/:executionId`

Evidence:

- `apps/web/src/app/router.tsx`
- `apps/web/src/shared/api/client.ts`
- `apps/web/src/features/*/api/*.ts`
- `apps/web/src/routes/**/*.tsx`

Important limitation: runbooks are listed globally from `/api/v1/runbooks/` and filtered client-side by organization in `useRunbooks`. This is acceptable for demo only, not multi-tenant SaaS.

### Data Persistence

PostgreSQL is the system of record. Docker Compose provisions Postgres 17. Django reads `DATABASE_URL`.

Evidence:

- `docker-compose.yml`
- `apps/api/config/settings/base.py`

### Multi-Tenancy Readiness

Partial only.

Implemented:

- `Runbook`, `Workflow`, and `Execution` have `organization` FK.
- Runbook slug is unique per organization.
- Workflow/execution indexes include organization/status fields.

Missing:

- No users.
- No membership model.
- No RBAC.
- No queryset scoping by authenticated organization.
- Public APIs expose all rows.
- Frontend filters tenant data client-side.
- No tenant-aware billing, quotas, audit, artifacts, or integration scoping.

### Security/Auth Readiness

Very low.

Current state:

- DRF default permission is `AllowAny`.
- No JWT/session API.
- No runner token authentication on internal endpoints.
- Runner sends `runner_id` and `claim_token` in body only.
- Internal endpoint protection is logical ownership validation, not authentication.
- `prod.py` only sets `DEBUG = False`.
- CORS is localhost-only, suitable for local dev.
- `.env.example` uses placeholder secrets.

Evidence:

- `apps/api/config/settings/base.py`
- `apps/api/config/settings/prod.py`
- `apps/runner/runner/client.py`
- `.env.example`

## 4. Current Product Capabilities

Implemented today:

- Create/list/retrieve organizations.
- Create/list/retrieve runbooks.
- Mark runbooks ready or archive them.
- Generate draft workflow from runbook via Django-to-AI boundary.
- Publish/archive workflows.
- Supersede previous published workflow on publish.
- Create execution only from published workflow.
- Snapshot workflow definition into execution.
- Materialize workflow steps into execution steps.
- Runner claims queued executions.
- Runner ownership validation through `runner_id` + `claim_token`.
- Heartbeat tracking.
- Step status transitions.
- Execution completion.
- React UI for the full demo path.
- Seed data command.
- Docker Compose local stack.
- CI and targeted tests.

Demo-ready but not sellable:

- Workflow execution is simulated.
- AI parsing is deterministic, not LLM-backed.
- Approvals are displayed as `requiresApproval`, but not enforced.
- No artifact/log evidence is persisted.
- No authentication.
- No tenant isolation.
- No production deployment.
- No customer onboarding or admin experience.
- No audit trail.

## 5. Product Definition

Problem solved:

Engineering teams have runbooks, scripts, operational procedures, and tribal workflows, but execution is often manual, unaudited, inconsistent, and hard to govern. This platform aims to make operational procedures structured, executable, reviewable, and eventually auditable.

Target customer:

Primary early buyer: platform engineering, SRE, DevOps, infrastructure, or internal tools teams at software companies with recurring operational procedures and production-change risk.

Jobs to be done:

- Convert runbooks into repeatable workflows.
- Execute production operations consistently.
- Pause risky steps for approval.
- Preserve evidence of what happened.
- Reduce errors from manual handoffs.
- Standardize incident/deployment/database procedures.
- Give engineering leaders visibility into operational work.

Best product category:

**Governed runbook execution platform.**

Secondary categories:

- AI-assisted runbook-to-workflow system
- Operational workflow governance platform
- SRE/internal operations automation layer

Not primarily:

- General workflow engine
- CI/CD replacement
- Incident management product
- Generic AI automation tool

Differentiation potential:

- Strong control-plane separation.
- Runner executes through Django APIs only.
- AI is advisory, not authoritative.
- Future approvals/policies/audit/artifacts create governance value.
- Workflow execution is tied to operational runbooks, not generic business processes.

Not differentiated yet:

- Real AI quality.
- Execution sandboxing.
- Integrations.
- Enterprise security.
- Compliance-ready audit/evidence.
- UX polish.

## 6. Technical Business Model

### Product Layers

| Layer | Current maturity | Customer value | Dependency | Monetization potential |
|---|---:|---|---|---:|
| Core workflow execution | Medium demo | Repeatable operations | Current Django/runner | High |
| Runbook authoring/parsing | Low-medium | Faster workflow creation | AI parser, schema | Medium-high |
| Runner service | Low-medium | Executes work outside web app | Internal API stability | High |
| Approval gates | Planned | Human control of risky steps | Step-start contract | Very high |
| Policy engine | Planned | Org rules enforced consistently | Approvals | Very high |
| Audit trail | Planned | Accountability/compliance | Stable event taxonomy | Very high |
| Artifacts/evidence | Planned | Debugging and proof | Storage, audit | High |
| Integrations | Planned | Fit into Slack/PagerDuty/Jira | Audit/artifacts | High |
| AI assistance | Stub | Faster setup, summarization | Auth/data controls | Medium |
| Enterprise admin/security | Missing | Sellability | Auth/RBAC/tenancy | Very high |
| Deployment/operations | Local only | Trust/reliability | Hardening/AWS | High |

### Monetization Strategy

Early MVP pricing should be simple:

- **Team SaaS pilot:** flat monthly pilot fee, e.g. $500-$2,000/month.
- Limit by organization, active workflows, and executions/month.
- Include founder support.
- Avoid complex usage billing until value is proven.

Later pricing:

- Base platform fee per organization/team.
- Seat pricing for operators/admins.
- Execution volume tiers.
- Enterprise add-ons for audit retention, SSO, private deployment, custom integrations, compliance exports, support SLA.
- Self-hosted/private cloud annual contracts for security-sensitive teams.

Best early model:

> Flat pilot subscription plus execution limits, with enterprise upgrades later.

Best later model:

> Platform fee + seats + usage + enterprise governance/security add-ons.

### Deployment Model

Recommended sequence:

1. **Local/demo**: current Docker Compose.
2. **Single-tenant hosted SaaS pilots**: fastest path to learning.
3. **Private cloud/self-hosted enterprise**: offered once hardening and IaC exist.
4. **Hybrid/open-core**: defer unless market pull demands it.

Likely buyer concern: this product touches production procedures. Many serious customers will eventually ask for private cloud or self-hosting. The codebase's Docker-first, service-separated design supports that future, but it is not currently deployment-ready.

## 7. True MVP Definition

### Exists Today

- Vertical runbook -> workflow -> execution -> runner -> frontend slice.
- Basic workflow versioning.
- Runner claim/heartbeat/step update protocol.
- Minimal React UI.
- Deterministic AI boundary.
- Docker-first local development.
- Tests across API, runner, AI, frontend.
- Phase 10 planning docs.

### Demo-Ready But Not Sellable

- Browser demo can show the product concept.
- Runner progress appears in UI through polling.
- Workflow generation appears AI-assisted.
- Execution statuses are real in DB.
- The architecture story is credible.

But it cannot yet be sold because any team can access all data, internal endpoints are unauthenticated, execution is fake, and there is no evidence/audit layer.

### Required Before First Customer

Minimum sellable MVP:

- Auth and organization membership.
- Tenant-scoped querysets and object access.
- Runner token authentication.
- Approval gates that actually pause execution.
- Basic audit trail for state changes.
- Basic artifact/log capture.
- Real command execution or clearly scoped safe executor.
- Execution recovery for stale claims/heartbeats.
- Production deployment baseline.
- Admin/onboarding flow.
- Operational docs.
- Security posture statement.
- Support/debug tooling.
- Demo seed data and guided onboarding.

## 8. MVP Gaps and Monetization Blockers

| Blocker | Severity | Why it blocks monetization | Resolution | Effort |
|---|---:|---|---|---:|
| No auth/RBAC | Critical | Cannot protect customer data | Phase 10.7-style JWT, membership, roles | L |
| No tenant isolation | Critical | Cross-customer data leak risk | Queryset scoping, org header, tests | M-L |
| Internal APIs unauthenticated | Critical | Anyone reaching API can claim work | Runner bearer token + network isolation | M |
| No enforced approvals | Critical | Governance promise not real | Step-start contract + approval models/UI | L |
| No audit trail | High | No accountability/compliance value | Append-only audit events | M-L |
| No artifacts/log evidence | High | Cannot prove/debug execution | Artifact model/upload/download | M-L |
| Fake execution | High | Not useful for real ops | Safe subprocess/sandbox model | L |
| AI is regex parser | Medium | Differentiator weak | LLM parsing with review gate | M |
| No production settings | High | Cannot deploy safely | Harden `prod.py`, health, logs, metrics | M |
| No recovery/watchdog | High | Stuck executions require manual DB work | Stale heartbeat recovery | M |
| UX is demo-first | Medium | Hard to onboard customers | Productized flows, empty states, admin | M |
| No integrations | Medium | Product not ambient in ops workflow | Slack/webhook/PagerDuty later | M |
| No billing/usage | Medium | Cannot operate SaaS business | Usage events, plans, limits | M |

## 9. Startup Launch Plan

### Phase 1 — Pre-Launch

Engineering:

- Implement auth, membership, tenant scoping.
- Add runner token auth.
- Implement approval gates.
- Add minimal audit events.
- Add artifact/log capture.
- Add real/safe execution mode.
- Add stale execution recovery.
- Harden production settings.
- Add deployment path for a single hosted environment.

Demo readiness:

- Use seeded examples for deployment, incident response, key rotation.
- Show approval pause/resume.
- Show audit timeline and artifacts.
- Show failure path and recovery.

Security baseline:

- No public internal endpoints.
- No default secrets.
- Tenant isolation tests.
- Basic security docs.
- Admin-only destructive actions.

Customer discovery:

- Interview 20-30 platform/SRE leaders.
- Validate which workflows are painful enough to pay for.
- Avoid selling "AI automation"; sell controlled operational execution.

### Phase 2 — Launch

Ideal first customer:

- 20-300 engineer software company.
- Has platform/SRE team.
- Runs repeated production procedures.
- Feels pain around manual runbooks, approvals, incident consistency, or compliance evidence.
- Not so regulated that SOC2/SSO/self-hosting is mandatory on day one.

Buyer/user:

- Buyer: VP Eng, Head of Platform, Head of Infrastructure, SRE manager.
- User: SRE, platform engineer, on-call engineer, release engineer.

Pilot structure:

- 4-6 week pilot.
- One team, 3-5 real runbooks.
- One runner environment.
- Weekly founder check-in.
- Success metric: at least 10 successful real or shadow executions, 1-2 high-risk approval workflows, evidence captured.

Pricing:

- First pilots: $1k-$3k/month or $5k-$15k fixed pilot.
- Convert to annual once repeat usage exists.

### Phase 3 — Post-Launch

- Prioritize roadmap from actual executed runbooks.
- Instrument usage: workflows created, executions, failures, approvals, artifacts.
- Harden reliability around runner recovery.
- Add integrations requested by customers.
- Add enterprise deployment/security features only when sales requires them.
- Build customer support playbooks.

## 10. Team and Hiring Plan

### Solo Founder Path

One technical founder can realistically:

- Finish backend control plane.
- Build minimum React UI.
- Implement runner MVP.
- Do founder-led sales.
- Deploy first single-tenant pilots.

Defer:

- Complex policy language.
- Marketplace integrations.
- Full enterprise admin.
- Advanced AI agents.
- Multi-region infrastructure.
- Heavy brand/marketing site.

Outsource selectively:

- UX polish.
- Security review.
- Deployment/IaC review.
- Compliance documentation.

Biggest bottleneck: context switching between deep backend correctness, frontend polish, ops, and sales.

### Small Startup Team: 3-5 People

Recommended roles:

| Role | Responsibilities | When | Unblocks |
|---|---|---|---|
| Founding backend/platform engineer | Django services, runner protocol, auth, audit | First hire | Sellable core |
| Frontend/product engineer | Operator UX, admin, execution visibility | Early | Customer usability |
| Infra/platform engineer | Deployment, observability, security hardening | Before paid prod | Reliable pilots |
| Product/design generalist | Workflow UX, onboarding, docs | After first demos | Adoption |
| Founder-led GTM/operator | Discovery, pilots, onboarding | Founder or early hire | Revenue |

### Growth Team: 5-10 People

Structure:

- Backend/platform: workflow, policies, audit, integrations.
- Frontend/product: authoring, execution, admin, review flows.
- DevOps/SRE: deployments, observability, customer environments.
- Security/compliance: auth, audit guarantees, enterprise posture.
- Product/design: workflow ergonomics.
- Sales/customer success: founder-led until repeatability appears.

Do not hire too early:

- Dedicated ML engineer before real AI demand.
- Enterprise sales before product is sellable.
- Full-time compliance lead before customers require it.
- Large marketing team before ICP is validated.

## 11. Engineering Roadmap

Recommended order:

| Order | Item | Business value | Dependency | Risk | Effort |
|---:|---|---|---|---|---:|
| 1 | Auth + tenant isolation | Enables any sale | Current org model | Migration complexity | L |
| 2 | Runner token auth + internal isolation | Protects execution controls | Auth settings | Security gaps | M |
| 3 | Approval gates | Core governance value | Step-start API | Stuck runner waits | L |
| 4 | Audit trail | Accountability | Auth/approvals | Overstated immutability | M |
| 5 | Real execution + sandbox | Makes product useful | Runner protocol | Host safety | L |
| 6 | Artifacts/log evidence | Debug/proof | Execution output | Storage abuse | M |
| 7 | Watchdog/recovery | Reliability | Heartbeats | False failure | M |
| 8 | Production hardening | Deployability | Above core | Config drift | M |
| 9 | Integrations | Workflow adoption | Audit/artifacts | Latency/SSRF | M |
| 10 | Better AI parsing + review gate | Differentiation | Stable schema/auth | Cost/data leakage | M |
| 11 | Live updates/SSE | UX/reduced polling | Auth | Multi-task scaling | M |
| 12 | Billing/usage | SaaS operation | Auth/usage events | Plan complexity | M |
| 13 | Admin controls | Enterprise readiness | Auth/RBAC | UX scope creep | M |

Do not build early:

- General-purpose DSL policy engine.
- Marketplace/plugin system.
- Complex AI agents that execute actions.
- Multi-region deployment.
- Heavy workflow branching/parallelism.
- Native mobile.
- Deep CI/CD replacement features.

## 12. Sales and Market Strategy

Value propositions:

- Reduce operational risk.
- Standardize production procedures.
- Make runbooks executable.
- Preserve evidence for compliance and debugging.
- Reduce manual handoff errors.
- Improve incident response consistency.
- Add governance around automation.

Target segments ranked:

1. Platform engineering teams at software companies.
2. SRE/DevOps teams with repeated production procedures.
3. Infrastructure teams managing risky maintenance.
4. Regulated startups needing lightweight evidence.
5. Internal tools teams building workflow consoles.
6. Enterprise IT ops, later due sales cycle length.

Concrete use cases:

- Production deployment runbooks.
- Incident response workflows.
- Database maintenance.
- Access/key rotation.
- Infrastructure change procedures.
- On-call remediation.
- Compliance-controlled operational changes.
- Failed deployment evidence capture.

Messaging angles:

- "Turn runbooks into controlled execution."
- "Approvals and evidence for production operations."
- "AI helps draft workflows; your control plane approves and records them."
- "Less tribal procedure, more repeatable operations."
- "Govern automation without giving scripts unchecked power."

## 13. Competitive Positioning

Against scripts:

- Scripts execute; this governs, records, and displays execution.

Against cron:

- Cron schedules; this handles human-approved operational workflows.

Against CI/CD:

- CI/CD deploys code; this handles broader operational procedures.

Against internal tools:

- Internal tools are bespoke; this is a reusable operations control plane.

Against workflow engines:

- Generic workflow engines lack SRE/runbook-specific approvals, runner boundaries, and evidence focus.

Against incident tools:

- Incident tools coordinate response; this executes and records procedures.

Against automation platforms:

- Automation platforms often optimize action breadth; this should optimize governance, review, and evidence.

## 14. Deployment and Pricing Strategy

Deployment recommendation:

- Early: hosted single-tenant SaaS pilots.
- Later: multi-tenant SaaS with strict tenant isolation.
- Enterprise: private cloud/self-hosted option once AWS/IaC/hardening exist.

Pricing recommendation:

Early:

- Flat pilot fee.
- Execution/workflow limits.
- Founder support included.

Later:

- Platform fee by organization.
- Seats for operators/admins.
- Execution volume tiers.
- Add-ons for SSO, audit retention, integrations, private deployment, compliance export, support SLA.

Open-core:

- Do not start open-core unless distribution becomes the main growth bottleneck. The product's value depends on trust, hosted reliability, integrations, and governance, which can support commercial SaaS/private deployment without open-core.

## 15. Key Risks

| Risk | Severity | Evidence | Impact | Mitigation |
|---|---:|---|---|---|
| Architecture over-expansion | High | Extensive Phase 10 plans | Slow launch | Build only sellable MVP |
| Auth/tenant gaps | Critical | `AllowAny`, unscoped querysets | Unsellable/security risk | Auth + isolation first |
| Runner safety | High | Simulated execution, empty sandbox | Dangerous real execution | Sandbox/subprocess controls |
| Internal API exposure | Critical | No auth on internal views | Unauthorized execution control | Runner token + private routing |
| Product overbreadth | High | Approvals/policies/audit/artifacts/integrations/AI all planned | Overbuilding | Pick 2-3 killer workflows |
| AI risk | Medium | Regex parser, unused OpenAI key | Weak differentiation or data leakage | Review gate, cost/data controls |
| Reliability risk | High | No watchdog/recovery | Stuck executions | Recovery command/service |
| Market risk | Medium | Category overlaps CI/CD/internal tools | Confusing pitch | Position as governed runbook execution |
| Sales risk | Medium | Enterprise trust requirements | Long cycles | Start with smaller platform teams |
| Compliance risk | High | No audit/artifacts/auth today | Cannot sell compliance story | Build basic evidence layer before claims |

## 16. Recommendations and Next Steps

Priority recommendations:

1. Treat the current repo as a strong technical prototype, not an MVP.
2. Define MVP around **governed execution**, not AI.
3. Implement auth, tenant isolation, and runner token auth before any customer-facing deployment.
4. Implement approval gates before policies.
5. Implement audit and artifacts before integrations.
6. Add real execution only with explicit sandbox and artifact boundaries.
7. Keep AI advisory with a mandatory review gate.
8. Build one strong demo around production deployment or incident response.
9. Sell founder-led pilots to platform/SRE teams before broad marketing.
10. Avoid building a generic workflow engine.

Most important immediate technical work:

- Auth/RBAC and tenant-scoped querysets.
- Runner authentication.
- Approval pause/resume.
- Audit events.
- Artifact/log capture.
- Production hardening and deployment path.

## 17. Appendix: Evidence Map

| File/Directory | Contribution |
|---|---|
| `README.md` | Product statement, monorepo layout, Docker-first intent |
| `CLAUDE.md` | Architecture boundaries and service ownership rules |
| `memory/project_phases.md` | Phase completion state and test-count claims |
| `memory/architecture_conventions.md` | Service-layer, error, URL, execution conventions |
| `docker-compose.yml` | Local service topology: Postgres, API, AI, runner, web |
| `Makefile` | Local operations, test, lint, bootstrap, seed commands |
| `.env.example` | Required settings and current secrets posture |
| `.github/workflows/ci.yml` | CI jobs and current validation coverage |
| `apps/api/config/settings/base.py` | Installed apps, DRF permissions, CORS, DB, AI settings |
| `apps/api/config/settings/prod.py` | Minimal production readiness gap |
| `apps/api/config/api_v1_urls.py` | Public and internal API routing |
| `apps/api/apps/common/*` | UUID base model, domain exceptions, error envelope |
| `apps/api/apps/organizations/*` | Organization model/API baseline |
| `apps/api/apps/runbooks/*` | Runbook persistence and AI client boundary |
| `apps/api/apps/workflows/*` | Workflow versioning, AI mapping, publish/supersede |
| `apps/api/apps/executions/*` | Execution lifecycle, runner ownership, step state machine |
| `apps/api/apps/{approvals,policies,audit,artifacts,integrations,users}` | Phase 10 stubs only |
| `apps/runner/runner/*` | Poller, client, executor, heartbeat, placeholder sandbox/artifacts |
| `apps/ai/app/*` | FastAPI parser, placeholder enrich/summarize, stateless AI boundary |
| `apps/web/src/app/*` | Router, layout, providers |
| `apps/web/src/features/*` | Frontend API clients, hooks, types |
| `apps/web/src/routes/*` | Current product slice UI |
| `packages/workflow-schema/workflow.schema.json` | Canonical minimal workflow schema |
| `packages/contracts/workflow/workflow.schema.json` | Duplicate contract schema |
| `packages/sdk/*` | Placeholder SDK |
| `docs/architecture/execution-flow.md` | Intended execution lifecycle |
| `docs/api/rest-api-v1.md` | Public API documentation, with some drift |
| `docs/api/internal-runner-api.md` | Runner API documentation, with completion-field drift |
| `docs/runner/execution-loop.md` | Runner lifecycle documentation |
| `docs/blueprints/phase-10-*` | Planned platform expansion roadmap |
| `docs/blueprints/phase-10-expansion-architecture-guardrails.md` | Cross-cutting Phase 10 decisions |
| `docs/audits/*` | Prior readiness and blueprint audits, useful but partly stale |
| `infra/aws/README.md` | Confirms AWS is placeholder only |
| `infra/{docker,compose,scripts}/README.md` | Future infra placeholders |
