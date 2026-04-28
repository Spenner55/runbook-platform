# Phase 10.4 Readiness Verification Record

| Field | Value |
|---|---|
| Date | 2026-04-28 |
| Phase | 10.4 Artifacts |
| Purpose | Verify remediation of Phase 10.4 readiness audit gaps before Phase 10.5 Integrations |
| Result | Ready for Phase 10.5 |

## Scope Verified

- Artifact upload remains Django-controlled and runner-only through internal APIs.
- Public artifact list, download request, and content endpoints require tenant scope through `organization_id`.
- Local download URLs are signed and expiring; direct content access without a valid token is rejected.
- Artifact upload audit and download URL audit are fail-closed.
- Runner uploads after terminal execution are rejected.
- Artifact settings are present in Django settings and `.env.example`.
- Storage path containment, checksum requirement, MIME allowlist, metadata cap, quota limits, and artifact error states are covered by tests.

## Commands Run

```sh
make lint
# passed

make test-api
# 342 passed

make test-runner
# 72 passed

make test-web
# 51 passed
```

Additional targeted checks run during remediation:

```sh
docker compose exec api pytest apps/artifacts/tests -q
# 55 passed

docker compose exec runner pytest runner/tests/test_client.py -q
# 14 passed
```

## Manual Checks

- Verified the artifact download response now returns `/api/v1/artifacts/{id}/content/?organization_id=...&token=...` instead of a permanent content URL.
- Verified the frontend passes the execution organization ID to artifact list and download calls.
- Verified no claim token, storage key, or raw artifact bytes are added to audit metadata or public serializers.

## Rollback Notes

- The remediation is code/config only and does not add a database migration.
- Rollback would restore permanent local content URLs and remove `organization_id` from artifact frontend calls; that would re-open the Phase 10.4 audit gaps and should only be done for an emergency revert.
- Local artifact files created before this change remain readable only through the new grant-gated content endpoint.

## Residual Accepted Scope

- S3 object I/O remains deferred. Phase 10.4 validates S3 settings shape but still implements only the local storage backend.
- Authenticated tenant context remains deferred to Phase 10.7. Explicit `organization_id` scoping is the Phase 10.4/10.5 bridge.
- Generated-file directory collection remains deferred; stdout/stderr and explicit internal upload endpoints are the accepted Phase 10.4 baseline.
