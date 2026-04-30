# Phase 10.9 Step 7 Migration Safety Notes

These migrations add enum `CHECK` constraints and one integration dispatch index. They do not delete data, alter column types, or use concurrent index operations.

## Preflight Data Audit

Run these before applying the Step 7 migrations in any shared or production-like database. Each query should return zero rows.

```sql
SELECT status, COUNT(*) FROM executions_execution
WHERE status NOT IN ('queued', 'claimed', 'running', 'succeeded', 'failed', 'cancelled')
GROUP BY status;

SELECT status, COUNT(*) FROM executions_executionstep
WHERE status NOT IN ('pending', 'waiting_for_approval', 'running', 'succeeded', 'failed', 'skipped')
GROUP BY status;

SELECT status, COUNT(*) FROM approvals_approvalrequest
WHERE status NOT IN ('pending', 'approved', 'rejected', 'timed_out')
GROUP BY status;

SELECT decision, COUNT(*) FROM approvals_approvaldecision
WHERE decision NOT IN ('approved', 'rejected', 'timed_out')
GROUP BY decision;

SELECT source_type, COUNT(*) FROM approvals_approvaldecision
WHERE source_type NOT IN ('human', 'system')
GROUP BY source_type;

SELECT actor_type, COUNT(*) FROM audit_auditevent
WHERE actor_type NOT IN ('user', 'runner', 'system', 'api_client', 'unknown')
GROUP BY actor_type;

SELECT object_type, COUNT(*) FROM audit_auditevent
WHERE object_type NOT IN (
  'organization', 'runbook', 'workflow', 'execution', 'execution_step',
  'approval_request', 'approval_decision', 'policy', 'policy_rule',
  'policy_evaluation', 'artifact', 'integration_connection'
)
GROUP BY object_type;

SELECT type, COUNT(*) FROM integrations_integrationconnection
WHERE type NOT IN ('slack_webhook', 'generic_webhook', 'pagerduty')
GROUP BY type;

SELECT last_delivery_status, COUNT(*) FROM integrations_integrationconnection
WHERE last_delivery_status <> ''
  AND last_delivery_status NOT IN ('success', 'failed')
GROUP BY last_delivery_status;
```

## Reversibility

All Step 7 schema operations are Django-managed `AddConstraint` or `AddIndex` operations. They are reversible with the corresponding migration rollback.
