import { useParams } from 'react-router-dom'

import { useExecutionAuditTrail } from '../../features/audit/hooks/useExecutionAuditTrail'
import type { AuditEvent } from '../../features/audit/types'
import { useExecutionDetail } from '../../features/executions/hooks/useExecutionDetail'
import type { PolicyEvaluationSummary } from '../../features/policies/types'
import { getApiErrorMessage } from '../../shared/api/client'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

function getStepPillClass(status: string) {
  if (status === 'succeeded') return 'pill pill--success'
  if (status === 'failed') return 'pill pill--danger'
  if (status === 'waiting_for_approval') return 'pill pill--warn'
  if (status === 'running') return 'pill pill--info'
  return 'pill'
}

function getPolicyOutcomePillClass(outcome: string) {
  if (outcome === 'approval_required') return 'pill pill--warn'
  if (outcome === 'auto_approve') return 'pill pill--success'
  if (outcome === 'block') return 'pill pill--danger'
  return 'pill'
}

function getPolicyOutcomeLabel(outcome: string) {
  if (outcome === 'approval_required') return 'Approval Required'
  if (outcome === 'auto_approve') return 'Auto Approved'
  if (outcome === 'block') return 'Blocked'
  return outcome
}

function PolicyEvaluationBadge({ evaluation }: { evaluation: PolicyEvaluationSummary }) {
  const floorApplied = evaluation.outcome !== evaluation.effective_outcome

  return (
    <div style={{ marginTop: '0.25rem', fontSize: '0.85em' }}>
      <span className={getPolicyOutcomePillClass(evaluation.effective_outcome)}>
        {getPolicyOutcomeLabel(evaluation.effective_outcome)}
      </span>{' '}
      {evaluation.decision_source === 'policy_rule' ? (
        <span className="muted">
          via {evaluation.policy_name ?? 'policy'} · rule: {evaluation.rule_name ?? 'unknown'}
        </span>
      ) : (
        <span className="muted">Workflow default</span>
      )}
      {evaluation.reason ? (
        <p className="muted" style={{ marginTop: '0.125rem' }}>
          {evaluation.reason}
        </p>
      ) : null}
      {floorApplied ? (
        <p
          className="banner banner--warn"
          style={{ marginTop: '0.25rem', padding: '0.25rem 0.5rem' }}
        >
          Policy returned Auto Approve but Approval Required floor was applied.
        </p>
      ) : null}
    </div>
  )
}

function formatDateTime(value: string | null) {
  if (!value) {
    return 'Not set'
  }

  return new Date(value).toLocaleString()
}

function formatEventType(eventType: string) {
  return eventType.replaceAll('_', ' ').replaceAll('.', ' ')
}

function metadataText(event: AuditEvent) {
  const metadata = event.metadata
  const parts = []
  if (typeof metadata.previous_status === 'string' && typeof metadata.new_status === 'string') {
    parts.push(`From ${metadata.previous_status} to ${metadata.new_status}`)
  }
  if (typeof metadata.step_key === 'string') {
    parts.push(`Step ${metadata.step_key}`)
  }
  if (typeof metadata.risk_level === 'string' && metadata.risk_level) {
    parts.push(`Risk ${metadata.risk_level}`)
  }
  if (typeof metadata.outcome === 'string') {
    parts.push(`Outcome ${metadata.outcome}`)
  }
  if (typeof metadata.reason === 'string' && metadata.reason) {
    parts.push(`Reason ${metadata.reason}`)
  }
  if (typeof metadata.decision === 'string') {
    parts.push(`Decision ${metadata.decision}`)
  }
  return parts.join(' · ')
}

function AuditTrailPanel({
  events,
  isLoading,
  error,
}: {
  events: AuditEvent[]
  isLoading: boolean
  error: unknown
}) {
  const timelineEvents = [...events].reverse()

  return (
    <div className="stack-md">
      <h3>Audit trail</h3>
      {isLoading ? <p className="muted">Loading audit trail…</p> : null}
      {error ? <p className="banner banner--error">{getApiErrorMessage(error)}</p> : null}
      {!isLoading && !error && timelineEvents.length === 0 ? (
        <p className="muted">No audit events recorded yet.</p>
      ) : null}
      {timelineEvents.length > 0 ? (
        <ol className="step-list">
          {timelineEvents.map((event) => (
            <li className="step-list__item" key={event.id}>
              <div>
                <strong>{formatEventType(event.event_type)}</strong>
                <p className="muted">
                  {event.actor_label || event.actor_type} · {event.object_type}
                </p>
                {metadataText(event) ? <p className="muted">{metadataText(event)}</p> : null}
              </div>
              <div className="step-list__meta">
                <span className="pill">{event.actor_type}</span>
                <span className="muted">{formatDateTime(event.occurred_at)}</span>
              </div>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  )
}

export function ExecutionDetailPage() {
  const { executionId } = useParams()
  const executionQuery = useExecutionDetail(executionId ?? null)
  const auditQuery = useExecutionAuditTrail({
    executionId: executionId ?? null,
    organizationId: executionQuery.data?.organization_id ?? null,
    executionStatus: executionQuery.data?.status ?? null,
  })

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Step 5</p>
        <h2>Execution detail</h2>
        <p className="muted">This page polls Django while the execution is active.</p>
      </div>

      {executionQuery.isLoading ? <p className="muted">Loading execution…</p> : null}
      {executionQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(executionQuery.error)}</p>
      ) : null}

      {executionQuery.data ? (
        <>
          <div className="detail-grid">
            <div>
              <p className="detail-grid__label">Status</p>
              <p>{executionQuery.data.status}</p>
            </div>
            <div>
              <p className="detail-grid__label">Workflow version</p>
              <p>{executionQuery.data.workflow_version}</p>
            </div>
            <div>
              <p className="detail-grid__label">Started</p>
              <p>{formatDateTime(executionQuery.data.started_at)}</p>
            </div>
            <div>
              <p className="detail-grid__label">Finished</p>
              <p>{formatDateTime(executionQuery.data.finished_at)}</p>
            </div>
            <div>
              <p className="detail-grid__label">Runner</p>
              <p>{executionQuery.data.claimed_by_runner_id || '—'}</p>
            </div>
            <div>
              <p className="detail-grid__label">Claimed</p>
              <p>{formatDateTime(executionQuery.data.claimed_at)}</p>
            </div>
            <div>
              <p className="detail-grid__label">Last heartbeat</p>
              <p>{formatDateTime(executionQuery.data.last_heartbeat_at)}</p>
            </div>
          </div>

          {ACTIVE_EXECUTION_STATUSES.has(executionQuery.data.status) ? (
            <p className="banner banner--info">Polling for runner updates…</p>
          ) : null}

          <div className="stack-md">
            <h3>Steps</h3>
            <ol className="step-list">
              {executionQuery.data.steps.map((step) => (
                <li className="step-list__item" key={step.id}>
                  <div>
                    <strong>
                      {step.position}. {step.name}
                    </strong>
                    <p className="muted">
                      {step.step_type} · risk {step.risk_level}
                      {step.requires_approval ? ' · approval required' : ''}
                    </p>
                    {step.status === 'waiting_for_approval' ? (
                      <p className="banner banner--warn" style={{ marginTop: '0.25rem' }}>
                        Awaiting approval before command execution.{' '}
                        <a href="/approvals">Go to Approvals Inbox</a>
                      </p>
                    ) : null}
                    {step.error_message && step.error_message !== 'policy_blocked' ? (
                      <p className="field__error">{step.error_message}</p>
                    ) : null}
                    {step.error_message === 'policy_blocked' ? (
                      <p className="banner banner--error" style={{ marginTop: '0.25rem' }}>
                        Blocked by policy before command execution.
                      </p>
                    ) : null}
                    {step.policy_evaluation ? (
                      <PolicyEvaluationBadge evaluation={step.policy_evaluation} />
                    ) : null}
                  </div>
                  <div className="step-list__meta">
                    <span className={getStepPillClass(step.status)}>{step.status}</span>
                    <span className="muted">exit {step.exit_code ?? '—'}</span>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <AuditTrailPanel
            events={auditQuery.data?.results ?? []}
            isLoading={auditQuery.isLoading}
            error={auditQuery.error}
          />
        </>
      ) : null}
    </section>
  )
}
