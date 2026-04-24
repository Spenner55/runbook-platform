import { useNavigate, useSearchParams } from 'react-router-dom'

import { useCreateWorkflow } from '../../features/workflows/hooks/useCreateWorkflow'
import { useRunbookDetail } from '../../features/runbooks/hooks/useRunbookDetail'
import { getApiErrorMessage } from '../../shared/api/client'

export function WorkflowCreatePage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const runbookId = searchParams.get('runbookId')
  const runbookQuery = useRunbookDetail(runbookId)
  const createWorkflow = useCreateWorkflow()

  async function handleCreateWorkflow() {
    if (!runbookId) {
      return
    }

    try {
      const workflow = await createWorkflow.mutateAsync({ runbook_id: runbookId })
      navigate(`/workflows/${workflow.id}`)
    } catch {
      // createWorkflow.error captures the failure; no navigation on error
    }
  }

  if (!runbookId) {
    return (
      <section className="panel">
        <div className="panel__header">
          <p className="eyebrow">Step 3</p>
          <h2>Select a runbook first</h2>
          <p className="muted">
            This page expects a <code>runbookId</code> query parameter.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Step 3</p>
        <h2>Create a workflow from a runbook</h2>
        <p className="muted">
          Django owns orchestration here and calls the internal AI parser behind the service layer.
        </p>
      </div>

      {runbookQuery.isLoading ? <p className="muted">Loading runbook context…</p> : null}
      {runbookQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(runbookQuery.error)}</p>
      ) : null}

      {runbookQuery.data ? (
        <div className="stack-md">
          <div className="detail-grid">
            <div>
              <p className="detail-grid__label">Title</p>
              <p>{runbookQuery.data.title}</p>
            </div>
            <div>
              <p className="detail-grid__label">Status</p>
              <p>{runbookQuery.data.status}</p>
            </div>
          </div>

          <div className="code-block">
            <pre>{runbookQuery.data.raw_content || 'No raw content stored.'}</pre>
          </div>

          {createWorkflow.error ? (
            <p className="banner banner--error">{getApiErrorMessage(createWorkflow.error)}</p>
          ) : null}

          <button
            className="button"
            disabled={createWorkflow.isPending}
            onClick={handleCreateWorkflow}
            type="button"
          >
            {createWorkflow.isPending ? 'Generating…' : 'Generate workflow'}
          </button>
        </div>
      ) : null}
    </section>
  )
}
