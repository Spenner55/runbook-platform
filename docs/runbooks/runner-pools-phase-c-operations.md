# Runner Pools Phase C Operations

This runbook covers the Phase C pilot runner-pool operations. It assumes Django
is the scheduling authority, runners call only `/api/v1/internal/`, and React
uses only public `/api/v1/` runner diagnostics.

## Safety Rules

- Use per-runner bearer tokens for internal runner endpoints. Legacy shared
  runner token mode is local/dev-test compatibility only.
- Treat registration tokens as one-time bootstrap secrets. Store them in a
  secret manager or ephemeral operator channel, never in tickets, docs, logs, or
  screenshots.
- The clear per-runner token is returned only at registration. Persist it only in
  the runner state file or local secret store with host-appropriate permissions.
- Never log runner tokens, registration tokens, token hashes, claim tokens,
  dispatch tokens, or target credentials.
- Public diagnostics must show health, pool, route, and capacity facts only.
  They must not show `token_hash`, registration token values, claim tokens,
  dispatch tokens, target credentials, or raw target metadata.

## Register Runner

1. Create or choose an active runner pool for the organization.
2. Create a scoped registration token for that pool with a short expiry and
   `max_registrations=1` unless an operator intentionally needs more.
3. Transfer the clear registration token to the runner host through a secret
   channel.
4. Start the runner with:
   - `API_BASE_URL`
   - `RUNNER_REGISTRATION_TOKEN`
   - optional `RUNNER_DISPLAY_NAME`
   - optional `RUNNER_INSTALL_FINGERPRINT`
   - `RUNNER_STATE_FILE` pointing at a persistent local file
5. Confirm the registration response persisted the canonical runner ID and
   per-runner bearer token in the runner state file.
6. Remove the bootstrap registration token from shell history and temporary
   files after startup.
7. Confirm the public runner list shows the runner as active and associated with
   the expected pool.

## Rotate Or Revoke Runner Credentials

Use rotation when the runner host remains trusted. Use revocation when the host
or token may be compromised.

For rotation:

1. Create a new short-lived registration token for the same pool.
2. Stop the runner.
3. Remove the runner state file from the host.
4. Start the runner with the new registration token and the same install
   fingerprint.
5. Confirm the existing runner identity re-registers, the per-runner token is
   rotated, and the old token no longer authenticates.

For revocation:

1. Use the public runner management API or UI to revoke the runner.
2. Confirm internal runner calls with that token return `401`.
3. Drain or fail any affected execution according to the stale execution
   recovery section below.
4. Issue a new registration token only after the host is trusted again.

## Drain Runner

1. Request drain on the runner from public runner management.
2. The runner remains allowed to heartbeat and finish its current execution.
3. New claim attempts return a drain response and the runner poll loop stops.
4. Confirm active execution count reaches zero before maintenance.
5. Reactivate or revoke the runner after maintenance, depending on whether the
   host should return to service.

## Drain Pool

1. Request drain on the pool from public runner-pool management.
2. Existing claimed executions may finish.
3. New claims from runners in the pool return a drain response.
4. Confirm pool active execution count reaches zero.
5. Disable the pool for extended outage or reactivate it when capacity should
   resume.

## Debug Route Miss

1. Open route diagnostics for the change.
2. Check the reported reason:
   - `route_miss`: no active route matched the target type and normalized
     identifier.
   - `missing_required_capability`: matched route or operation profile requires
     capabilities not present on the pool.
   - `multi_pool_unsupported`: targets resolve to different pools; Phase C
     supports one pool per change dispatch.
   - `pool_disabled` or `pool_draining`: matched pool is not accepting new
     claims.
3. Compare the change target `target_type`, normalized identifier, and
   environment with active `TargetConnectivityRoute` rows.
4. Prefer exact pilot routes. Use wildcard routes only when the reachability and
   trust boundary is deliberately shared.
5. Re-run dispatch preflight after correcting routes, pool status, or
   capabilities.

## Debug Offline Pool

1. Check runner list for the pool.
2. Confirm at least one runner is `active` and has `last_heartbeat_at` within
   `RUNNER_ONLINE_SECONDS`.
3. Inspect runner process logs for authentication failures, drain responses, or
   network errors.
4. Confirm the runner state file contains the expected canonical runner ID and a
   per-runner bearer token.
5. Re-register the runner if it was marked `offline` by the watchdog.
6. If all runners are unavailable, keep the pool disabled or draining until a
   healthy runner is online.

## Recover Stale Execution

1. Identify executions in `claimed` or `running` with stale
   `last_heartbeat_at`.
2. Check whether the runner is offline, revoked, disabled, or unreachable.
3. Run the stale execution recovery command or watchdog path used by the
   deployment.
4. Confirm the active `ExecutionLease` is expired or released exactly once.
5. Confirm target locks for failed/crashed change executions are released by the
   recovery/closure flow before redispatch.
6. Re-run dispatch preflight before any replacement dispatch.

## Verification Checklist

- `RUNNER_LEGACY_TOKEN_MODE` is disabled outside dev/test settings.
- Per-runner token auth succeeds; disabled and revoked runner tokens fail.
- Public APIs do not expose runner token, registration token, token hashes,
  claim token, dispatch token, or target credentials.
- Route diagnostics explain route miss, missing capability, offline pool, and
  capacity failures without secret material.
