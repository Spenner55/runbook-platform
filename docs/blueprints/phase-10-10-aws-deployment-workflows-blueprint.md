# Phase 10.10: AWS Deployment Workflows Blueprint

| Field | Value |
|---|---|
| Phase number | 10.10 |
| Phase name | AWS Deployment Workflows |
| Objective | Define production AWS infrastructure and deployment workflows for the existing runbook platform architecture. |
| Status | Blueprint only |
| Depends on | Phases 01-09 complete and verified; Phase 10.1-10.9 complete and verified |
| Authored | 2026-04-25 |

---

## 1. Purpose and sequencing rationale

Phase 10.10 moves the hardened platform onto AWS. It must not introduce new product capabilities, new service boundaries, or new orchestration paths. Its job is to make the already-complete platform deployable, observable, repeatable, and recoverable in production.

This phase starts only after Phase 10.9 is verified. Production hardening is a hard dependency because AWS deployment relies on:

- Production Django settings that read secrets from environment variables.
- Production-ready containers for API, AI, runner, and web.
- Health endpoints that check real dependencies.
- Structured logs and request IDs.
- Runner SIGTERM handling for ECS rolling deployments.
- Artifact storage support already wired through Django.
- Security, authentication, authorization, and audit behavior already complete.

AWS deployment comes after hardening because infrastructure should deploy the platform's intended production behavior. It should not compensate for missing app hardening with console tweaks, sidecars, queues, or new routing paths.

The deployment goal is a conservative single-region AWS production architecture:

- ECS Fargate for web, Django API, AI service, and runner tasks.
- RDS for PostgreSQL as the managed database.
- S3 for artifacts and deployment logs where useful.
- ECR for container images.
- ALB, ACM, and Route 53 for HTTPS traffic.
- Secrets Manager and SSM Parameter Store for configuration.
- CloudWatch for logs, metrics, alarms, and deployment events.
- GitHub Actions with OIDC for CI/CD.

This phase intentionally does not add multi-region, queues, Kubernetes, direct frontend-to-AI calls, direct runner database access, or manual console-only infrastructure.

---

## 2. Current-state inspection checklist

Before implementing Phase 10.10, inspect the repo in this order. Do not implement from memory, and do not assume this blueprint reflects future file contents after intervening phases.

### Roadmap and predecessor documents

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`.
- [ ] Read `docs/blueprints/phase-10-09-production-hardening-blueprint.md`.
- [ ] Confirm Phase 10.9 verification evidence exists and passed.
- [ ] Confirm production hardening changed the current local-dev Dockerfiles and settings before any AWS work begins.

### Infrastructure and deployment scaffolding

- [ ] Read `infra/aws/README.md`.
- [ ] Confirm whether `infra/aws/` contains only placeholder documentation or existing IaC.
- [ ] Read `.github/workflows/ci.yml`.
- [ ] List all workflow files under `.github/workflows/`.
- [ ] Confirm whether CI includes security scans, migration checks, container builds, and artifact publishing after Phase 10.9.

### Containers and runtime entrypoints

- [ ] Read `docker-compose.yml`.
- [ ] Read `apps/api/Dockerfile`.
- [ ] Read `apps/ai/Dockerfile`.
- [ ] Read `apps/runner/Dockerfile`.
- [ ] Read `apps/web/Dockerfile`.
- [ ] Confirm each Dockerfile has a production target, no reload/dev server command in production, and no dev dependency install in production.
- [ ] Confirm all images can be built from the repository root with explicit Dockerfile paths.

### Django API

- [ ] Read `apps/api/config/settings/base.py`.
- [ ] Read `apps/api/config/settings/prod.py`.
- [ ] Read `apps/api/config/urls.py`.
- [ ] Read `apps/api/config/api_v1_urls.py`.
- [ ] Confirm every public API remains under `/api/v1/`.
- [ ] Confirm every internal runner API remains under `/api/v1/internal/`.
- [ ] Confirm business logic remains in app `services.py` files.
- [ ] Confirm health and metrics endpoints exist outside `/api/v1/` only where operationally conventional, such as `/health/` and `/metrics/`.

### Runner and AI service

- [ ] Read `apps/runner/runner/main.py`.
- [ ] Read `apps/runner/runner/poller.py`.
- [ ] Read `apps/runner/runner/client.py`.
- [ ] Read `apps/runner/runner/schemas.py`.
- [ ] Confirm runner talks only to Django internal APIs.
- [ ] Confirm runner has no database, AI, S3 orchestration, or integration credentials except what is needed for its local step execution model.
- [ ] Read `apps/ai/app/main.py`.
- [ ] Read `apps/ai/app/api/routes/health.py`.
- [ ] Confirm AI service is stateless and advisory.

### Environment and operator documentation

- [ ] Read `.env.example`.
- [ ] Read `docs/runbooks/README.md`.
- [ ] List existing runbooks under `docs/runbooks/`.
- [ ] Confirm all required production environment variables are documented before deployment workflows reference them.

### Official documentation to check when implementing

Review current official docs only where they directly affect implementation details:

- GitHub Actions OIDC for AWS role assumption: <https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws>
- GitHub OIDC concepts: <https://docs.github.com/en/actions/concepts/security/openid-connect>
- Amazon ECS rolling deployments: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html>
- Amazon ECS deployment circuit breaker: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html>
- Amazon ECS Fargate networking: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html>
- ECS Secrets Manager injection: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html>
- ECR Docker image push workflow: <https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html>
- RDS automated backups: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.html>
- RDS Proxy: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html>
- S3 Block Public Access: <https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html>

### Current source observations from blueprint authoring

At the time this blueprint was written, the checked-out repository still contained local-development defaults:

- `infra/aws/README.md` stated that AWS infrastructure was not scaffolded yet.
- `.github/workflows/ci.yml` ran web, Python lint, API tests, runner tests, and AI tests, but did not yet define AWS deployments.
- The Dockerfiles used dev dependencies or dev commands, such as Django `runserver`, FastAPI `--reload`, and Vite dev server.
- `apps/api/config/settings/prod.py` only imported base settings and set `DEBUG = False`.
- `apps/api/config/urls.py` exposed a simple unconditional `/health/`.
- `docs/runbooks/README.md` was only a placeholder.

Under the baseline for Phase 10.10, these gaps should already be closed by Phase 10.9. If they are not closed, stop and complete Phase 10.9 first.

---

## 3. Architecture invariants and boundaries

All Phase 10 roadmap invariants apply in full:

| Invariant | Phase 10.10 consequence |
|---|---|
| Django is the control plane. | ECS, GitHub Actions, and AWS services deploy and operate Django. They do not make domain decisions or mutate platform state outside Django APIs and management commands. |
| Runner talks only to Django internal APIs. | Runner ECS tasks call only `/api/v1/internal/...` on the Django API service. They do not connect to RDS, AI, Slack, PagerDuty, Jira, or S3 for orchestration/state. |
| Frontend talks only to Django public APIs. | Web runtime config points browser requests at the Django public API under `/api/v1/`. It never routes directly to AI, runner, RDS, or integrations. |
| AI service is stateless and advisory. | AI ECS service has no database, no persistent volume, and no authority over state transitions. Django calls it and decides what to persist. |
| All APIs remain under `/api/v1/`. | No AWS-specific API paths are added. Operational endpoints like `/health/` and `/metrics/` may remain outside the API namespace if Phase 10.9 established that convention. |
| Internal runner APIs remain under `/api/v1/internal/`. | ALB and security groups protect these endpoints from public internet access wherever possible. Auth still lives in Django. |
| UUID primary keys remain standard. | Infrastructure does not introduce sequential public identifiers in URLs, logs, or deployment metadata for domain resources. |
| Business logic belongs in `services.py`. | Management commands for migrations, smoke data setup, or health validation call service functions rather than duplicating domain rules. |
| No service may route around Django. | No Lambda, ECS task, GitHub Action, or AWS console operation may directly mutate platform domain tables except Django migrations and approved Django management commands. |
| AWS deploys the existing architecture. | No queues, no Kubernetes, no service mesh, no direct frontend-to-AI path, and no runner database credentials are introduced for deployment convenience. |

Additional AWS deployment boundaries:

- Use one AWS region for this phase.
- Use separate environments, at minimum `staging` and `production`.
- Prefer separate AWS accounts for staging and production. If that is not available, use separate VPCs, IAM roles, ECS clusters, Secrets Manager paths, S3 buckets, and Terraform workspaces/states.
- All infrastructure changes must be represented in `infra/aws/`; the console may be used for emergency inspection, not as the source of truth.
- GitHub Actions assumes AWS roles through OIDC. Do not store long-lived AWS access keys in GitHub secrets.
- Every deployable image is immutable by digest. Human-readable tags are allowed as pointers, but ECS task definitions should record the image digest or a tag resolved by ECS into a digest.
- Deployments must be reversible at the service-task-definition level. Database rollback requires explicit migration rollback planning and may not be automatic.

---

## 4. Implementation scope by repo area

### `infra/aws/`

Create the complete IaC structure for AWS resources. Terraform is the recommended first implementation because the repository already has an empty AWS infrastructure area and no CloudFormation/CDK precedent. If a different IaC tool is selected, document the reason before implementation.

Expected additions:

- Environment modules and root stacks.
- VPC, subnets, route tables, NAT, security groups.
- ECR repositories.
- ECS cluster, task definitions, services, autoscaling, and scheduled tasks.
- ALB, listeners, target groups, security rules.
- Route 53 records and ACM certificates.
- RDS PostgreSQL, subnet groups, parameter groups, backups, and optional RDS Proxy.
- S3 artifact bucket with KMS encryption and block public access.
- Secrets Manager secrets and SSM parameters.
- CloudWatch log groups, alarms, dashboards, and EventBridge deployment failure rules.
- IAM roles for ECS task execution, task roles, GitHub deploy roles, migration task execution, and read-only operator access.

### `.github/workflows/`

Add workflow contracts for:

- Container build and push.
- IaC validation and plan.
- Staging deployment.
- Production deployment with a manual GitHub Environment approval gate.
- Post-deploy smoke tests.
- Optional rollback workflow that redeploys a previously approved task definition/image digest.

Keep the existing CI workflow as the quality gate. Deployment workflows must depend on successful CI rather than duplicating all test logic.

### Dockerfiles

Update only during implementation, not in this blueprint. Phase 10.10 implementers should confirm Phase 10.9 left production-ready images:

- `apps/api/Dockerfile`: production stage installs prod requirements and runs ASGI via gunicorn/uvicorn worker or another Phase 10.9-approved production command.
- `apps/ai/Dockerfile`: production stage runs uvicorn without reload.
- `apps/runner/Dockerfile`: production stage runs `python -m runner.main` with graceful shutdown support.
- `apps/web/Dockerfile`: production stage builds Vite output and serves static files through a minimal server such as nginx, Caddy, or a Node static server. The runtime must not use `npm run dev`.

### Django API config

Phase 10.10 should not change API contracts. It may add deployment support only where required:

- Environment variable documentation for AWS-specific hostnames, S3 bucket names, region, CloudWatch log level, and public API origin.
- Management commands for deployment validation only if they call existing service logic.
- Static/media storage settings only if Phase 10.4/10.9 did not already cover production S3 configuration.

### Runner

Deployment work configures runner ECS services and scaling. It should not change runner orchestration behavior except to consume production environment variables already defined by hardening:

- `API_BASE_URL` points to the private Django service endpoint or internal ALB hostname.
- `RUNNER_REGISTRATION_TOKEN` is injected from Secrets Manager.
- Runner tasks have no public IP.
- Runner task role is minimal. It should not include RDS permissions. S3 permissions are allowed only if a prior phase explicitly made runner responsible for uploading local execution artifacts through narrowly scoped, Django-authorized upload flows. Otherwise, artifact writes stay behind Django.

### Web

The frontend deployment must preserve the boundary that browser code calls only Django public APIs:

- `VITE_API_BASE_URL` or equivalent runtime config points to the public API origin.
- No AI, runner, integration, or S3 write endpoints are exposed directly.
- If the web is served from a separate hostname, configure CORS and CSRF trusted origins in Django through environment variables.

### Documentation

Add operator-facing runbooks under `docs/runbooks/` during implementation:

- Deploy staging.
- Promote staging to production.
- Roll back service image.
- Handle failed migration.
- Rotate secrets.
- Restore RDS from snapshot/PITR.
- Investigate ALB health failure.
- Investigate runner crash loop.
- Investigate S3 artifact permission failures.

---

## 5. Target AWS architecture and service mapping

### Service map

| Platform component | AWS target | Network exposure | Notes |
|---|---|---|---|
| Web frontend | ECS Fargate service behind public ALB listener, optionally fronted by CloudFront later | Public HTTPS | Serves built static assets. Browser calls Django public API only. |
| Django API | ECS Fargate service behind public ALB listener | Public HTTPS for `/api/v1/...`, `/health/ready/`, `/health/`; `/api/v1/internal/` must not be reachable from internet (see ALB routing, H-01) | Control plane, auth, authorization, persistence, orchestration, audit, and state transitions. |
| AI service | ECS Fargate service behind internal ALB or service discovery | Private only | Stateless advisory service called by Django only. |
| Runner | ECS Fargate service, no load balancer | Private outbound to Django internal API | Polls/claims work from Django, one execution per runner process unless app design later changes. |
| Postgres | Amazon RDS for PostgreSQL, Multi-AZ in production | Private only | Application connects through RDS endpoint or RDS Proxy. No public accessibility. |
| Artifacts | S3 bucket with KMS encryption and block public access | Private AWS APIs; signed access mediated by Django | Django controls artifact persistence and authorization. |
| Images | ECR private repositories | Private AWS APIs | Separate repos for api, ai, runner, web. Immutable tags recommended. |
| Logs | CloudWatch Logs | AWS control plane | One log group per service/environment. |
| Secrets | Secrets Manager plus SSM Parameter Store | AWS control plane | Secrets for sensitive values, SSM for non-sensitive config. |
| TLS and DNS | ACM and Route 53 | Public DNS/HTTPS | Certificates validated through DNS. |

### Networking layout

Use one VPC per environment:

- Two or three Availability Zones.
- Public subnets for ALB and NAT gateways.
- Private application subnets for ECS tasks.
- Private database subnets for RDS.
- Internet gateway attached to public subnets.
- NAT gateway per AZ for production. A single NAT gateway is acceptable for staging if cost is a priority and documented as a lower-availability choice.
- VPC endpoints where cost and reliability justify them:
  - ECR API and Docker registry interface endpoints.
  - CloudWatch Logs interface endpoint.
  - Secrets Manager interface endpoint.
  - SSM interface endpoint.
  - S3 gateway endpoint.

Security groups:

- Public ALB accepts `443` from the internet and optionally `80` only for redirect to HTTPS.
- Web/API ECS tasks accept traffic only from ALB security group.
- AI ECS tasks accept traffic only from API task security group or internal ALB security group.
- Runner ECS tasks accept no inbound traffic.
- RDS accepts `5432` only from API task security group and, if justified, migration task security group or RDS Proxy security group.
- S3 access is IAM-controlled. Bucket policies should deny non-TLS requests and deny unencrypted object writes.

### TLS and DNS

Use ACM certificates in the same region as the ALB:

- `app.example.com` for the web frontend.
- `api.example.com` for Django public API, unless the web and API share the same ALB hostname and path routing.
- Optional `staging-app.example.com` and `staging-api.example.com`.

Route 53 records:

- Alias A/AAAA records to ALB.
- DNS validation records for ACM.
- No public DNS record for AI or runner.
- RDS remains private and is not exposed through public DNS.

### ALB routing

Preferred initial routing:

- Host `app.example.com` routes to web target group.
- Host `api.example.com` routes to API target group.
- HTTP redirects to HTTPS.
- Health checks:
  - Web target group: `/health` or static server health endpoint.
  - API target group: `/health/ready/` (**not** `/health/` — the detailed endpoint checks the AI service and would remove API containers from rotation during AI outages; `ready` checks DB only).
  - AI internal target group, if using internal ALB: `/health`.

> **ARCHITECTURE DECISION (H-01): `/api/v1/internal/` endpoints must not be reachable from the public internet.**
>
> The runner internal API (`/api/v1/internal/claim-next`, `/api/v1/internal/executions/...`) uses runner-token authentication, but defense-in-depth requires that network controls block public reachability entirely — auth-only is insufficient if credentials are compromised.

Because the Django API service is behind the same public ALB that serves browser traffic, use one of the following mandatory controls (not optional):

**Option A (preferred when feasible):** Deploy a second internal ALB or VPC-private service endpoint that serves only `/api/v1/internal/`. Runner ECS tasks call this internal endpoint. The public ALB has no listener rule for `/api/v1/internal/`. This provides true network isolation.

**Option B (acceptable if two ALBs are operationally too complex):** Same Django service on the public ALB, but add an ALB listener rule that blocks requests to path prefix `/api/v1/internal/` from originating outside the private subnet CIDR. Runner tasks originate from private subnet ENIs. This provides network-layer access control without a second load balancer.

In either case, Django-level runner token authentication remains in place as the authentication layer. Network controls are defense-in-depth, not a replacement.

**Gate requirement:** Before Phase 10.10 is complete, confirm via `curl` from outside the VPC that `GET /api/v1/internal/claim-next` returns a network-level rejection (connection refused, 403, or timeout), not an authentication challenge.

### ECS services and tasks

API service:

> **MANDATORY GATE (B-05): Resolve live-streaming architecture before deploying more than one API task.**
>
> Phase 10.8's in-process SSE event bus is process-local. If two API ECS tasks are running, a browser subscribing to an execution event stream may land on a different task than the runner reporting step progress — the browser sees no events. **Sticky sessions on the ALB do NOT fix this** — the runner (a different ECS task) and the browser are different clients and ALB session affinity applies per-client, not per-execution.
>
> Before enabling `desired_count ≥ 2` for the API service, make an explicit architectural decision:
> - **Option A:** Pin API task count at 1 (no horizontal scale for API). Acceptable only for non-critical environments. Document this as a known availability tradeoff.
> - **Option B:** Externalize the event bus to Redis pub/sub, Postgres `LISTEN/NOTIFY` (requires a non-PgBouncer connection for the NOTIFY side), or AWS EventBridge. All API tasks subscribe to the shared bus; any task can serve any stream subscriber.
>
> This gate must be resolved and documented before Phase 10.10 marks the API ECS service as production-ready with `desired_count ≥ 2`.

- Desired count production: minimum 2 across AZs (only after B-05 streaming gate is resolved).
- Deployment type: ECS rolling update with deployment circuit breaker rollback enabled.
- Health check grace period tuned to app startup and migration timing.
- Autoscaling on CPU, memory, and ALB request count per target after production metrics are known.
- Task role grants S3 artifact access, Secrets Manager read for app secrets if needed, CloudWatch logging, and no broad AWS admin permissions.

Web service:

- Desired count production: minimum 2.
- No database or Secrets Manager access except non-sensitive config if absolutely necessary.
- Can be served as a container to preserve the repo's existing web deployable unit and image build contract.

AI service:

- Desired count production: minimum 1 initially, 2 if AI parsing is on critical path.
- Private only.
- Task role only for log delivery and reading its required secret, such as OpenAI API key.
- No RDS or S3 permissions unless a prior phase explicitly requires read-only model assets from S3.

Runner service:

- Desired count production: start with 1 or 2 depending on expected concurrency.
- No ALB.
- Private subnets only.
- Deployment minimum healthy percent should avoid killing all runners at once if long executions are possible.
- SIGTERM grace period must exceed runner graceful drain timeout from Phase 10.9.
- Scaling should be manual at first or based on a Django-exported queue depth metric only after that metric exists. Do not introduce SQS just to scale runners.

Migration task:

- One-off ECS task using the API image.
- Runs `python manage.py migrate --noinput` with production settings.
- Uses the same task role and environment as API, plus narrowly scoped DB access.
- Runs before API service task-definition update in each environment.
- Must be serialized per environment through GitHub Actions concurrency.

### Database

Use RDS for PostgreSQL:

- PostgreSQL major version should match local/dev and CI, or be explicitly tested for compatibility.
- Multi-AZ in production.
- Storage encryption enabled with KMS.
- Deletion protection enabled in production.
- Automated backups enabled with a retention period appropriate to the product's recovery objectives, initially 7-35 days.
- Manual snapshot before risky migrations.
- Performance Insights enabled if available and approved for cost.
- No public accessibility.

RDS Proxy:

- Recommended for production once API concurrency is more than trivial.
- Required if connection count under ECS autoscaling risks exhausting RDS connections.
- Configure credentials through Secrets Manager.
- Validate Django transaction behavior with RDS Proxy before production cutover.
- If RDS Proxy is deferred, document the connection limit calculation and revisit after load testing.

### Artifact storage with S3

Use one S3 bucket per environment, for example:

- `runbook-platform-staging-artifacts-<account-id>-<region>`
- `runbook-platform-production-artifacts-<account-id>-<region>`

Bucket requirements:

- Block Public Access enabled.
- Object Ownership set to bucket-owner-enforced.
- SSE-KMS encryption required.
- Versioning enabled for production.
- Lifecycle policy for old artifacts after product retention is decided.
- Bucket policy denies insecure transport.
- Application IAM policy grants least-privilege access to required prefixes only.
- Django remains the authorization gate for artifact upload/download metadata and signed URL generation.

### Logs, metrics, and alarms

CloudWatch Logs:

- `/runbook-platform/<env>/api`
- `/runbook-platform/<env>/ai`
- `/runbook-platform/<env>/runner`
- `/runbook-platform/<env>/web`
- `/runbook-platform/<env>/migration`

Initial alarms:

- ALB 5xx rate above threshold.
- API target group unhealthy host count > 0.
- API ECS deployment failed event.
- AI target group unhealthy host count > 0 if internal ALB is used.
- Runner service desired count not met.
- Runner task crash loop or repeated exits.
- RDS CPU, free storage, database connections, and replica/standby events where applicable.
- RDS automated backup failure.
- S3 4xx/5xx errors for artifact bucket if metrics are enabled.

CloudWatch dashboards should show ALB request count/errors, ECS service health, RDS health, and runner task count.

---

## 6. Infrastructure-as-code structure under `infra/aws/`

Recommended Terraform structure:

```text
infra/aws/
  README.md
  versions.tf
  providers.tf
  backend.tf.example
  environments/
    staging/
      main.tf
      variables.tf
      terraform.tfvars.example
      outputs.tf
    production/
      main.tf
      variables.tf
      terraform.tfvars.example
      outputs.tf
  modules/
    network/
    ecr/
    alb/
    ecs-service/
    ecs-runner-service/
    rds-postgres/
    s3-artifacts/
    secrets/
    iam-github-oidc/
    observability/
    dns/
```

### State management

- Use remote Terraform state in an S3 bucket with DynamoDB locking, or OpenTofu/Terraform Cloud if already approved.
- State bucket must be created through a documented bootstrap step.
- State files must never be committed.
- Keep staging and production state isolated.
- Use separate AWS IAM roles for plan and apply where practical.

### Module contracts

`network`:

- Inputs: environment, region, VPC CIDR, AZ count, subnet CIDRs, enable NAT per AZ, endpoint toggles.
- Outputs: VPC ID, public subnet IDs, app subnet IDs, database subnet IDs, route table IDs.

`ecr`:

- Creates private repos for `api`, `ai`, `runner`, `web`.
- Enables image scanning on push if available/approved.
- Adds lifecycle policies for unreferenced tags while retaining release tags.
- Outputs repository URLs.

`alb`:

- Creates public ALB, HTTP redirect, HTTPS listeners, target groups, access logs if approved.
- Outputs listener ARNs, target group ARNs, ALB DNS name, security group ID.

`ecs-service`:

- Generic service module for web, API, and AI if AI uses internal ALB.
- Inputs include image URI, CPU, memory, env vars, secrets, target group, health check, desired count, autoscaling config.
- Enables deployment circuit breaker rollback for rolling deployments.

`ecs-runner-service`:

- No load balancer.
- Desired count, CPU, memory, env vars, secrets, log group, security groups.
- Deployment config respects graceful shutdown.

`rds-postgres`:

- Creates subnet group, parameter group, instance or cluster depending on selected RDS shape.
- Enables encryption, backups, deletion protection, maintenance window, backup window.
- Outputs endpoint, port, secret ARN, security group ID.

`s3-artifacts`:

- Creates artifact bucket, KMS key or uses provided KMS key, versioning, lifecycle, bucket policy.
- Outputs bucket name, bucket ARN, KMS key ARN.

`secrets`:

- Defines names and ARNs for Secrets Manager secrets and SSM parameters.
- Does not commit secret values.
- Supports manual initial secret value creation or secure CI-populated values.

`iam-github-oidc`:

- Creates GitHub OIDC provider if not already account-global.
- Creates environment-scoped deploy roles.
- Trust policy constrains repository, branch, and GitHub Environment subject claims.
- Role permissions are least privilege for ECR push, ECS task definition registration, ECS service update, running migration task, reading Terraform state, and applying IaC only where intended.

`observability`:

- Log groups, metric filters, alarms, EventBridge rules for ECS deployment failures, optional SNS topics.

`dns`:

- Route 53 records and ACM DNS validation.
- Supports external DNS delegation if the hosted zone is managed outside this stack.

### IaC commands

From `infra/aws/environments/staging`:

```bash
terraform init
terraform fmt -check -recursive ../..
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

For production, run the same commands in `infra/aws/environments/production` only after staging has passed deployment verification and human approval.

---

## 7. CI/CD workflow contracts under `.github/workflows/`

### Existing CI contract

The current CI workflow should remain the first gate:

- Web install, build, lint, format check, and tests.
- Python compile/lint/format checks.
- API tests with PostgreSQL.
- Runner tests.
- AI tests.
- Security and migration validation added by Phase 10.9.

No AWS deployment workflow may bypass CI.

### New workflow: `aws-iac-plan.yml`

Purpose:

- Validate and plan infrastructure changes for staging and production.

Triggers:

- Pull requests touching `infra/aws/**` or `.github/workflows/aws-*.yml`.
- Manual dispatch.

Required behavior:

- Run `terraform fmt -check -recursive infra/aws`.
- Run `terraform validate` for affected environments.
- Run `terraform plan` for staging on PRs.
- For production, plan only on manual dispatch or protected branch merges.
- Post plan summary to the workflow summary, not as a committed file.
- Use GitHub OIDC to assume read/plan role where remote state access is needed.

No apply occurs in this workflow.

### New workflow: `aws-iac-apply.yml`

Purpose:

- Apply infrastructure changes.

Triggers:

- Manual dispatch only for production.
- Optional automatic staging apply after merge to `main`.

Required behavior:

- Uses GitHub Environment protection rules.
- Uses concurrency group `aws-iac-${environment}`.
- Requires a previously reviewed plan or generates a fresh plan immediately before apply.
- Applies one environment at a time.
- Records Terraform outputs needed by deployment workflows without exposing secrets.

Human approval gates:

- Production apply requires explicit approval from repository environment reviewers.
- Any RDS replacement, VPC replacement, S3 bucket destruction, or IAM privilege expansion requires a separate written approval in the PR.

### New workflow: `aws-build-images.yml`

Purpose:

- Build and push deployable images to ECR.

Triggers:

- Push to `main`.
- Release tag.
- Manual dispatch.

Build matrix:

- `api`: `apps/api/Dockerfile`
- `ai`: `apps/ai/Dockerfile`
- `runner`: `apps/runner/Dockerfile`
- `web`: `apps/web/Dockerfile`

Tagging strategy:

- Immutable commit tag: `<git-sha>`.
- Environment candidate tag: `staging-<git-sha>` or `prod-candidate-<git-sha>`.
- Optional semantic release tag if release process exists.
- Avoid relying on mutable `latest`.

Required behavior:

- Authenticate to AWS using OIDC.
- Authenticate Docker to ECR.
- Build from repository root.
- Run container build smoke checks before push where practical.
- Push images to ECR.
- Capture image digests as workflow outputs/artifacts.
- Generate SBOM and image scan report if Phase 10.9 security tooling selected one.

### New workflow: `aws-deploy-staging.yml`

Purpose:

- Deploy a commit to staging.

Triggers:

- Successful `aws-build-images.yml` on `main`.
- Manual dispatch with image digests.

Required behavior:

1. Resolve image digests for api, ai, runner, web.
2. Register new ECS task definitions for staging.
3. Run migration task using the API image.
4. Update AI service.
5. Update API service.
6. Update web service.
7. Update runner service.
8. Wait for ECS services to stabilize.
9. Run smoke tests.
10. Publish deployment summary with task definition ARNs and image digests.

Concurrency:

- `deploy-staging`.

Rollback:

- If migration fails, stop before updating services.
- If a service fails health checks, rely on ECS circuit breaker where configured and run explicit rollback workflow if needed.

### New workflow: `aws-promote-production.yml`

Purpose:

- Promote a staging-verified build to production.

Triggers:

- Manual dispatch only.

Inputs:

- Git SHA or release tag.
- Image digests for api, ai, runner, web, or a staging deployment ID from which digests can be resolved.
- Migration risk classification: `none`, `backward-compatible`, `requires-maintenance-window`.

Required behavior:

- Verify the selected images are the same digests that passed staging smoke tests.
- Require GitHub Environment approval for `production`.
- Confirm RDS backup/snapshot status before migration.
- Run migration precheck.
- Create manual RDS snapshot for risky migrations if required.
- Run migration task.
- Update services in the production order.
- Wait for stability.
- Run production smoke tests.
- Record deployment summary.

Production deploy order:

1. AI service, if backward compatible.
2. API migration task.
3. API service.
4. Web service.
5. Runner service.

If a deploy includes API changes that require new AI behavior, deploy AI first and validate its health before migrations and API rollout. If a deploy includes runner changes that depend on new internal API behavior, deploy API before runner.

### New workflow: `aws-rollback.yml`

Purpose:

- Redeploy previously known-good service task definitions/images.

Triggers:

- Manual dispatch only.

Inputs:

- Environment.
- Service or all services.
- Target task definition ARN or deployment record ID.
- Whether database rollback is required.

Required behavior:

- Does not run automatically after a failed migration.
- Verifies target task definition belongs to the selected environment.
- Updates selected ECS service to the target task definition.
- Waits for stability.
- Runs smoke tests.
- Records rollback summary.

Database rollback:

- Requires a human decision.
- Uses migration reverse only if tested and data-safe.
- Uses RDS restore to a new instance for destructive or uncertain migrations.
- Never blindly restores production over the live database without an incident commander and explicit approval.

---

## 8. Secrets and environment management

### Principles

- No hardcoded secrets in source, Dockerfiles, Terraform variables, workflow YAML, or committed `.tfvars`.
- GitHub Actions uses OIDC for AWS credentials.
- Application secrets live in AWS Secrets Manager.
- Non-sensitive config can live in SSM Parameter Store or Terraform variables.
- ECS task definitions inject secrets through the ECS secrets mechanism.
- Secret rotation requires a forced new ECS deployment because environment-injected secrets are read at task startup.

### Secret naming

Use consistent environment prefixes:

```text
/runbook-platform/staging/django/secret-key
/runbook-platform/staging/database/url
/runbook-platform/staging/openai/api-key
/runbook-platform/staging/runner/registration-token
/runbook-platform/staging/integrations/slack/webhook-url
/runbook-platform/production/django/secret-key
/runbook-platform/production/database/url
/runbook-platform/production/openai/api-key
/runbook-platform/production/runner/registration-token
/runbook-platform/production/integrations/slack/webhook-url
```

Prefer Secrets Manager JSON secrets only when grouping values has a real operational benefit. Otherwise use one secret per sensitive value for narrow IAM grants and simpler rotation.

### Environment variables

Production API task requires at least:

- `DJANGO_SETTINGS_MODULE=config.settings.prod`
- `DJANGO_SECRET_KEY` from Secrets Manager.
- `DATABASE_URL` from Secrets Manager or assembled from RDS secret.
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `CORS_ALLOWED_ORIGINS`
- `AI_BASE_URL` private AI endpoint.
- `AWS_REGION`
- `AWS_STORAGE_BUCKET_NAME`
- `AWS_S3_ARTIFACT_PREFIX`
- `RUNNER_REGISTRATION_TOKEN` only if Django validates runner tokens from env.
- Integration secrets from Secrets Manager as established by Phase 10.5.

Production AI task requires:

- `OPENAI_API_KEY` from Secrets Manager.
- AI model/config variables from SSM if non-sensitive.
- Log level and environment name.

Production runner task requires:

- `API_BASE_URL` private Django internal endpoint.
- `RUNNER_REGISTRATION_TOKEN` from Secrets Manager.
- `RUNNER_ID` generated per ECS service/task convention or injected per task.
- `RUNNER_POLL_INTERVAL_SECONDS`.
- Log level and environment name.

Production web task requires:

- Public API base URL only.
- No AWS credentials unless the selected static server requires none, which should be the case.

### GitHub secrets and variables

GitHub should store:

- AWS role ARNs as environment variables or GitHub environment variables.
- AWS account IDs and regions as non-secret variables.
- No long-lived AWS access keys.
- No application secrets.

### Secret rotation workflow

1. Write new value to Secrets Manager.
2. Run application-specific validation if possible.
3. Force new ECS deployment for affected services.
4. Confirm new tasks are healthy.
5. Confirm old tasks drained.
6. Record rotation in audit/ops notes.
7. Roll back by restoring previous secret version and forcing another deployment if the new value fails.

---

## 9. Database migration and rollback workflow

### Migration principles

- Migrations run through Django using the API image.
- Migrations are serialized per environment.
- Services are not updated if migration fails.
- Production migrations require a preflight and a rollback note.
- Prefer expand/contract migrations for zero-downtime compatibility:
  - Expand schema with nullable columns/tables/indexes.
  - Deploy code that writes both old and new shape if needed.
  - Backfill through a controlled command.
  - Contract old schema in a later deploy after verification.

### Preflight checks

Before running migrations:

```bash
python manage.py check --deploy
python manage.py showmigrations --plan
python manage.py migrate --check
```

In CI or staging, also run:

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
pytest
```

For production:

- Confirm latest automated RDS backup is available.
- For risky migrations, create a manual snapshot.
- Confirm migration SQL if migration touches large tables, indexes, or destructive operations:

```bash
python manage.py sqlmigrate <app_label> <migration_name>
```

### Runtime workflow

1. Build and push images.
2. Register migration task definition using the API image digest.
3. Stop if selected image digest did not pass CI and staging.
4. Run migration ECS task in private app subnet with DB access.
5. Stream logs to CloudWatch.
6. Wait for task exit code.
7. Stop deployment on non-zero exit.
8. Continue service deployment only after successful migration.

### Rollback notes

Code rollback is usually faster than database rollback. Database rollback depends on the migration type:

- Additive migration: redeploy previous service task definition if app code fails. Usually no DB rollback required.
- Backward-compatible data migration: redeploy previous app only if old code tolerates new data. Otherwise run tested reverse migration or forward fix.
- Destructive migration: requires maintenance window and explicit restore plan before deploy. Prefer not to ship destructive migrations in this phase.
- Failed migration before commit: fix migration and rerun after confirming DB state.
- Failed migration after partial changes: inspect `django_migrations`, schema state, and migration logs. Do not guess. Use a tested fix-forward or restore to a new RDS instance.

RDS restore should normally create a new DB instance from snapshot/PITR, validate it, then repoint application configuration through a controlled maintenance procedure. Do not overwrite the live production database casually.

---

## 10. Deployment verification and smoke tests

### Health checks

ALB and ECS health checks:

- Web: static server health endpoint or root returns 200.
- API (ALB target): `GET /health/ready/` — DB check only; returns 200 if DB is reachable. AI service outage must NOT cause ALB to mark API containers unhealthy.
- API (ops/monitoring): `GET /health/` — full dependency check (DB + AI); used by ops dashboards only, never by ALB.
- AI: `GET /health` returns service status; degraded AI dependency should be visible but should not be confused with container crash.
- Runner: ECS service desired count equals running count; logs show polling; no ALB health check.

### Staging smoke tests

Run after every staging deployment:

```bash
curl -fsS https://staging-api.example.com/health/ready/   # ALB-facing; must return 200
curl -fsS https://staging-api.example.com/health/          # Ops; shows AI status
curl -fsS https://staging-app.example.com/
```

Then run an authenticated API smoke suite:

- Login or obtain JWT using the Phase 10.7 auth flow.
- `GET /api/v1/organizations/`.
- Create or select a test organization.
- Create a runbook.
- Parse/enrich with AI only if the staging key and cost policy allow it.
- Create workflow version.
- Start execution with a harmless command.
- Confirm runner claims execution through Django internal API.
- Confirm step logs stream or are retrievable.
- Confirm execution reaches succeeded.
- Upload and retrieve a small artifact through Django-mediated artifact flow.
- Confirm audit entries exist for key actions.
- Confirm SSE execution status page works if Phase 10.8 is complete.

### Production smoke tests

Use non-destructive checks:

- Public web loads over HTTPS.
- API health is healthy.
- Auth token acquisition works.
- Read-only list endpoint works for a smoke tenant.
- AI health is reachable from Django, not from the public internet.
- Runner service is running and polling, but do not execute production shell commands unless a dedicated smoke runbook exists and is approved.
- S3 artifact bucket can be accessed by Django using a tiny smoke object only if the runbook permits it.

### Deployment summary

Each deployment workflow must record:

- Environment.
- Git SHA.
- Image digests for web, API, AI, runner.
- ECS task definition ARNs.
- Migration task ARN and exit code.
- Smoke test results.
- Rollback target task definitions.
- Human approver for production.

---

## 11. Operational runbooks

Create or update these runbooks during implementation:

| Runbook | Purpose |
|---|---|
| `docs/runbooks/aws-deploy-staging.md` | How to deploy and verify staging. |
| `docs/runbooks/aws-promote-production.md` | How to promote staging images to production. |
| `docs/runbooks/aws-rollback-service.md` | How to roll back ECS services to prior task definitions. |
| `docs/runbooks/aws-failed-migration.md` | How to triage and recover from migration failure. |
| `docs/runbooks/aws-restore-rds.md` | How to restore RDS from snapshot/PITR into a validation instance and cut over if approved. |
| `docs/runbooks/aws-rotate-secrets.md` | How to rotate Secrets Manager values and force ECS redeploys. |
| `docs/runbooks/aws-alb-health-failure.md` | How to debug ALB target health failures. |
| `docs/runbooks/aws-runner-crash-loop.md` | How to debug runner task failures and stuck executions. |
| `docs/runbooks/aws-s3-artifact-access.md` | How to debug artifact upload/download permission failures. |
| `docs/runbooks/aws-dns-tls.md` | How to validate Route 53, ACM, and HTTPS behavior. |

Each runbook must include:

- Symptoms.
- First checks.
- Commands.
- Expected outputs.
- Escalation conditions.
- Rollback or mitigation.
- Links to dashboards/log groups.

---

## 12. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### Milestone 1: Confirm production-hardening readiness

Files touched:

- None expected.
- If gaps are found, stop and return to Phase 10.9 rather than patching them inside 10.10.

Steps:

1. Read Phase 10 roadmap and Phase 10.9 blueprint.
2. Inspect Dockerfiles, settings, health endpoints, runner shutdown behavior, and CI.
3. Run local verification commands from Phase 10.9.
4. Record readiness evidence in the implementation PR.

Commands:

```bash
docker compose exec api python manage.py check --deploy
docker compose exec api pytest
docker compose exec api python manage.py showmigrations
cd apps/web && npm run build
cd apps/web && npm run lint
```

Verification:

- All checks pass.
- Production images exist or are planned before AWS deployment.
- No app boundary violation is present.

Rollback notes:

- No deployment has occurred.

Human approval gate:

- Engineering approval that Phase 10.9 is complete.

### Milestone 2: Scaffold `infra/aws/` IaC structure

Files touched:

- `infra/aws/README.md`
- `infra/aws/versions.tf`
- `infra/aws/providers.tf`
- `infra/aws/backend.tf.example`
- `infra/aws/environments/staging/*`
- `infra/aws/environments/production/*`
- `infra/aws/modules/*`

Steps:

1. Choose Terraform or document an alternative.
2. Add remote state bootstrap instructions.
3. Add empty environment roots wired to modules.
4. Add formatting and validation commands.

Commands:

```bash
cd infra/aws
terraform fmt -recursive
cd environments/staging && terraform init && terraform validate
cd ../production && terraform init && terraform validate
```

Verification:

- `terraform fmt -check -recursive infra/aws` passes.
- `terraform validate` passes for staging and production.

Rollback notes:

- Revert IaC scaffold PR before any apply.

Human approval gate:

- Approval of IaC tool, remote state approach, and account/environment model.

### Milestone 3: Implement network, DNS, and TLS foundations

Files touched:

- `infra/aws/modules/network/*`
- `infra/aws/modules/dns/*`
- `infra/aws/environments/staging/*`
- `infra/aws/environments/production/*`

Steps:

1. Create VPC/subnet model.
2. Create route tables, NAT, and endpoints.
3. Create Route 53 records and ACM cert validation scaffolding.
4. Apply to staging first.

Commands:

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

Verification:

- Subnets span approved AZs.
- No RDS or ECS task is publicly exposed.
- ACM certificates validate.
- DNS aliases resolve to ALB after ALB milestone.

Rollback notes:

- Terraform destroy is acceptable only for staging before dependent resources exist.
- Production network deletion requires explicit approval and impact review.

Human approval gate:

- Approval of CIDR ranges, hosted zone strategy, NAT cost/availability posture.

### Milestone 4: Add ECR repositories and image build workflow

Files touched:

- `infra/aws/modules/ecr/*`
- `.github/workflows/aws-build-images.yml`
- Possibly Dockerfiles if Phase 10.9 did not already make production targets.

Steps:

1. Create ECR repositories for api, ai, runner, web.
2. Add GitHub OIDC deploy role permissions for ECR push.
3. Add build matrix.
4. Push staging candidate images.
5. Record image digests.

Commands:

```bash
docker build -f apps/api/Dockerfile .
docker build -f apps/ai/Dockerfile .
docker build -f apps/runner/Dockerfile .
docker build -f apps/web/Dockerfile .
```

Verification:

- ECR repos exist.
- Images push with commit SHA tags.
- Workflow summary includes digests.
- No `latest` dependency in deploy workflow.

Rollback notes:

- Delete bad image tags if not referenced.
- Do not delete digests referenced by active task definitions.

Human approval gate:

- Approval of image naming, retention policy, and scan policy.

### Milestone 5: Add secrets, IAM, and S3 artifact storage

Files touched:

- `infra/aws/modules/secrets/*`
- `infra/aws/modules/s3-artifacts/*`
- `infra/aws/modules/iam-github-oidc/*`
- Environment roots.
- `.env.example` only if Phase 10.9 did not document required production variables.

Steps:

1. Create artifact buckets with block public access and KMS encryption.
2. Create ECS task roles and execution roles.
3. Create Secrets Manager secret shells and SSM parameters.
4. Add GitHub OIDC roles constrained by repo/environment.
5. Manually populate initial secret values through approved secure process.

Commands:

```bash
terraform plan -out=tfplan
terraform apply tfplan
aws secretsmanager describe-secret --secret-id /runbook-platform/staging/django/secret-key
aws s3api get-public-access-block --bucket <artifact-bucket>
```

Verification:

- Bucket is private, encrypted, and denies public access.
- ECS task roles are least privilege.
- GitHub deploy role can assume via OIDC only from allowed repo/environment.

Rollback notes:

- Disable unused roles rather than deleting active roles.
- Preserve artifact buckets unless empty and explicitly approved.

Human approval gate:

- Security approval of IAM policies and secret naming.

### Milestone 6: Add RDS PostgreSQL and optional RDS Proxy

Files touched:

- `infra/aws/modules/rds-postgres/*`
- Environment roots.
- `docs/runbooks/aws-restore-rds.md`

Steps:

1. Create staging RDS.
2. Validate connectivity from a one-off ECS task or approved network path.
3. Enable backups, encryption, and deletion protection for production.
4. Add RDS Proxy if connection pooling is required or approved.
5. Document restore procedure.

Commands:

```bash
terraform plan -out=tfplan
terraform apply tfplan
aws rds describe-db-instances --db-instance-identifier <db-id>
```

Verification:

- RDS is private.
- Backup retention is enabled.
- Production deletion protection is enabled.
- API/migration task security group can connect; runner cannot.

Rollback notes:

- Staging RDS can be destroyed only after confirming no needed data.
- Production RDS changes require snapshot and approval.

Human approval gate:

- Approval of DB size, Multi-AZ, backup retention, maintenance window, and monthly cost.

### Milestone 7: Add ECS services and ALB routing

Files touched:

- `infra/aws/modules/alb/*`
- `infra/aws/modules/ecs-service/*`
- `infra/aws/modules/ecs-runner-service/*`
- `infra/aws/modules/observability/*`
- Environment roots.

Steps:

1. Create ECS cluster.
2. Create log groups.
3. Register task definitions.
4. Create web/API services behind public ALB.
5. Create AI service private endpoint.
6. Create runner service with no inbound exposure.
7. Enable deployment circuit breaker rollback for rolling services.

Commands:

```bash
terraform plan -out=tfplan
terraform apply tfplan
aws ecs describe-services --cluster <cluster> --services <api-service> <web-service> <runner-service>
```

Verification:

- API and web target groups are healthy.
- AI is not publicly reachable.
- Runner has no public IP and no inbound rules.
- CloudWatch logs receive entries for every service.

Rollback notes:

- Revert to prior task definition if app health fails.
- Use ECS service events and CloudWatch logs before changing infrastructure.

Human approval gate:

- Approval of public exposure, ALB routing, health check paths, and service sizing.

### Milestone 8: Add staging deployment workflow

Files touched:

- `.github/workflows/aws-deploy-staging.yml`
- `docs/runbooks/aws-deploy-staging.md`

Steps:

1. Resolve image digests from build workflow.
2. Register task definitions.
3. Run migration task.
4. Update services in correct order.
5. Wait for stabilization.
6. Run smoke tests.

Commands:

```bash
aws ecs run-task --cluster <cluster> --task-definition <migration-task>
aws ecs wait services-stable --cluster <cluster> --services <api-service>
curl -fsS https://staging-api.example.com/health/
```

Verification:

- Staging deploy completes from GitHub Actions.
- Smoke tests pass.
- Deployment summary includes rollback targets.

Rollback notes:

- Use rollback workflow or manually update service to previous task definition while workflow is being built.
- If migration failed, do not update services.

Human approval gate:

- Approval that staging deployment is repeatable before production workflow work begins.

### Milestone 9: Add production promotion workflow

Files touched:

- `.github/workflows/aws-promote-production.yml`
- `docs/runbooks/aws-promote-production.md`

Steps:

1. Require manual dispatch with staging-verified digests.
2. Require GitHub production environment approval.
3. Confirm RDS backup/snapshot readiness.
4. Run migration task.
5. Deploy services.
6. Run production smoke tests.
7. Record deployment.

Commands:

```bash
aws rds describe-db-instances --db-instance-identifier <prod-db-id>
aws ecs wait services-stable --cluster <prod-cluster> --services <prod-api-service>
curl -fsS https://api.example.com/health/
```

Verification:

- Only approved users can deploy production.
- Production uses same image digests verified in staging.
- Smoke tests pass.

Rollback notes:

- Roll back service task definitions for app regressions.
- Use database restore/fix-forward only under incident procedure for data regressions.

Human approval gate:

- Required GitHub Environment approval plus explicit migration approval for non-additive migrations.

### Milestone 10: Add rollback workflow and operational runbooks

Files touched:

- `.github/workflows/aws-rollback.yml`
- `docs/runbooks/aws-rollback-service.md`
- `docs/runbooks/aws-failed-migration.md`
- `docs/runbooks/aws-alb-health-failure.md`
- `docs/runbooks/aws-runner-crash-loop.md`
- `docs/runbooks/aws-s3-artifact-access.md`
- `docs/runbooks/aws-rotate-secrets.md`
- `docs/runbooks/aws-dns-tls.md`

Steps:

1. Implement rollback workflow with environment and service inputs.
2. Validate rollback in staging.
3. Write and dry-run runbooks.
4. Link dashboards/log groups in runbooks.

Commands:

```bash
aws ecs update-service --cluster <cluster> --service <service> --task-definition <previous-task-definition>
aws ecs wait services-stable --cluster <cluster> --services <service>
```

Verification:

- Staging rollback succeeds.
- Runbooks are executable by an operator who did not write the deployment.
- Production rollback requires approval.

Rollback notes:

- This milestone is the rollback mechanism. Revert workflow if it points to wrong environment/service.

Human approval gate:

- Operations approval that deployment and rollback runbooks are production-ready.

### Milestone 11: Production readiness review and first production deploy

Files touched:

- No code required.
- Deployment record in GitHub Actions and release notes if release process exists.

Steps:

1. Confirm staging has run on production-equivalent configuration.
2. Confirm dashboards and alarms are live.
3. Confirm production secrets are populated.
4. Confirm DNS and TLS.
5. Confirm RDS backups.
6. Run production promotion.
7. Monitor for at least one agreed observation window.

Commands:

```bash
curl -fsS https://api.example.com/health/
aws cloudwatch describe-alarms --state-value ALARM
aws ecs describe-services --cluster <prod-cluster> --services <prod-api-service> <prod-web-service> <prod-runner-service>
```

Verification:

- All services stable.
- Smoke tests pass.
- No critical alarms.
- Operators can locate logs and rollback target.

Rollback notes:

- Use `aws-rollback.yml` for service regression.
- Use failed migration or RDS restore runbook for database regression.

Human approval gate:

- Manual production readiness signoff before first production deploy.

---

## 13. Testing strategy: IaC validation, container build tests, CI dry runs, migration checks, smoke tests, security checks, manual production readiness gate

### IaC validation

- `terraform fmt -check -recursive infra/aws`
- `terraform validate` for each environment.
- `terraform plan` in PRs.
- Static analysis with `tflint`, `checkov`, or equivalent if approved by Phase 10.9 security tooling.
- Review plan output for destructive changes before every apply.

### Container build tests

- Build every image from repository root.
- Run image-level smoke command where possible:
  - API: import Django settings and run `python manage.py check`.
  - AI: import FastAPI app and call test client health in CI.
  - Runner: import runner main modules and validate env parsing with test values.
  - Web: build static assets and start static server in CI if practical.
- Scan images for high/critical vulnerabilities according to Phase 10.9 policy.

### CI dry runs

- Use `workflow_dispatch` against staging with a harmless branch before enabling production.
- Use GitHub Environments for staging and production.
- Validate OIDC trust policy by attempting role assumption from allowed and disallowed refs/environments.
- Confirm concurrency prevents overlapping deploys.

### Migration checks

- `makemigrations --check --dry-run`.
- `migrate --check`.
- Apply migrations to staging from a production-like snapshot if allowed.
- Review SQL for risky migrations.
- Confirm rollback notes exist in PR for every migration.

### Smoke tests

- Health checks.
- Authenticated API calls.
- End-to-end runbook execution in staging.
- Artifact upload/download.
- Audit trail verification.
- Runner polling and execution completion.
- AI parse/enrich path in staging only if key/cost policy allows.

### Security checks

- Confirm no long-lived AWS keys in GitHub secrets.
- Confirm secret scanning passes.
- Confirm S3 block public access.
- Confirm RDS not publicly accessible.
- Confirm AI service not publicly accessible.
- Confirm runner has no inbound security group rules.
- Confirm `/api/v1/internal/` endpoints reject unauthenticated requests.
- Confirm CORS/CSRF origins match deployed hostnames.
- Confirm least-privilege IAM policy review.

### Manual production readiness gate

Production may not be deployed until:

- Staging deploy and rollback both succeeded.
- Production Terraform plan reviewed.
- Production RDS backup/restore runbook reviewed.
- All production secrets populated.
- DNS/ACM validated.
- CloudWatch alarms configured.
- Incident owner and rollback approver are named for first deploy.

---

## 14. Failure modes and risks

### Failed migration

Risk:

- Migration exits non-zero or partially changes schema/data.

Mitigation:

- Run migrations before service update.
- Use staging first.
- Use additive migrations.
- Take manual snapshot for risky production migrations.
- Stop deploy on migration failure.

Recovery:

- Inspect migration logs and `django_migrations`.
- Fix forward if safe.
- Reverse only tested reversible migrations.
- Restore to new RDS instance for destructive/uncertain failures.

### Broken image

Risk:

- Image builds but cannot start in ECS due to missing dependency, wrong command, or config mismatch.

Mitigation:

- Build and smoke-test images in CI.
- Use ECS deployment circuit breaker rollback.
- Use health checks that reflect real readiness.

Recovery:

- Redeploy previous task definition.
- Do not repush a different image to an existing immutable release tag.

### Partial deploy

Risk:

- Some services update while others fail, creating version skew.

Mitigation:

- Define deployment order.
- Keep API changes backward compatible with web, AI, and runner for at least one deploy.
- Record service versions/digests.

Recovery:

- Roll back affected services to compatible task definitions.
- Prefer fix-forward only when rollback would worsen compatibility.

### Secret mismatch

Risk:

- ECS task starts with wrong secret value or missing env var.

Mitigation:

- Validate required env at startup.
- Use environment-scoped secret names.
- Smoke test after every secret rotation.

Recovery:

- Restore previous Secrets Manager version.
- Force new ECS deployment.

### ALB health failure

Risk:

- Tasks run but target health fails due to wrong path, port, security group, startup time, or dependency failure.

Mitigation:

- Use explicit health endpoints.
- Tune grace periods.
- Validate security groups.

Recovery:

- Check target group health reason.
- Check ECS service events and CloudWatch logs.
- Roll back task definition if app health is broken.

### Runner crash

Risk:

- Runner exits repeatedly or is killed mid-execution.

Mitigation:

- SIGTERM handling from Phase 10.9.
- ECS service desired count alarms.
- Django stuck-execution watchdog.

Recovery:

- Inspect runner logs and ECS stopped task reason.
- Scale runner service to zero only if needed to stop damage.
- Let Django watchdog recover stale executions.
- Redeploy previous runner task definition if regression is image-specific.

### S3 permission issue

Risk:

- Artifact upload/download fails due to IAM, bucket policy, KMS key, or prefix mismatch.

Mitigation:

- Least-privilege policy tests in staging.
- Smoke artifact upload/download.
- Bucket policy denies insecure/public access but allows task role.

Recovery:

- Inspect S3 access denied details and CloudTrail.
- Correct IAM/KMS/prefix.
- Do not make bucket public.

### Rollback complexity

Risk:

- App rollback is simple but database state is not backward compatible.

Mitigation:

- Expand/contract migrations.
- Production migration approval gate.
- Rollback notes required in PR.

Recovery:

- Use compatible prior task definitions.
- Fix forward when data has already moved.
- Use RDS restore only under incident procedure.

---

## 15. What NOT to do

- Do not change app boundaries for AWS.
- Do not route frontend directly to AI.
- Do not route frontend directly to runner.
- Do not give runner database access.
- Do not let runner mutate S3 artifacts except through a previously approved, Django-authorized artifact flow.
- Do not add manual console-only infrastructure.
- Do not hardcode secrets in Terraform, GitHub workflows, Dockerfiles, settings, or docs.
- Do not store long-lived AWS access keys in GitHub.
- Do not expose RDS publicly.
- Do not expose AI publicly.
- Do not expose runner publicly.
- Do not create endpoints outside `/api/v1/` for product APIs.
- Do not move business logic into views, serializers, GitHub Actions scripts, Terraform, Lambda, or ECS task wrappers.
- Do not add queues unless explicitly justified by measured production load and approved as a later architecture phase.
- Do not introduce Kubernetes/EKS for this phase.
- Do not add multi-region deployment yet.
- Do not use mutable `latest` tags as deployment inputs.
- Do not run production migrations from a developer laptop.
- Do not make S3 artifact buckets public.
- Do not bypass Django authorization with CloudFront/S3 public object URLs.
- Do not build a separate deployment database, workflow engine, or orchestration service.

---

## 16. Definition of done

Phase 10.10 is done when:

- `infra/aws/` contains reviewed, validated IaC for staging and production.
- Staging and production use isolated AWS resources or clearly isolated accounts/environments.
- ECR repositories exist for web, API, AI, and runner.
- GitHub Actions builds and pushes immutable images.
- GitHub Actions deploys staging automatically or by approved dispatch.
- GitHub Actions promotes staging-verified images to production through a manual approval gate.
- GitHub Actions can roll back ECS services to known-good task definitions.
- Migrations run as one-off ECS tasks before service rollout.
- Migration failure stops deployment before service update.
- RDS PostgreSQL is private, encrypted, backed up, and protected in production.
- S3 artifact storage is private, encrypted, and mediated by Django.
- Web and API are served over HTTPS with ACM certificates and Route 53 DNS.
- AI and runner are private.
- Runner talks only to Django internal APIs.
- Frontend talks only to Django public APIs.
- No service routes around Django for orchestration, persistence, authorization, or state transitions.
- CloudWatch logs, alarms, and deployment failure events are configured.
- Staging smoke tests cover health, auth, API, runner execution, artifacts, audit, and AI where allowed.
- Production smoke tests are non-destructive and documented.
- Required runbooks exist under `docs/runbooks/`.
- A manual production readiness gate has been completed.
- The first production deployment record includes image digests, task definitions, migration result, smoke test result, and rollback targets.
