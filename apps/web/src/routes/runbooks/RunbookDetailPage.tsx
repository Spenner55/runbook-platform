import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useRunbookDetail } from '../../features/runbooks/hooks/useRunbookDetail'
import { useRunbookWorkflows } from '../../features/workflows/hooks/useRunbookWorkflows'
import { getApiErrorMessage } from '../../shared/api/client'

export function RunbookDetailPage() {
  const { runbookId } = useParams()
  const runbookQuery = useRunbookDetail(runbookId ?? null)
  const workflowsQuery = useRunbookWorkflows(runbookId ?? null)
  const [expanded, setExpanded] = useState(false)

  const rawContent = runbookQuery.data?.raw_content ?? ''
  const truncated = rawContent.length > 400 && !expanded

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <Link className="muted" to="/runbooks">
          ← Runbooks
        </Link>

        {runbookQuery.isLoading ? <h2>Loading…</h2> : null}
        {runbookQuery.data ? (
          <>
            <h2>{runbookQuery.data.title}</h2>
            <p className="muted">
              <code>{runbookQuery.data.slug}</code>
            </p>
          </>
        ) : null}
        {runbookQuery.error ? (
          <p className="banner banner--error">{getApiErrorMessage(runbookQuery.error)}</p>
        ) : null}
      </div>

      {runbookQuery.data ? (
        <div className="detail-grid">
          <div>
            <p className="detail-grid__label">Status</p>
            <span className="pill">{runbookQuery.data.status}</span>
          </div>
          <div>
            <p className="detail-grid__label">Created</p>
            <p>{new Date(runbookQuery.data.created_at).toLocaleString()}</p>
          </div>
        </div>
      ) : null}

      {rawContent ? (
        <div className="stack-md">
          <h3>Raw content</h3>
          <pre className="code-block">
            {truncated ? rawContent.slice(0, 400) + '…' : rawContent}
          </pre>
          {rawContent.length > 400 ? (
            <button
              className="button button--ghost"
              onClick={() => setExpanded((v) => !v)}
              type="button"
            >
              {expanded ? 'Show less' : 'Show more'}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="stack-md">
        <div className="actions-row">
          <h3>Workflows</h3>
          <div>
            <Link
              className="button button--secondary"
              to={`/workflows/new?runbookId=${runbookId}`}
            >
              Generate workflow (AI)
            </Link>
          </div>
        </div>

        {workflowsQuery.isLoading ? <p className="muted">Loading workflows…</p> : null}
        {workflowsQuery.error ? (
          <p className="banner banner--error">{getApiErrorMessage(workflowsQuery.error)}</p>
        ) : null}

        {workflowsQuery.data?.length ? (
          <ul className="list">
            {workflowsQuery.data.map((workflow) => (
              <li className="list__item" key={workflow.id}>
                <div>
                  <strong>{workflow.name}</strong>
                  <p className="muted">
                    v{workflow.version} · <span className="pill">{workflow.status}</span>
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
          <p className="muted">No workflows yet. Generate one from this runbook.</p>
        ) : null}
      </div>
    </section>
  )
}
