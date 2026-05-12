import { Link } from 'react-router-dom'

import { useExecutions } from '../../features/executions/hooks/useExecutions'
import { useWorkflows } from '../../features/workflows/hooks/useWorkflows'
import { getApiErrorMessage } from '../../shared/api/client'

const ACTIVE_STATUSES = ['queued', 'claimed', 'running']

export function WorkflowsPage() {
  const workflowsQuery = useWorkflows()
  const activeExecutionsQuery = useExecutions(ACTIVE_STATUSES)
  const activeWorkflowIds = new Set(
    (activeExecutionsQuery.data ?? [])
      .filter((e) => e.status === 'queued' || e.last_heartbeat_at !== null)
      .map((e) => e.workflow_id)
  )

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <h2>Workflows</h2>
      </div>

      {workflowsQuery.isLoading ? <p className="muted">Loading workflows…</p> : null}
      {workflowsQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(workflowsQuery.error)}</p>
      ) : null}

      {workflowsQuery.data?.length ? (
        <ul className="list">
          {[...workflowsQuery.data]
            .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
            .map((workflow) => (
              <li className="list__item" key={workflow.id}>
                <div>
                  <strong>{workflow.name}</strong>
                  <p className="muted">
                    v{workflow.version} · <span className="pill">{workflow.status}</span> ·{' '}
                    {new Date(workflow.created_at).toLocaleString()}
                    {activeWorkflowIds.has(workflow.id) ? (
                      <span className="pill pill--info" style={{ marginLeft: '0.5rem' }}>
                        Running
                      </span>
                    ) : null}
                    {workflow.requires_review ? (
                      <span className="pill pill--warn" style={{ marginLeft: '0.5rem' }}>
                        Needs review
                      </span>
                    ) : null}
                  </p>
                </div>
                <Link className="button button--ghost" to={`/workflows/${workflow.id}`}>
                  View
                </Link>
              </li>
            ))}
        </ul>
      ) : null}

      {!workflowsQuery.isLoading && !workflowsQuery.error && !workflowsQuery.data?.length ? (
        <p className="muted">No workflows yet. Generate one from a runbook.</p>
      ) : null}
    </section>
  )
}
