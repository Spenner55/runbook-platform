import { useParams } from 'react-router-dom'

import { useExecutionDetail } from '../../features/executions/hooks/useExecutionDetail'
import { getApiErrorMessage } from '../../shared/api/client'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

function formatDateTime(value: string | null) {
  if (!value) {
    return 'Not set'
  }

  return new Date(value).toLocaleString()
}

export function ExecutionDetailPage() {
  const { executionId } = useParams()
  const executionQuery = useExecutionDetail(executionId ?? null)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Step 5</p>
        <h2>Execution detail</h2>
        <p className="muted">
          This page polls Django while the execution is active.
        </p>
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
            <p className="banner banner--info">
              Polling for runner updates…
            </p>
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
                    </p>
                    {step.error_message ? (
                      <p className="field__error">{step.error_message}</p>
                    ) : null}
                  </div>
                  <div className="step-list__meta">
                    <span className="pill">{step.status}</span>
                    <span className="muted">exit {step.exit_code ?? '—'}</span>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </>
      ) : null}
    </section>
  )
}
