import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useExecutions } from '../../features/executions/hooks/useExecutions'
import { getApiErrorMessage } from '../../shared/api/client'

const STATUS_FILTERS = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function getStatusPillClass(status: string) {
  if (status === 'succeeded') return 'pill pill--success'
  if (status === 'failed') return 'pill pill--danger'
  if (status === 'running' || status === 'claimed') return 'pill pill--info'
  if (status === 'cancelled') return 'pill'
  return 'pill'
}

export function ExecutionsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const executionsQuery = useExecutions(statusFilter === 'all' ? undefined : [statusFilter])

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>Executions</h2>
      </div>

      <div className="actions-row">
        {STATUS_FILTERS.map((s) => (
          <button
            className={s === statusFilter ? 'button button--sm' : 'button button--sm button--ghost'}
            key={s}
            onClick={() => setStatusFilter(s)}
            type="button"
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {executionsQuery.isLoading ? <p className="muted">Loading executions…</p> : null}
      {executionsQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(executionsQuery.error)}</p>
      ) : null}

      {executionsQuery.data?.length ? (
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Workflow</th>
              <th>Name</th>
              <th>Status</th>
              <th>Started</th>
              <th>Finished</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {executionsQuery.data.map((execution) => (
              <tr key={execution.id}>
                <td>
                  <code>{execution.id.slice(0, 8)}…</code>
                </td>
                <td>
                  <code>{execution.workflow_id.slice(0, 8)}…</code>
                </td>
                <td>{execution.workflow_name ?? '—'}</td>
                <td>
                  <span className={getStatusPillClass(execution.status)}>{execution.status}</span>
                </td>
                <td>{formatDateTime(execution.started_at)}</td>
                <td>{formatDateTime(execution.finished_at)}</td>
                <td>
                  <Link
                    className="button button--ghost button--sm"
                    to={`/executions/${execution.id}`}
                  >
                    View
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {!executionsQuery.isLoading && !executionsQuery.error && !executionsQuery.data?.length ? (
        <p className="muted">
          No executions{statusFilter !== 'all' ? ` with status "${statusFilter}"` : ''} yet.
        </p>
      ) : null}
    </section>
  )
}
