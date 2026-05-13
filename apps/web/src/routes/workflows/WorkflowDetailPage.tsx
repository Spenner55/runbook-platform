import { Link, useNavigate, useParams } from 'react-router-dom'

import { useCreateExecution } from '../../features/executions/hooks/useCreateExecution'
import { useCreateV2Draft } from '../../features/workflows/hooks/useCreateV2Draft'
import { usePublishWorkflow } from '../../features/workflows/hooks/usePublishWorkflow'
import { useWorkflowDetail } from '../../features/workflows/hooks/useWorkflowDetail'
import type {
  ActionInvocation,
  ArtifactDeclaration,
  DryRunSpec,
  IdempotencySpec,
  RetrySpec,
  WorkflowDefinitionV2,
  WorkflowDetail,
} from '../../features/workflows/types'
import { getApiErrorMessage } from '../../shared/api/client'

function isV2(
  detail: WorkflowDetail
): detail is WorkflowDetail & { definition: WorkflowDefinitionV2 } {
  return detail.definition_schema_version === 'workflow.schema.v2'
}

function actionSummary(action: ActionInvocation): string | null {
  const p = action.params
  if (!p) return null
  if (action.type === 'shell_command' && typeof p.command === 'string') return p.command
  if (action.type === 'http_request' && typeof p.method === 'string' && typeof p.url === 'string')
    return `${p.method} ${p.url}`
  if (action.type === 'manual_task' && typeof p.instructions === 'string') return p.instructions
  if (action.type === 'approval_gate' && typeof p.message === 'string') return p.message
  return null
}

function RetrySummary({ retry }: { retry: RetrySpec }) {
  return (
    <span>
      max {retry.maxAttempts} attempt{retry.maxAttempts !== 1 ? 's' : ''}
      {retry.backoffSeconds != null ? `, ${retry.backoffSeconds}s backoff` : ''}
    </span>
  )
}

function IdempotencySummary({ idempotency }: { idempotency: IdempotencySpec }) {
  return (
    <span>
      {idempotency.mode}
      {idempotency.mode === 'keyed' && idempotency.key ? ` (${idempotency.key})` : ''}
    </span>
  )
}

function DryRunSummary({ dryRun }: { dryRun: DryRunSpec }) {
  return <span>{dryRun.supported ? dryRun.strategy : 'unsupported'}</span>
}

function ArtifactList({ artifacts }: { artifacts: ArtifactDeclaration[] }) {
  if (artifacts.length === 0) return null
  return (
    <p className="muted" style={{ fontSize: '0.8em', marginTop: '0.2rem' }}>
      Artifacts: {artifacts.map((a) => a.key).join(', ')}
    </p>
  )
}

function ValidationStatusBadge({ status }: { status: WorkflowDetail['validation_status'] }) {
  if (status === 'not_applicable') return null
  const labels: Record<string, string> = {
    valid: 'Valid',
    invalid: 'Invalid',
    pending: 'Pending',
  }
  return (
    <span className={`pill${status === 'invalid' ? ' pill--risk-high' : ''}`}>
      {labels[status] ?? status}
    </span>
  )
}

export function WorkflowDetailPage() {
  const { workflowId } = useParams()
  const navigate = useNavigate()
  const workflowQuery = useWorkflowDetail(workflowId ?? null)
  const publishWorkflow = usePublishWorkflow(workflowId ?? null)
  const createExecution = useCreateExecution()
  const createV2DraftMutation = useCreateV2Draft(workflowId ?? null)

  async function handlePublishWorkflow() {
    await publishWorkflow.mutateAsync()
  }

  async function handleCreateExecution() {
    if (!workflowId) return
    const execution = await createExecution.mutateAsync({ workflow_id: workflowId })
    navigate(`/executions/${execution.id}`)
  }

  async function handleMigrateToV2() {
    const newWorkflow = await createV2DraftMutation.mutateAsync()
    navigate(`/workflows/${newWorkflow.id}`)
  }

  const wf = workflowQuery.data
  const v2 = wf && isV2(wf)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <Link className="muted" to={`/workflows`}>
          ← Back to Workflows
        </Link>

        <h2>Workflow detail</h2>
      </div>

      {workflowQuery.isLoading ? <p className="muted">Loading workflow…</p> : null}
      {workflowQuery.error ? (
        <p className="banner banner--error">{getApiErrorMessage(workflowQuery.error)}</p>
      ) : null}

      {wf?.requires_review ? (
        <p className="banner banner--warning">
          AI-generated workflow requires review before it can be published or executed.
        </p>
      ) : null}

      {wf?.validation_status === 'invalid' ? (
        <div className="banner banner--error">
          <p>
            <strong>Validation errors</strong>
          </p>
          {wf.validation_report?.errors?.map((err) => (
            <p key={err.code} style={{ marginTop: '0.25rem' }}>
              [{err.code}] {err.detail}
            </p>
          ))}
        </div>
      ) : null}

      {wf ? (
        <>
          <div className="detail-grid">
            <div>
              <p className="detail-grid__label">Name</p>
              <p>{wf.name}</p>
            </div>
            <div>
              <p className="detail-grid__label">Version</p>
              <p>{wf.version}</p>
            </div>
            <div>
              <p className="detail-grid__label">Status</p>
              <p>{wf.status}</p>
            </div>
            <div>
              <p className="detail-grid__label">Schema</p>
              <p>{wf.definition_schema_version}</p>
            </div>
            {v2 ? (
              <div>
                <p className="detail-grid__label">Catalog</p>
                <p>
                  {(wf.definition as WorkflowDefinitionV2).catalogVersion ??
                    wf.catalog_version ??
                    '—'}
                </p>
              </div>
            ) : null}
            {wf.validation_status !== 'not_applicable' ? (
              <div>
                <p className="detail-grid__label">Validation</p>
                <p>
                  <ValidationStatusBadge status={wf.validation_status} />
                </p>
              </div>
            ) : null}
          </div>

          {v2 && (wf.definition as WorkflowDefinitionV2).secrets?.length ? (
            <div className="stack-sm">
              <h3>Declared secrets</h3>
              <ul>
                {(wf.definition as WorkflowDefinitionV2).secrets!.map((s) => (
                  <li key={s.key}>
                    <code className="code-inline">{s.key}</code>
                    {s.displayName ? ` — ${s.displayName}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="actions-row">
            {wf.requires_review ? (
              <Link className="button" to={`/workflows/${workflowId}/review`}>
                Review now
              </Link>
            ) : null}

            {wf.status === 'draft' ? (
              <button
                className="button button--secondary"
                disabled={publishWorkflow.isPending || wf.requires_review}
                onClick={handlePublishWorkflow}
                type="button"
              >
                {publishWorkflow.isPending ? 'Publishing…' : 'Publish workflow'}
              </button>
            ) : null}

            <button
              className="button button--secondary"
              disabled={
                createExecution.isPending || wf.status !== 'published' || wf.requires_review
              }
              onClick={handleCreateExecution}
              type="button"
            >
              {createExecution.isPending ? 'Creating execution…' : 'Create execution'}
            </button>

            {wf.definition_schema_version === 'workflow.schema.v1' ? (
              <button
                className="button button--secondary"
                disabled={createV2DraftMutation.isPending}
                onClick={handleMigrateToV2}
                type="button"
              >
                {createV2DraftMutation.isPending ? 'Migrating…' : 'Migrate to v2'}
              </button>
            ) : null}
          </div>

          {publishWorkflow.error ? (
            <p className="banner banner--error">{getApiErrorMessage(publishWorkflow.error)}</p>
          ) : null}
          {createExecution.error ? (
            <p className="banner banner--error">{getApiErrorMessage(createExecution.error)}</p>
          ) : null}
          {createV2DraftMutation.error ? (
            <p className="banner banner--error">
              {getApiErrorMessage(createV2DraftMutation.error)}
            </p>
          ) : null}

          <div className="stack-md">
            <h3>Workflow steps</h3>
            <ol className="step-list">
              {v2
                ? (wf.definition as WorkflowDefinitionV2).steps.map((step) => {
                    const summary = actionSummary(step.action)
                    return (
                      <li className="step-list__item" key={step.id} id={`step-${step.id}`}>
                        <div>
                          <strong>{step.name}</strong>
                          <p className="muted">
                            {step.action.type}
                            {step.action.version ? ` · v${step.action.version}` : ''} · risk{' '}
                            {step.risk}
                          </p>
                          {summary ? (
                            <pre
                              className="code-block"
                              style={{ marginTop: '0.25rem', fontSize: '0.85em' }}
                            >
                              {summary}
                            </pre>
                          ) : null}
                          {step.secrets?.length ? (
                            <p className="muted" style={{ fontSize: '0.8em', marginTop: '0.2rem' }}>
                              Secrets: {step.secrets.join(', ')}
                            </p>
                          ) : null}
                          {step.artifacts?.length ? (
                            <ArtifactList artifacts={step.artifacts} />
                          ) : null}
                          {step.retry ? (
                            <p className="muted" style={{ fontSize: '0.8em', marginTop: '0.2rem' }}>
                              Retry: <RetrySummary retry={step.retry} />
                            </p>
                          ) : null}
                          {step.idempotency ? (
                            <p className="muted" style={{ fontSize: '0.8em', marginTop: '0.2rem' }}>
                              Idempotency: <IdempotencySummary idempotency={step.idempotency} />
                            </p>
                          ) : null}
                          {step.dryRun ? (
                            <p className="muted" style={{ fontSize: '0.8em', marginTop: '0.2rem' }}>
                              Dry-run: <DryRunSummary dryRun={step.dryRun} />
                            </p>
                          ) : null}
                        </div>
                        <span className="pill">
                          {step.requiresApproval ? 'Approval required' : 'No approval'}
                        </span>
                      </li>
                    )
                  })
                : (
                    wf.definition as {
                      steps: import('../../features/workflows/types').WorkflowStep[]
                    }
                  ).steps.map((step) => (
                    <li className="step-list__item" key={step.id} id={`step-${step.id}`}>
                      <div>
                        <strong>{step.name}</strong>
                        <p className="muted">
                          {step.type} · risk {step.risk}
                        </p>
                        {step.command ? (
                          <pre
                            className="code-block"
                            style={{ marginTop: '0.25rem', fontSize: '0.85em' }}
                          >
                            {step.command}
                          </pre>
                        ) : null}
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
