# Phase 10.5 Integrations Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-28 |
| Scope | Read-only implementation audit of Phase 10.5 Integrations |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-05-integrations-blueprint.md`, prior Phase 10.1-10.4 implementation status docs, and Phase 10.6 readiness requirements |
| Verdict | **Not ready for Phase 10.6 sign-off yet**: the core integration path is implemented and API/runner/web tests pass, but lint fails, manual end-to-end verification is missing, and SSRF dispatch remains DNS-TOCTOU vulnerable relative to the Phase 10.5 blueprint. |

## 1. Executive verdict

Phase 10.5 Integrations is substantially implemented, but it should not be signed off as the baseline for Phase 10.6 Richer AI Parsing yet.

The main architecture is in place: Django owns integration records, encrypted webhook credentials, public management APIs, delivery-attempt logging, audit events for integration management, outbound dispatch, execution/approval/artifact trigger hooks, and a React settings UI. The runner still does not call external systems, and integration failures are caught so normal delivery failures do not affect execution state.

The blockers are verification and security-hardening gaps:

1. `make lint` fails on import ordering in `apps/api/apps/integrations/tests/test_api.py`.
2. Dispatch-time SSRF protection re-validates the URL, but `_dispatch_webhook()` still posts to the original URL through `httpx`, allowing DNS to be resolved a second time. This does not satisfy the blueprint's DNS pinning requirement.
3. The Phase 10.5 manual end-to-end gate is not recorded.
4. The dispatch budget settings and bounded parallel dispatch required by the blueprint are absent.
5. Event taxonomy drift exists: approval decisions emit `approval.approved`/`approval.rejected` instead of the required `approval.decided`, and execution creation emits `execution.created` while `execution.started` is emitted later when the first step starts.

Do not start Phase 10.6 until the required fixes in section 7 are completed or explicitly accepted in writing. No application-code fixes were made during this audit.

## 2. Implemented scope

- `apps.integrations` is registered in `INSTALLED_APPS`.
- `/api/v1/integrations/` is mounted as a public management API.
- `IntegrationConnection` and `IntegrationDeliveryAttempt` models exist and inherit UUID `BaseModel`.
- Integration records are organization-scoped and delivery attempts denormalize `organization`.
- Integration indexes cover organization/active/type, organization/created time, integration/attempted time, organization/attempted time, and event/attempted time.
- Webhook credentials are stored in `encrypted_credentials` using Fernet.
- Public serializers omit `encrypted_credentials` and expose `credentials_configured`.
- Config output is recursively redacted for sensitive keys and URL-looking strings.
- Credential write paths validate and encrypt webhook URLs.
- Creation, update, and deactivation emit `integration.created`, `integration.updated`, and `integration.deactivated` audit events.
- Delivery attempts are recorded for success, non-2xx responses, timeouts, validation failures, and decryption failures.
- `last_delivery_at` and `last_delivery_status` are updated after each attempt.
- `IntegrationService.notify(...)` filters active connections by organization and event type.
- Generic webhook and Slack webhook payload builders exist.
- Payload previews scrub secret-looking keys and URL-looking values.
- Integration failures are caught in the dispatch path and represented as failed delivery attempts where possible.
- Execution service emits integration notifications for execution creation, execution started, step started, step failed, execution completed, execution failed, and execution cancelled.
- Approval service emits integration notifications for approval requested and terminal human approval decisions.
- Artifact upload emits the optional `artifact.uploaded` notification.
- Public list, create, detail, patch, deactivate, and delivery-history endpoints exist.
- Public integration detail/deactivate/delivery-history APIs require an `organization_id` query parameter and scope UUID lookup by organization.
- React has integration types, API functions, React Query hooks, list/create/deactivate UI, detail page, delivery history view, route registration, and tests.
- Runner code remains uninvolved in external dispatch.
- No queue, Celery worker, Kafka, RabbitMQ, SQS, EventBridge, inbound webhook system, PagerDuty Events API, Jira integration, or AI-service dependency was introduced.

## 3. Missing scope

- No recorded manual end-to-end verification for create integration, receive execution/approval/terminal events, deactivate integration, event filtering, SSRF rejection, encrypted credential inspection, and payload/audit redaction.
- `INTEGRATION_DISPATCH_BUDGET_SECONDS` is not configured.
- `INTEGRATION_MAX_PER_TRIGGER` is not configured.
- Dispatch is sequential, not bounded by the blueprint's per-trigger budget and `ThreadPoolExecutor` plan.
- `_dispatch_webhook()` does not pin the resolved IP for the outbound HTTP call.
- No public delivery-attempt detail endpoint exists for `GET /api/v1/integrations/{id}/deliveries/{delivery_id}/`.
- Delivery history is returned as `{"results": [...]}` only; it is not paginated with `count`, `next`, and `previous`.
- Public list returns a bare array, not the blueprint's paginated response shape.
- Integration create/update serializers do not include `event_types` as typed serializer fields; the view passes raw `event_types` to the service for validation.
- `PATCH /api/v1/integrations/{id}/` cannot patch `is_active`, though the explicit deactivate action exists.
- No confirmation prompt exists before frontend deactivation.
- The create form uses a plain URL input and comma-separated event type text input, not a masked/password URL field and checkbox group.
- The frontend has no update/edit form for name, event types, config, or credential rotation.
- The integration detail page does not display `payload_preview`, so delivery debugging visibility is limited.
- Production settings do not require `INTEGRATION_FERNET_KEY` at startup.
- Base/test settings do not provide a generated test key by configuration; integration tests use a fixture instead.
- No max-connections-per-org guard exists.

## 4. Blueprint drift

- The dedicated blueprint's required creation trigger is `execution.started`; this implementation sends `execution.created` at execution record creation and sends `execution.started` only when the execution transitions from claimed to running.
- Approval decision notifications use `approval.approved` and `approval.rejected`; the blueprint requires `approval.decided` with a `decision` field. `approval.decided` exists in the supported event set but is not emitted by `decide_approval()`.
- The implementation adds extra integration events outside the five required trigger points: `execution.created`, `execution.cancelled`, `execution_step.started`, `execution_step.failed`, `execution_step.waiting_for_approval`, `approval.approved`, `approval.rejected`, and `artifact.uploaded`.
- Execution-failed payload context does not include `failed_step_name` or `failed_step_position`.
- Execution payload context omits `workflow_name`, so Slack payloads can render `Unknown workflow`.
- Approval-request payload context omits `step_name` and `step_position`.
- Dispatch is called after the local `transaction.atomic()` block exits, but it does not use `transaction.on_commit()`. This is usually post-commit for these direct calls, but it does not preserve the blueprint's guarantee if the service is called inside a wider outer transaction.
- The SSRF validator checks scheme, localhost, private/link-local/reserved/multicast/unspecified addresses, userinfo, and metadata IPs, but it does not explicitly block `.local` hostnames, `metadata.google.internal`, or well-known internal service ports.
- The blueprint requires DNS resolution to be pinned for the outbound call; the implementation validates first and then lets `httpx` resolve the original hostname again.
- The roadmap names `Integration`/`IntegrationEvent`; the dedicated blueprint renamed these to `IntegrationConnection`/`IntegrationDeliveryAttempt`. The implementation correctly follows the dedicated blueprint naming.
- The API uses `/delivery-attempts/`; the blueprint examples use `/deliveries/`. This is acceptable if kept stable, but it is contract drift.
- Audit events for management are fail-closed because service methods do not catch `AuditService.emit(...)` failures. This is stronger than the blueprint's main concern for credential rotation auditability, but tests do not explicitly prove rollback semantics.

## 5. Test coverage review

Verification run during this audit:

```sh
make test-api
# 384 passed

make test-runner
# 72 passed

make test-web
# 58 passed

make lint
# failed: ruff import ordering in apps/integrations/tests/test_api.py
```

Covered:

- Integration credential encryption/decryption round trip.
- Missing Fernet key raises a clear error when encryption is attempted.
- Encrypted credential bytes do not contain plaintext webhook URL.
- SSRF validator rejects `http`, `file`, localhost, IPv4 private ranges, link-local metadata IP, IPv6 loopback, and IPv6 link-local.
- Integration model defaults and delivery-attempt records.
- Successful dispatch creates a successful delivery attempt and updates last delivery status.
- Non-2xx dispatch creates a failed delivery attempt.
- Timeout creates a failed delivery attempt.
- Organization-scoped dispatch does not send org A events to org B connections.
- Inactive connections do not dispatch.
- Event type filtering works.
- Credential decryption failure records a failed attempt.
- Payload preview redacts webhook URL, claim token, nested API token, and URL-looking values.
- Integration create/update/deactivate emits audit events.
- Public API list scopes by organization.
- Public API create stores encrypted credentials and excludes secrets in responses.
- Public API detail excludes encrypted credentials and plaintext URL.
- Public API deactivate prevents future dispatch.
- Delivery-history endpoint returns attempts.
- Invalid webhook URL and metadata endpoint create requests return 400.
- Serializer regression test checks plaintext URL never appears in create/list/detail/patch/deactivate responses.
- Execution service tests cover integration notification on completion/failure and notification failure not propagating.
- Approval service tests cover approval-request and approval-decision notification hooks.
- Artifact service tests cover optional artifact-upload notification.
- Frontend tests cover list, empty state, create submission, URL removal from DOM after save, deactivate action, delivery history, failed delivery display, and missing organization ID.

Gaps:

- `make lint` fails.
- No test covers DNS pinning or DNS rebinding/TOCTOU prevention.
- No test covers `.local`, `metadata.google.internal`, blocked internal ports, or URL userinfo in the SSRF validator.
- No test proves dispatch stays under a per-trigger budget with many active integrations.
- No test proves one delivery-attempt DB write failure cannot stop later connections from being attempted.
- No test proves `notify()` is registered through `transaction.on_commit()`.
- No test checks `approval.decided`, because the implementation emits `approval.approved`/`approval.rejected`.
- No test asserts execution-failed payload includes failed step name/position.
- No API tests enforce paginated `count`/`next`/`previous` response shapes.
- No API delivery-attempt detail endpoint tests exist.
- No frontend tests cover create API field-level URL validation display, generic create failure display, list load error, detail load error, delivery load error, inactive row styling, or deactivation confirmation.
- No manual full-stack verification record was found.

## 6. Security/operational risks

- Public APIs still use global pre-auth `AllowAny`; organization query parameters reduce accidental cross-tenant reads but are not authorization.
- The integration list/detail/deactivate/delivery endpoints scope by `organization_id`, but `POST /api/v1/integrations/` accepts any existing organization ID until Phase 10.7 auth adds membership enforcement.
- `INTEGRATION_FERNET_KEY` defaults to an empty string in base/prod settings and fails only when encryption/decryption is attempted, not at startup.
- If `INTEGRATION_FERNET_KEY` changes or is missing, dispatch records `validation_error` attempts but does not surface credential corruption beyond delivery history.
- Dispatch-time SSRF validation is vulnerable to DNS rebinding because `httpx` performs its own DNS lookup after validation.
- The SSRF validator is less complete than the blueprint blocklist for `.local`, metadata hostnames, and internal service ports.
- Sequential dispatch can add `N * INTEGRATION_DISPATCH_TIMEOUT_SECONDS` latency to request paths. This is especially risky for runner-facing terminal execution updates.
- Because dispatch is synchronous and unbounded by count, one organization can configure enough integrations to slow state-transition responses.
- Delivery attempts have no retention policy or purge command; the table can grow quickly with step-level events enabled.
- Payload redaction is key-fragment and URL-prefix based. Secret-looking substrings inside otherwise allowed string values can still be stored in payload previews.
- Generic webhook payloads include any scrubbed context values the caller supplies. Current context builders avoid commands, raw output, storage keys, and claim tokens, but this relies on future call sites using safe context.
- Integration management audit metadata omits credentials, but admin edits to `IntegrationConnection` do not go through the service and therefore do not emit management audit events.
- Admin hides `encrypted_credentials`, but `IntegrationConnectionAdmin` can still edit fields without service validation/audit.
- Integration failure isolation depends on `_record_attempt()` succeeding; a database failure while recording one attempt can stop later connections in the outer `notify()` loop.

## 7. Required fixes before Phase 10.6

1. Fix the lint failure in `apps/api/apps/integrations/tests/test_api.py` and rerun `make lint`.

2. Make dispatch SSRF protection DNS-TOCTOU safe.
   - Resolve and validate once at dispatch time.
   - Pin the resolved IP for the actual HTTP call.
   - Preserve the original hostname for TLS/SNI/Host handling in a tested way.
   - Add tests that prove `httpx` is not given the original URL for dispatch after validation.

3. Complete the SSRF blocklist required by the blueprint.
   - Block `.local` hostnames.
   - Block `metadata.google.internal`.
   - Block userinfo explicitly in tests.
   - Block well-known internal ports or document an explicit allowlist decision.

4. Add bounded dispatch controls.
   - Add `INTEGRATION_DISPATCH_BUDGET_SECONDS`.
   - Add `INTEGRATION_MAX_PER_TRIGGER`.
   - Enforce deterministic connection selection when the max is exceeded.
   - Add tests for budget exceeded behavior and skipped excess integrations.

5. Align event taxonomy with the required Phase 10.5 contract or document the replacement contract.
   - Emit `approval.decided` with `decision`.
   - Decide whether `execution.created` is a private extra event or whether `execution.started` should fire at execution creation as the blueprint states.
   - Ensure the frontend event selection UI reflects only supported/public event types.

6. Improve required payload context.
   - Include workflow name for execution payloads.
   - Include failed step name and position for `execution.failed` where derivable.
   - Include step name and position for `approval.requested`.

7. Use `transaction.on_commit()` for integration trigger hooks so dispatch cannot happen before the true outer transaction commits.

8. Record the Phase 10.5 manual end-to-end verification gate:
   - Create a generic webhook integration.
   - Receive execution, approval, decision, and terminal events.
   - Deactivate and prove dispatch stops.
   - Configure event filtering and prove only matching events are delivered.
   - Verify blocked SSRF URL is rejected.
   - Confirm encrypted DB credentials are not plaintext.
   - Confirm audit metadata and delivery previews contain no webhook URL or credential value.

## 8. Recommended non-blocking follow-ups

- Add paginated integration list and delivery-history responses with `count`, `next`, and `previous`.
- Add `GET /api/v1/integrations/{id}/deliveries/{delivery_id}/` or explicitly remove it from the contract.
- Rename `/delivery-attempts/` to `/deliveries/` or document `/delivery-attempts/` as the stable API path.
- Add an edit/rotate-credentials UI.
- Replace comma-separated event type entry with a checkbox group of known public event types.
- Change the webhook URL input to `type="password"` or another masked control during entry.
- Add a confirmation prompt before deactivation.
- Display safe `payload_preview` details in the delivery history page.
- Add frontend tests for load errors, validation errors, inactive rows, deactivation failure, and delivery empty/error states.
- Add service tests for audit rollback on create/update/deactivate failure.
- Add a management command or retention note for pruning old `IntegrationDeliveryAttempt` rows.
- Make `IntegrationConnectionAdmin` read-only or route admin changes through audited service operations.
- Add a max-connections-per-organization guard if integrations remain pre-auth for any extended period.
- Consider value-level redaction helpers for payload preview strings before AI-generated summaries are added to notification payloads.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-05-integrations-blueprint.md`
- `docs/blueprints/phase-10-06-richer-ai-parsing-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-implementation-status.md`
- `docs/blueprints/phase-10-02-policies-implementation-status.md`
- `docs/blueprints/phase-10-03-audit-trail-implementation-status.md`
- `docs/blueprints/phase-10-04-artifacts-implementation-status.md`
- `.env.example`
- `docker-compose.yml`
- `apps/api/requirements/base.txt`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/dev.py`
- `apps/api/config/settings/test.py`
- `apps/api/config/settings/prod.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_services.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/artifacts/tests/test_services.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/tests/test_services.py`
- `apps/api/apps/integrations/__init__.py`
- `apps/api/apps/integrations/apps.py`
- `apps/api/apps/integrations/models.py`
- `apps/api/apps/integrations/migrations/0001_initial.py`
- `apps/api/apps/integrations/migrations/0002_alter_integrationconnection_event_types.py`
- `apps/api/apps/integrations/admin.py`
- `apps/api/apps/integrations/crypto.py`
- `apps/api/apps/integrations/ssrf.py`
- `apps/api/apps/integrations/services.py`
- `apps/api/apps/integrations/serializers.py`
- `apps/api/apps/integrations/views.py`
- `apps/api/apps/integrations/urls.py`
- `apps/api/apps/integrations/tests/conftest.py`
- `apps/api/apps/integrations/tests/test_api.py`
- `apps/api/apps/integrations/tests/test_crypto.py`
- `apps/api/apps/integrations/tests/test_models.py`
- `apps/api/apps/integrations/tests/test_services.py`
- `apps/api/apps/integrations/tests/test_ssrf.py`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/app/router.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/features/integrations/types.ts`
- `apps/web/src/features/integrations/api/integrationsApi.ts`
- `apps/web/src/features/integrations/hooks/useIntegrations.ts`
- `apps/web/src/features/integrations/hooks/useCreateIntegration.ts`
- `apps/web/src/features/integrations/hooks/useDeactivateIntegration.ts`
- `apps/web/src/features/integrations/hooks/useIntegrationDetail.ts`
- `apps/web/src/features/integrations/hooks/useIntegrationDelivery.ts`
- `apps/web/src/routes/integrations/IntegrationsPage.tsx`
- `apps/web/src/routes/integrations/IntegrationsPage.test.tsx`
- `apps/web/src/routes/integrations/IntegrationDetailPage.tsx`
- `apps/web/src/routes/integrations/IntegrationDetailPage.test.tsx`

## 10. Commands to run for verification

Focused backend integration verification:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/integrations/tests -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/executions/tests/test_services.py apps/approvals/tests/test_services.py apps/artifacts/tests/test_services.py -v
```

Focused frontend integration verification:

```sh
docker compose exec web npm test -- --run src/routes/integrations/IntegrationsPage.test.tsx src/routes/integrations/IntegrationDetailPage.test.tsx
```

Full regression gates:

```sh
make lint
make test-api
make test-runner
make test-web
```

Manual verification before Phase 10.6:

```sh
make up-d
make migrate
make seed-dev
make logs-api
make logs-runner
```

Manual verification must prove:

- A generic webhook integration can be created from the UI.
- The webhook receives the expected execution, approval, decision, and terminal events.
- Delivery failures create failed `IntegrationDeliveryAttempt` rows and do not affect execution state.
- Event type filtering suppresses non-matching events.
- Deactivation suppresses future dispatch.
- SSRF-blocked URLs return 400.
- `encrypted_credentials` does not contain the plaintext webhook URL.
- Public API responses do not contain credentials.
- Audit metadata and delivery previews do not contain webhook URLs, claim tokens, artifact storage keys, raw output, or credentials.

## Short summary

Phase 10.5 has the core integration plumbing in place, and API, runner, and web test suites pass. It is not ready for Phase 10.6 sign-off until lint is clean, DNS-pinned SSRF-safe dispatch and bounded dispatch are implemented or explicitly accepted, and the manual end-to-end integration gate is recorded.
