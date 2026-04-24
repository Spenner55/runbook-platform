import { useNavigate, useParams } from 'react-router-dom'

import { useCreateExecution } from '../../features/executions/hooks/useCreateExecution'
import { usePublishWorkflow } from '../../features/workflows/hooks/usePublishWorkflow'
import { useWorkflowDetail } from '../../features/workflows/hooks/useWorkflowDetail'
import { getApiErrorMessage } from '../../shared/api/client'

export function WorkflowDetailPage() {
  const { workflowId } = useParams()
  const navigate = useNavigate()
  const workflowQuery = useWorkflowDetail(workflowId ?? null)
  const publishWorkflow = usePublishWorkflow(workflowId ?? null)
  const createExecution = useCreateExecution()

  async function handlePublishWorkflow() {
    await publishWorkflow.mutateAsync()
  }

  async function handleCreateExecution() {
    if (!workflowId) {
      return
    }

    const execution = await createExecution.mutateAsync({ workflow_id: workflowId })
    navigate(`/executions/${execution.id}`)
  }

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Step 4</p>
        <h2>Workflow detail</h2>
        <p className="muted">
          Publish the generated workflow, then create an execution from the published version.
        </p>
      </div>

      {workflowQuery.isLoading ? <p className="muted">Loading workflow…</p> : null}
      {workflowQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(workflowQuery.error)}</p>
      ) : null}

      {workflowQuery.data ? (
        <>
          <div className="detail-grid">
            <div>
              <p className="detail-grid__label">Name</p>
              <p>{workflowQuery.data.name}</p>
            </div>
            <div>
              <p className="detail-grid__label">Version</p>
              <p>{workflowQuery.data.version}</p>
            </div>
            <div>
              <p className="detail-grid__label">Status</p>
              <p>{workflowQuery.data.status}</p>
            </div>
            <div>
              <p className="detail-grid__label">Schema</p>
              <p>{workflowQuery.data.definition_schema_version}</p>
            </div>
          </div>

          <div className="actions-row">
            {workflowQuery.data.status === 'draft' ? (
              <button
                className="button"
                disabled={publishWorkflow.isPending}
                onClick={handlePublishWorkflow}
                type="button"
              >
                {publishWorkflow.isPending ? 'Publishing…' : 'Publish workflow'}
              </button>
            ) : null}

            <button
              className="button button--secondary"
              disabled={createExecution.isPending || workflowQuery.data.status !== 'published'}
              onClick={handleCreateExecution}
              type="button"
            >
              {createExecution.isPending ? 'Creating execution…' : 'Create execution'}
            </button>
          </div>

          {publishWorkflow.error ? (
            <p className="banner banner--error">{getApiErrorMessage(publishWorkflow.error)}</p>
          ) : null}
          {createExecution.error ? (
            <p className="banner banner--error">{getApiErrorMessage(createExecution.error)}</p>
          ) : null}

          <div className="stack-md">
            <h3>Workflow steps</h3>
            <ol className="step-list">
              {workflowQuery.data.definition.steps.map((step) => (
                <li className="step-list__item" key={step.id}>
                  <div>
                    <strong>{step.name}</strong>
                    <p className="muted">
                      {step.type} · risk {step.risk}
                    </p>
                  </div>
                  <span className="pill">
                    {step.requiresApproval ? 'Approval required' : 'No approval'}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </>
      ) : null}
    </section>
  )
}
