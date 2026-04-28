# Open Core, Deployment, Pricing, and Business Strategy Report

Prepared: 2026-04-28  
Scope: Business strategy report only. No product functionality or feature implementation is changed by this document.

## 1. Executive Summary

Runbook Platform should be positioned as a **governed runbook execution platform for platform engineering, SRE, DevOps, infrastructure, and production operations teams**. The strongest wedge is not "AI workflow generation" by itself. The strongest wedge is safer production operations: turn human runbooks into versioned, executable workflows with approvals, policy enforcement, audit evidence, artifacts, private runners, and deployment controls.

The recommended business model is:

1. Sell **hosted single-tenant SaaS pilots first** to get real customer usage quickly.
2. Move to **hosted SaaS + private cloud/self-hosted enterprise** as soon as security-sensitive customers ask for control over runner placement, secrets, network access, and data residency.
3. Consider **open core only after the hosted product has real usage signals**, because open core can help distribution but can also distract the company into supporting free users before the value proposition and buyer are proven.

In this context, **open core** means a business model where a useful core product is released as open source, while enterprise-grade capabilities are proprietary or commercially licensed. For this product, the free/open core would be the local runbook-to-workflow execution engine for individual teams. Paid features would be the capabilities managers and executives buy: SSO, RBAC, policy governance, audit retention, compliance exports, private runners, HA, enterprise integrations, support, and managed hosting.

The best initial go-to-market motion is **founder-led sales to platform/SRE leaders at 50-500 engineer software companies**. These teams have enough operational pain to pay, but are usually not so procurement-heavy that the company needs SOC 2, SAML, SCIM, multi-region hosting, and a field sales team on day one.

The pricing strategy should avoid underpricing. Direct market references show that runbook automation and incident operations tools can support meaningful B2B pricing: PagerDuty Runbook Automation lists **$125/user/month plus a platform fee** for hosted runbook automation, PagerDuty Incident Management lists Professional and Business plans around **$21-$41/user/month annually**, FireHydrant lists a Platform Pro package at **$9,600/year**, and Windmill publishes an open-source/self-hosted model with enterprise pricing starting from low monthly entry points but expanding by seats and enterprise capability. This product should not compete as a cheap workflow tool. It should compete as operational governance software that reduces production risk.

Recommended initial commercial pricing:

| Stage | Offer | Price |
| --- | --- | ---: |
| Design partner pilot | 4-6 week supported pilot, 3-5 runbooks, one team, one runner environment | $5,000-$15,000 fixed pilot or $1,500-$3,000/month |
| Team SaaS | Hosted single-tenant or managed tenant for one operations team | $1,500-$3,000/month |
| Business | Multiple teams, policies, approvals, audit, integrations | $3,000-$8,000/month |
| Enterprise | SSO/RBAC, audit retention, private runners, support SLA, custom deployment | $40,000-$150,000/year |
| Private cloud/self-hosted | Customer-controlled deployment, annual license and support | $60,000-$250,000/year |

## 2. Repo-Derived Product Understanding

This strategy is grounded in a read-only review of the repository and existing reports. The product architecture is already shaped around a strong B2B control-plane story:

| Area | Repo evidence | Strategic meaning |
| --- | --- | --- |
| Django API | `apps/api`, `docs/architecture/architecture-overview.md` | Django is the control plane and source of truth. This supports governance, audit, authorization, and enterprise trust. |
| React app | `apps/web`, `apps/web/src/app/router.tsx` | The UI already maps to operator workflows: organizations, runbooks, workflows, executions, approvals, policies. |
| Runner | `apps/runner`, `docs/runner/execution-loop.md` | Private runner architecture is the core enterprise deployment advantage. Customers can execute near their own systems without exposing secrets to a generic SaaS worker. |
| AI service | `apps/ai`, `docs/architecture/ai-service-boundary.md` | AI is advisory, not authoritative. This is the correct posture for production operations. |
| Data model | `docs/architecture/data-model.md` | Organization-scoped runbooks, workflows, executions, and steps support future tenant isolation and billing. |
| Phase 10 docs | `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` | Approvals, policies, audit, artifacts, integrations, auth, hardening, live updates, and AWS deployment are the path from vertical slice to platform. |
| Deployment blueprint | `docs/blueprints/phase-10-10-aws-deployment-workflows-blueprint.md` | ECS Fargate, RDS, S3, ALB, ECR, Secrets Manager, CloudWatch, and GitHub OIDC are the right conservative AWS baseline. |

This report assumes the app is complete for commercial planning purposes, meaning the finished product includes:

- Authentication, authorization, organization membership, and tenant isolation.
- Versioned runbooks and workflows.
- Real runner execution with safe execution boundaries.
- Approval gates that pause execution.
- Policy rules and policy evaluations.
- Append-only audit events.
- Artifact and log evidence capture.
- Integrations for Slack, PagerDuty, Jira, GitHub, webhooks, and cloud/secrets systems.
- Deployment-ready production settings.
- Hosted SaaS and private runner deployment paths.
- Billing, usage metering, admin controls, and support workflows.

## 3. What "Open Core" Means

**Open core** is a hybrid business model for commercial open-source software. A company releases a useful core product as open source, then sells proprietary or commercially licensed premium capabilities around it. Open Core Ventures describes it as an open-source core product plus a commercial source-available premium product. GitLab describes its own business as open core, with most revenue coming from paid subscription tiers. The model is controversial because only the core is open; enterprise capabilities are usually paid.

For this product, open core would mean:

- A free/open-source core that an engineer can run locally or in a small team.
- Paid enterprise capabilities that a manager, director, security team, or executive buyer needs to run it at scale.
- A clean license and packaging boundary so users understand what is free, what is paid, and why.
- A community/distribution strategy, not just a pricing gimmick.

The most useful segmentation is **buyer-based open core**:

| Persona | Should be free/open core | Should be paid |
| --- | --- | --- |
| Individual platform engineer | Local runbook execution, workflow authoring, basic runner, CLI/API, basic logs, basic integrations | Not the primary paid buyer |
| Team lead / SRE manager | Small-team usability may be free to seed adoption | Approvals, policies, audit, RBAC, reports, team governance |
| Director / VP Engineering | Evaluation docs may be free | Compliance exports, SSO, private cloud, support SLA, data retention, procurement controls |
| Security / compliance | Security posture docs may be public | Audit immutability guarantees, advanced access controls, retention, encryption controls |

### Recommended Open-Core Boundary

| Capability | Free/open core | Paid commercial |
| --- | --- | --- |
| Local Docker deployment | Yes | Yes |
| Runbook CRUD | Yes | Yes |
| Workflow generation and editing | Yes | Yes |
| Basic runner execution | Yes | Yes |
| Basic execution history | Yes | Yes |
| One organization / one workspace | Yes | Unlimited |
| Basic logs | Yes | Advanced log retention and artifact controls |
| API and SDK | Yes | Enterprise API quotas and support |
| Authentication | Basic local auth | SSO/SAML/OIDC, SCIM, advanced RBAC |
| Approvals | Simple manual approvals could be free | Role-based approvals, multi-party approvals, timeouts, escalation |
| Policies | Very limited examples | Policy engine, policy evaluations, dry runs, inheritance |
| Audit trail | Short retention or local only | Long retention, export, tamper-evidence, compliance views |
| Private runners | One local runner | Multiple runner groups, runner tokens, HA, environment isolation |
| Integrations | Webhook and basic Slack | PagerDuty, Jira, ServiceNow, GitHub, cloud secrets, SIEM |
| Deployment | Community Docker Compose | Managed SaaS, private cloud, HA self-hosted |
| Support | Community | SLA, private support channel, onboarding |

### Open-Core Risks

Open core should not be adopted casually. The risks are real:

- Free users can consume support before the company has revenue.
- If too much governance is free, the company has no pricing power.
- If the free core is too limited, users see it as open-source marketing rather than a real project.
- Enterprise buyers may still prefer hosted SaaS or private cloud over managing open source.
- Competitors can learn from the open product.
- License choices can create trust issues if changed later.

### Recommendation

Do **not** lead with open core in the first commercial phase. Lead with paid design partners and hosted/private pilots. Revisit open core after:

- At least 5-10 design partners have used the product on real runbooks.
- The team knows which capabilities are the adoption wedge and which capabilities close deals.
- The support burden of self-hosted users is understood.
- The license strategy is decided before public release.

If open core is adopted, use it as a distribution engine for platform engineers, while preserving commercial value in governance, enterprise security, audit, private runners, managed hosting, and support.

## 4. Product Positioning

### Category

Primary category:

> Governed runbook execution platform.

Secondary category language:

- Runbook automation for SRE and platform teams.
- Production operations workflow governance.
- AI-assisted runbook-to-workflow execution.
- Private-runner operational automation.

Avoid positioning as:

- A generic workflow engine.
- A CI/CD replacement.
- A generic AI agent platform.
- A ticketing system.
- A pure incident management product.
- A chatbot.

### One-Sentence Pitch

> Runbook Platform turns production runbooks into governed, executable workflows with approvals, policies, audit evidence, and private runners.

### Longer Pitch

Engineering teams already have runbooks for deploys, database maintenance, incident response, key rotation, failover, service restarts, and emergency fixes. The problem is that those procedures are often copied from docs, run manually, approved in chat, and reconstructed after the fact. Runbook Platform makes those procedures executable, reviewable, repeatable, and auditable without requiring teams to abandon their existing scripts and operational tools.

### Core Differentiator

The product should win by combining:

- Human-readable runbooks.
- AI-assisted workflow creation.
- Explicit human approvals.
- Policy enforcement.
- Audit evidence.
- Private execution close to customer infrastructure.
- A Django control plane that remains the source of truth.

The strongest trust message is: **AI proposes, humans approve, policy governs, runners execute, audit proves.**

## 5. Ideal Customer Profile

### Best Initial ICP

| Attribute | Target |
| --- | --- |
| Company size | 50-500 engineers |
| Team | Platform, SRE, infrastructure, DevOps, production engineering |
| Maturity | Has recurring production procedures but limited governance tooling |
| Pain | Manual runbooks, risky handoffs, weak auditability, production-change anxiety |
| Budget owner | VP Engineering, Head of Platform, Director of Infrastructure, SRE manager |
| Users | On-call engineers, platform engineers, release engineers, infra operators |
| Buying trigger | Incident, audit requirement, platform standardization effort, repeated production mistakes |

### Secondary ICPs

- Fintech or healthcare software teams before heavy compliance lock-in.
- Internal developer platform teams building self-service operations.
- Managed service providers running customer operations.
- AI infrastructure teams with repeated GPU/cluster maintenance procedures.
- Data platform teams with repeatable database and pipeline operations.

### Poor Initial ICPs

- Tiny startups with no operational process.
- Very large enterprises requiring long procurement, SOC 2 Type II, FedRAMP, or deep ServiceNow customization from day one.
- Teams looking only for incident paging.
- Teams looking only for CI/CD.
- Teams that refuse any automation near production systems.

## 6. Pain Points and Jobs To Be Done

### Pain Points

| Pain | Current workaround | Product value |
| --- | --- | --- |
| Runbooks are stale | Wiki pages and tribal knowledge | Versioned workflows derived from runbooks |
| Production procedures are manual | Copy/paste commands | Structured execution with step history |
| Approvals happen in chat | Slack messages and screenshots | First-class approval gates |
| Compliance evidence is painful | Reconstruct after incident | Audit timeline and artifacts |
| Scripts live everywhere | Local machines, CI jobs, shell history | Runner-controlled execution |
| Risk differs by context | Human judgment every time | Policy evaluation |
| Failures are hard to debug | Scattered logs | Per-step output and artifact evidence |
| Operations span private systems | VPN, bastions, manual access | Private runner environments |

### Jobs To Be Done

- When a production task needs to be performed, operators want to run the approved procedure without improvising.
- When a risky step is reached, managers want approval to be required before execution continues.
- When an audit or incident review happens, leaders want proof of who did what, when, and why.
- When a runbook changes, teams want version history and previous execution snapshots to remain explainable.
- When automation touches private infrastructure, security teams want execution to happen inside their network.

## 7. Competitive Landscape

### Direct and Adjacent Competitors

| Competitor/category | Strength | Weakness or opening |
| --- | --- | --- |
| PagerDuty Runbook Automation / Rundeck | Established runbook automation, open-source lineage, enterprise features | Expensive, broad, can feel heavy; room for modern UX and AI-assisted authoring |
| Windmill | Strong open-source developer automation and self-hosting story | Broader developer workflow platform, less specifically positioned around governed production runbooks |
| StackStorm | Open-source event-driven ops automation | Complex, older UX, steeper learning curve |
| FireHydrant / Rootly / incident.io | Strong incident management workflows | Incident lifecycle focus, not primarily private governed runbook execution |
| GitHub Actions / GitLab CI / Jenkins | Ubiquitous automation execution | CI/CD orientation, weak human approval/audit ergonomics for ops runbooks |
| ServiceNow | Enterprise workflow and approval gravity | Heavy implementation, slower for platform engineers |
| Internal scripts and docs | Free and already adopted | No governance, audit, repeatability, or centralized visibility |

### Pricing Reference Points

Live market references at report time:

- PagerDuty Incident Management lists annual Professional and Business pricing around **$21/user/month** and **$41/user/month**, with Enterprise custom pricing and automation as add-ons.
- PagerDuty Runbook Automation lists a hosted plan at **$125/user/month plus platform fee**.
- FireHydrant lists Platform Pro at **$9,600/year** with responder/runbook/integration limits.
- Windmill advertises free open-source/self-hosted usage and enterprise pricing that starts at a low monthly floor but scales by enterprise needs.
- Rundeck documents a free open-source edition and commercial Runbook Automation editions for production-ready enterprise scale.

Implication: the market already accepts a mix of seat pricing, platform fees, annual contracts, self-hosted enterprise licensing, and add-ons. This product should avoid a pure low-cost seat plan because the value is tied to production risk reduction, not generic collaboration.

## 8. Packaging Strategy

### Recommended Packages

| Package | Target | Deployment | Commercial goal |
| --- | --- | --- | --- |
| Community | Individual engineers and small teams | Self-hosted Docker | Distribution, trust, bottom-up adoption |
| Team Cloud | Small platform/SRE team | Hosted SaaS | Fastest paid adoption |
| Business Cloud | Multiple teams | Hosted SaaS or single-tenant SaaS | Core revenue |
| Enterprise Cloud | Security-sensitive orgs | Single-tenant SaaS with private runners | Larger annual contracts |
| Private Cloud / Self-Hosted | Regulated or network-sensitive customers | Customer AWS/VPC/on-prem | Strategic enterprise deals |

### Feature Packaging

| Capability | Community | Team | Business | Enterprise |
| --- | ---: | ---: | ---: | ---: |
| Runbooks and workflows | Yes | Yes | Yes | Yes |
| Basic runner | Yes | Yes | Yes | Yes |
| Workflow versioning | Yes | Yes | Yes | Yes |
| Executions/month | Limited by self-host | 1,000 | 10,000 | Custom |
| Users | 5-10 | 10-25 | 25-100 | Custom |
| Runner environments | 1 | 1-2 | 5 | Custom |
| Manual approvals | Basic | Yes | Yes | Yes |
| Policy rules | No or limited | Limited | Yes | Advanced |
| Audit retention | Local/short | 30 days | 1 year | Custom |
| Artifacts | Local/basic | Limited | Included | Custom retention |
| Integrations | Webhook | Slack/GitHub | PagerDuty/Jira/cloud | ServiceNow/SIEM/custom |
| SSO/RBAC | No | Basic roles | SSO/RBAC | SAML/OIDC/SCIM/custom roles |
| Support | Community | Email | Priority | SLA/private channel |
| Deployment | Self-host | Hosted | Hosted/single-tenant | Hosted/private/self-hosted |

## 9. Pricing Strategy

### Pricing Principles

1. Charge for governance and operational risk reduction, not just workflow execution.
2. Keep pilot pricing simple.
3. Avoid per-execution pricing as the primary metric early; it may discourage usage.
4. Use execution limits as packaging guardrails.
5. Use annual contracts for Enterprise and Private Cloud.
6. Price private deployment high enough to cover support burden.
7. Keep AI pricing behind a usage allowance and overage because LLM costs are variable.

### Recommended Public Pricing

| Tier | Price | Included | Best for |
| --- | ---: | --- | --- |
| Community | Free | Self-hosted, local runner, basic workflow execution, short local history | Individual platform engineers evaluating the concept |
| Team Cloud | $1,500/month | Up to 15 users, 1 org, 1 runner environment, 1,000 executions/month, 30-day audit | One platform/SRE team |
| Business Cloud | $4,000/month | Up to 50 users, 5 runner environments, 10,000 executions/month, policies, approvals, 1-year audit, Slack/GitHub/Jira | Growing engineering orgs |
| Enterprise Cloud | From $60,000/year | SSO/RBAC, custom retention, advanced policies, private runners, priority support, compliance exports | Security-conscious orgs |
| Private Cloud / Self-Hosted | From $100,000/year | Customer-controlled deployment, support SLA, HA guidance, deployment review | Regulated or network-sensitive orgs |

### Alternate Usage-Based Add-Ons

| Add-on | Suggested pricing |
| --- | ---: |
| Additional runner environment | $250-$1,000/month |
| Additional 10,000 executions/month | $500-$1,500/month |
| Additional audit/artifact retention | $250-$2,000/month depending on retention and storage |
| Advanced AI parsing/summarization | Included allowance, then usage-based pass-through plus margin |
| Premium support | 15%-25% of annual contract |
| Professional services onboarding | $5,000-$25,000 one-time |

### Pilot Pricing

Use pilots to learn and qualify, not as unpaid consulting.

Recommended pilot offer:

- 4-6 weeks.
- 3-5 real runbooks.
- One team.
- One runner environment.
- Weekly founder check-in.
- Security review session.
- Success criteria agreed before kickoff.
- Price: **$5,000-$15,000 fixed** or **$1,500-$3,000/month**.

Pilot success criteria:

- At least 10 successful real or shadow executions.
- At least two high-risk workflows with approvals.
- At least one policy rule that prevents or gates risky behavior.
- Audit timeline and artifacts used in a review.
- Champion agrees to convert to annual or introduce the economic buyer.

## 10. Deployment Strategy

### Deployment Philosophy

This product runs operational procedures and may touch production infrastructure. Deployment strategy is therefore part of the product, not an afterthought.

The deployment strategy should support three buyer needs:

1. **Fast evaluation:** hosted demo or single-tenant SaaS.
2. **Safe execution:** private runners inside the customer's network.
3. **Enterprise control:** private cloud/self-hosted deployment for regulated teams.

### Recommended Deployment Sequence

| Phase | Deployment | Why |
| --- | --- | --- |
| 1 | Local Docker demo | Keep demos reproducible and cheap |
| 2 | Founder-managed single-tenant SaaS pilots | Fastest way to learn without solving full multi-tenant scale |
| 3 | Hosted multi-tenant SaaS control plane + private runners | Scalable default commercial model |
| 4 | Single-tenant SaaS for larger customers | Easier security review and data isolation |
| 5 | Private cloud/self-hosted enterprise | Required for sensitive production environments |
| 6 | Open-core community distribution | Optional distribution layer after product-market signal |

### AWS Production Reference Architecture

Use the existing Phase 10.10 direction:

- ECS Fargate for web, Django API, AI service, and runner tasks.
- RDS PostgreSQL for persistence.
- S3 for artifacts, evidence, logs where appropriate, and exported reports.
- ECR for images.
- ALB, ACM, and Route 53 for HTTPS.
- Secrets Manager and SSM Parameter Store for config and credentials.
- CloudWatch logs, metrics, alarms, and dashboards.
- GitHub Actions OIDC to assume AWS roles without long-lived AWS keys.
- ECS deployment circuit breaker with rollback enabled.
- Private subnets for API, runner, AI, and database where possible.
- Public exposure only for web/API ingress through ALB.

AWS references support the core choices: Fargate bills by requested vCPU/memory/storage seconds, RDS bills by selected database capacity, Secrets Manager bills by stored secrets and API calls, GitHub Actions OIDC avoids long-lived AWS credentials, ECS deployment circuit breaker can roll back unhealthy deployments, and S3 Block Public Access should protect artifact buckets by default.

### Single-Tenant Pilot Architecture

Recommended for first paid customers:

- One AWS account or environment per customer, or at least isolated ECS services, RDS database, secrets namespace, S3 bucket, and CloudWatch log groups.
- API and web behind ALB.
- Runner deployed inside the same VPC or connected to customer network through VPN/private connectivity if needed.
- AI service disabled or isolated unless the customer approves data handling.
- Manual provisioning at first, then Terraform after patterns stabilize.

Advantages:

- Easier security explanation.
- Easier incident debugging.
- Lower blast radius.
- Faster sales to teams nervous about multi-tenant SaaS.

Disadvantages:

- Higher operational overhead.
- More expensive per customer.
- Requires strong environment inventory and runbooks.

### Hosted SaaS + Private Runner Architecture

Recommended default after pilots:

- Shared hosted control plane for web/API/AI.
- Customer-scoped organizations, RBAC, audit, policies, and billing.
- Runners installed in the customer's VPC, Kubernetes cluster, ECS service, VM, or on-prem environment.
- Runner authenticates to Django internal APIs using short-lived or rotatable tokens.
- Runner does not talk to the database.
- Runner receives only the work it is authorized to execute.
- Artifacts upload through controlled, signed, tenant-scoped flows.

This is the best long-term commercial architecture because it lets the company operate the control plane while customers keep execution close to private systems.

### Private Cloud / Self-Hosted Architecture

Offer only when the customer value justifies support cost.

Minimum requirements:

- Terraform or customer-deployable IaC.
- Production Docker images.
- Documented secrets model.
- Database backup and restore runbooks.
- Upgrade/migration procedures.
- Health checks and smoke tests.
- Support bundle collection.
- License enforcement that does not break production execution when a license server is unavailable.

Contractually require:

- Named customer owner.
- Supported versions policy.
- Upgrade window requirements.
- Access to logs/support bundles for troubleshooting.
- Annual minimum contract.

### Estimated AWS Cost Model

Actual costs depend heavily on region, traffic, logs, retention, storage, high availability, and support tooling. The following planning ranges are useful for gross margin modeling:

| Environment | Monthly infra estimate | Notes |
| --- | ---: | --- |
| Internal demo/staging | $150-$500 | Small ECS tasks, small RDS, limited logs |
| Single-tenant pilot | $300-$1,500 | RDS, ALB, ECS services, logs, secrets, S3 |
| Production SaaS baseline | $1,500-$5,000 | HA services, RDS backups, observability, multiple envs |
| Larger single-tenant enterprise | $2,000-$10,000+ | Multi-AZ DB, higher retention, more logs/artifacts, support tooling |

Gross margin guidance:

- Team Cloud at $1,500/month should target infra cost below $300/month after early pilot learning.
- Business Cloud at $4,000/month can support more isolation and support.
- Enterprise/Private Cloud must be priced annually because support, security review, and deployment complexity dominate raw AWS cost.

## 11. Sales Strategy

### Sales Motion

Use founder-led sales until at least 10 customers have converted from pilot to paid. The founder should personally hear objections, observe onboarding, and learn which workflows generate urgency.

Recommended sales path:

1. Identify accounts with visible platform/SRE maturity.
2. Reach platform/SRE leaders and senior ICs.
3. Lead with a sharp production-operations pain, not a generic automation pitch.
4. Run a 30-minute discovery call.
5. Demo a realistic runbook: deployment rollback, database maintenance, incident remediation, key rotation, or service restart.
6. Propose a paid pilot with explicit success criteria.
7. Convert to annual after measured operational value.

### Buyer Personas

| Persona | Cares about | Message |
| --- | --- | --- |
| VP Engineering | Risk, consistency, engineering leverage, auditability | "Standardize production procedures without building an internal platform." |
| Head of Platform | Self-service, guardrails, private execution | "Let teams run approved operations safely through private runners." |
| SRE Manager | On-call load, repeatability, incident quality | "Turn fragile runbooks into controlled execution with evidence." |
| Security/Compliance | Access control, audit, retention, proof | "Approval, policy, and audit are first-class, not chat screenshots." |
| Senior SRE/Platform IC | Speed, ergonomics, fewer manual steps | "Keep your scripts, add execution history and guardrails." |

### Discovery Questions

Use these in sales calls:

- What recurring production procedures still live in docs or wiki pages?
- Which runbooks are most dangerous if run incorrectly?
- Where do approvals happen today?
- How do you prove who approved and ran a production operation?
- What happens when a runbook step fails halfway through?
- Which systems would a runner need to reach?
- Would a hosted control plane with private runners pass security review?
- What compliance or audit pressure exists this year?
- What would make a 6-week pilot obviously successful?

### Demo Flow

The demo should be concrete and short:

1. Import or paste a real-looking production runbook.
2. Show AI-assisted workflow extraction.
3. Review and publish the workflow.
4. Start an execution.
5. Show the runner processing safe steps.
6. Pause at a high-risk approval step.
7. Approve/reject from the approval inbox.
8. Show policy evaluation explaining why approval was required.
9. Show logs/artifacts.
10. Show audit timeline and export.

The demo should avoid magic. Production buyers trust clear controls more than autonomous AI.

### Objection Handling

| Objection | Response |
| --- | --- |
| "We already have scripts." | "That is exactly the starting point. The product wraps existing scripts with approval, policy, audit, and repeatable execution." |
| "We use GitHub Actions/Jenkins." | "CI/CD is good for build and deploy pipelines. This is for operator-run production procedures with human approvals, evidence, and private runner context." |
| "We cannot let SaaS execute in our environment." | "Use private runners. The hosted control plane coordinates; execution happens inside your network." |
| "AI cannot be trusted with production." | "AI is advisory. Humans review, policies govern, and Django owns state transitions." |
| "We need SOC 2." | "For early pilots, use single-tenant/private deployment and a security posture packet. SOC 2 should be on the roadmap once pilots validate demand." |
| "Rundeck already exists." | "Rundeck is strong. The opportunity is a modern governed workflow experience with AI-assisted authoring, first-class policy/audit, and a lighter private-runner model." |

## 12. Marketing Strategy

### Messaging Pillars

1. **From docs to execution:** Convert runbooks into workflows operators can actually run.
2. **Governed by default:** Approvals, policies, and audit are built into execution.
3. **Private where it matters:** Runners execute near customer systems.
4. **AI with guardrails:** AI helps create and summarize; it does not silently operate production.
5. **Proof after every run:** Every execution has step history, artifacts, decisions, and audit trail.

### Website Structure

The first marketing site should be practical and buyer-oriented:

- Hero: governed runbook execution for production operations.
- Product section: runbook import, workflow review, approval gates, policies, audit, private runners.
- Use cases: deploy rollback, database migration, incident remediation, access/key rotation, service restart.
- Security section: control plane, private runners, tenant isolation, audit, secrets posture.
- Deployment section: hosted SaaS, single-tenant, private cloud.
- Pricing section: Team, Business, Enterprise, Private Cloud.
- Demo CTA: "Run a pilot on three production runbooks."

Avoid vague AI language and avoid a generic "workflow automation" site.

### Content Marketing

High-signal content topics:

- "Why production runbooks fail in real incidents"
- "A practical guide to governed runbook execution"
- "Approval gates for SRE teams without ServiceNow overhead"
- "How private runners make SaaS acceptable for production automation"
- "Runbook automation vs CI/CD: where each belongs"
- "Audit evidence for production operations"
- "How to turn a wiki runbook into an executable workflow"
- "AI-assisted runbook parsing without autonomous production changes"

### Community Strategy If Open Core

If open core is adopted:

- Publish excellent Docker Compose quick start.
- Provide example runbooks for common operations.
- Provide runner installation guides for AWS, Kubernetes, and bare VM.
- Make docs strong enough that a senior SRE can evaluate in under one hour.
- Keep community support async and bounded.
- Convert heavy support questions into paid onboarding.

## 13. Business Roadmap

### Phase 0: Finalize Product Definition

Goal: Make the category, buyer, and commercial promise crisp.

Deliverables:

- Positioning statement.
- ICP and disqualification criteria.
- Security posture one-pager.
- Pilot proposal template.
- Three demo runbooks.
- Pricing sheet.
- Customer discovery script.

### Phase 1: Design Partner Pilots

Goal: Prove that real teams will use governed runbook execution on real workflows.

Target:

- 5 design partners.
- $5,000-$15,000 per pilot.
- 3-5 real runbooks per customer.
- One repeatable onboarding path.

Learning goals:

- Which runbooks are urgent enough?
- Which integrations are deal-breakers?
- Is private runner deployment mandatory?
- What audit evidence is actually reviewed?
- What price creates friction?

### Phase 2: Paid Team and Business SaaS

Goal: Convert pilots into recurring revenue.

Targets:

- 10 paying customers.
- $10k-$30k MRR.
- 80%+ pilot-to-paid conversion among qualified pilots.
- Documented onboarding runbook.

Build business systems:

- Billing and usage tracking.
- Support process.
- Customer health metrics.
- Security review packet.
- Product analytics.

### Phase 3: Enterprise Readiness

Goal: Win larger accounts without drowning in custom work.

Add:

- SSO/SAML/OIDC and SCIM if not already complete.
- Advanced RBAC.
- Audit export.
- Custom retention.
- Private runners with HA.
- Deployment review process.
- Support SLAs.
- Procurement and security docs.
- Private cloud package.

Revenue target:

- $500k-$1M ARR.
- 3-5 enterprise customers.
- Annual contract value from $40k-$150k.

### Phase 4: Open Core or Community Edition

Goal: Increase distribution if bottom-up demand is visible.

Only launch if:

- The paid value boundary is proven.
- Support load is manageable.
- Documentation is strong.
- License is final.
- The team has capacity to maintain community trust.

Success metrics:

- GitHub stars are not enough.
- Track activated deployments, weekly active workspaces, workflows created, executions completed, community-to-pipeline conversion, and enterprise inbound.

### Phase 5: Platform Expansion

Goal: Become the production operations governance layer.

Expansion paths:

- Template library for common production procedures.
- Policy packs for regulated workflows.
- Deep Slack/PagerDuty/Jira/ServiceNow integrations.
- SIEM/audit exports.
- Runner marketplace or plugin model.
- Workflow recommendations from historical execution data.
- Managed enterprise runners.
- Compliance-specific packages.

## 14. Operating Metrics

### Product Metrics

- Organizations created.
- Active teams.
- Runbooks imported.
- Workflows published.
- Executions started.
- Executions completed successfully.
- Executions blocked by policy.
- Approval requests created.
- Approval decision latency.
- Failed step rate.
- Mean execution duration.
- Artifact/log views.
- Audit exports.
- Runner heartbeat reliability.

### Business Metrics

- Discovery calls per week.
- Qualified opportunities.
- Pilot starts.
- Pilot conversion rate.
- MRR/ARR.
- Gross margin by deployment type.
- Sales cycle length.
- Expansion revenue.
- Churn.
- Support hours per customer.
- Deployment time per customer.

### Key Early Signal

The most important early product signal is not signups. It is:

> A customer runs real operational procedures through the platform repeatedly, then uses the audit/execution record afterward.

## 15. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Product is perceived as "another workflow tool" | Weak differentiation | Lead with governed production operations, private runners, audit, and approvals |
| AI positioning creates trust concerns | Security teams block adoption | Message AI as advisory only |
| Private deployments consume all engineering time | Low margin | Price private cloud high and standardize IaC/support bundles |
| Open core gives away paid value | Weak monetization | Use buyer-based packaging; keep management/compliance features paid |
| Enterprise asks arrive too early | Roadmap distraction | Qualify hard; use paid pilots only |
| Runner execution creates security risk | Trust loss | Keep least-privilege runner tokens, environment isolation, scoped secrets, and audit |
| Integrations sprawl | Product complexity | Start with Slack, PagerDuty, Jira, webhooks; add others only from paid demand |
| Support burden grows faster than revenue | Burn risk | Charge for onboarding and support; build support bundle tooling |

## 16. Recommended Next Business Actions

1. Choose positioning: "governed runbook execution platform."
2. Create a 10-slide sales deck around production runbook risk.
3. Build a security posture one-pager focused on private runners and control-plane boundaries.
4. Define the first three demo workflows: deploy rollback, database maintenance, incident remediation.
5. Draft a paid pilot SOW with success criteria and conversion terms.
6. Interview 20 platform/SRE leaders before launching open core.
7. Start with hosted single-tenant pilots, not a free community launch.
8. Track customer evidence needs: audit, logs, artifacts, approvals, policy decisions.
9. Price pilots high enough to filter serious buyers.
10. Revisit open core after pilot conversion data proves what must stay paid.

## 17. Source Notes

Repo sources reviewed:

- `README.md`
- `docs/reports/repository-to-startup-analysis-report.md`
- `docs/architecture/architecture-overview.md`
- `docs/architecture/data-model.md`
- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-10-aws-deployment-workflows-blueprint.md`
- `docker-compose.yml`
- `packages/workflow-schema/workflow.schema.json`
- `apps/web/src/app/router.tsx`
- Current Django models for executions, approvals, policies, and audit.

External market and deployment references:

- GitLab stewardship and open core model: https://handbook.gitlab.com/handbook/company/stewardship/
- Open Core Ventures open-core model: https://handbook.opencoreventures.com/open-core-model/
- Open Core Ventures buyer-based open core: https://handbook.opencoreventures.com/startup-manual/buyer-based-open-core
- PagerDuty Incident Management pricing: https://www.pagerduty.com/pricing/
- PagerDuty Runbook Automation pricing: https://www.pagerduty.com/pricing/process-automation/
- Rundeck introduction and commercial Runbook Automation notes: https://docs.rundeck.com/docs/about/introduction.html
- Windmill pricing: https://www.windmill.dev/pricing
- FireHydrant pricing: https://firehydrant.com/pricing
- AWS Fargate pricing: https://aws.amazon.com/fargate/pricing/
- Amazon RDS for PostgreSQL pricing: https://aws.amazon.com/rds/postgresql/pricing/
- AWS Secrets Manager pricing: https://aws.amazon.com/secrets-manager/pricing/
- GitHub Actions OIDC for AWS: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services
- Amazon ECS deployment circuit breaker: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html
- Amazon ECS Fargate task networking: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html
- Amazon S3 Block Public Access: https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html
