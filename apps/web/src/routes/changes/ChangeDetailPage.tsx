import { useParams } from 'react-router-dom'

import { useChangeDetail } from '../../features/changes/hooks/useChangeDetail'
import { useSubmitChange } from '../../features/changes/hooks/useSubmitChange'
import type { ChangeRecord } from '../../features/changes/types'
import { getApiErrorMessage } from '../../shared/api/client'
import { useState } from 'react'

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function getStatusPillClass(status: string) {
  if (status === 'draft') return 'pill'
  if (status === 'pending_approval') return 'pill pill--warn'
  if (status === 'approved' || status === 'dispatchable') return 'pill pill--info'
  if (status === 'running') return 'pill pill--info'
  if (status === 'closed') return 'pill pill--success'
  if (status === 'rejected' || status === 'expired' || status === 'canceled') return 'pill pill--danger'
  return 'pill'
}

function ChangeStatusBadge({ status }: { status: string }) {
  return <span className={getStatusPillClass(status)}>{status.replace(/_/g, ' ')}</span>
}

function ChangeOverview({ change }: { change: ChangeRecord }) {
  return (
    <section className="stack-md">
      <div>
        <h3>{change.title}</h3>
        <ChangeStatusBadge status={change.status} />
      </div>
      {change.summary ? <p>{change.summary}</p> : null}
      <dl style={{ display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: '0.25rem' }}>
        <dt className="muted">Profile</dt>
        <dd>{change.operation_profile.name} ({change.operation_profile.key})</dd>
        <dt className="muted">Workflow</dt>
        <dd>{change.workflow_id}</dd>
        <dt className="muted">Justification</dt>
        <dd>{change.justification || <em className="muted">None provided</em>}</dd>
        <dt className="muted">Created</dt>
        <dd>{formatDateTime(change.created_at)}</dd>
        {change.submitted_at && (
          <>
            <dt className="muted">Submitted</dt>
            <dd>{formatDateTime(change.submitted_at)}</dd>
          </>
        )}
        {change.approved_at && (
          <>
            <dt className="muted">Approved</dt>
            <dd>{formatDateTime(change.approved_at)}</dd>
          </>
        )}
        {change.running_at && (
          <>
            <dt className="muted">Started running</dt>
            <dd>{formatDateTime(change.running_at)}</dd>
          </>
        )}
        {change.closed_at && (
          <>
            <dt className="muted">Closed</dt>
            <dd>{formatDateTime(change.closed_at)}</dd>
          </>
        )}
        {change.terminal_reason && (
          <>
            <dt className="muted">Terminal reason</dt>
            <dd>{change.terminal_reason}</dd>
          </>
        )}
      </dl>
    </section>
  )
}

function ChangeTargetsList({ change }: { change: ChangeRecord }) {
  if (!change.targets.length) return null
  return (
    <section>
      <h4>Targets</h4>
      <ul className="step-list">
        {change.targets.map((t) => (
          <li key={t.id} className="step-list__item">
            <span className="pill">{t.environment}</span>{' '}
            <strong>{t.target_type}</strong>: {t.target_identifier}
          </li>
        ))}
      </ul>
    </section>
  )
}

function ApprovalSection({ change }: { change: ChangeRecord }) {
  const ar = change.approval_request
  if (!ar) return null
  return (
    <section>
      <h4>Approval Request</h4>
      <dl style={{ display: 'grid', gridTemplateColumns: '140px 1fr', rowGap: '0.25rem' }}>
        <dt className="muted">Status</dt>
        <dd><span className="pill">{ar.status}</span></dd>
        <dt className="muted">Requested</dt>
        <dd>{formatDateTime(ar.requested_at)}</dd>
        <dt className="muted">Expires</dt>
        <dd>{formatDateTime(ar.expires_at)}</dd>
      </dl>
    </section>
  )
}

function ExecutionBindingSection({ change }: { change: ChangeRecord }) {
  const binding = change.execution_binding
  if (!binding) return null
  return (
    <section>
      <h4>Execution Binding</h4>
      <dl style={{ display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: '0.25rem' }}>
        <dt className="muted">Execution</dt>
        <dd>{binding.execution_id}</dd>
        <dt className="muted">Execution status</dt>
        <dd><span className="pill">{binding.execution_status}</span></dd>
        <dt className="muted">Reserved</dt>
        <dd>{formatDateTime(binding.reserved_at)}</dd>
        {binding.bound_at && (
          <>
            <dt className="muted">Bound</dt>
            <dd>{formatDateTime(binding.bound_at)}</dd>
          </>
        )}
      </dl>
    </section>
  )
}

function SubmitChangeSection({ change }: { change: ChangeRecord }) {
  const submitMutation = useSubmitChange(change.id)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  if (change.status !== 'draft') return null

  return (
    <section>
      {errorMsg && <p className="banner banner--error">{errorMsg}</p>}
      <button
        className="btn btn--primary"
        disabled={submitMutation.isPending}
        onClick={() => {
          setErrorMsg(null)
          submitMutation.mutate(undefined, {
            onError: (err) => setErrorMsg(getApiErrorMessage(err)),
          })
        }}
      >
        {submitMutation.isPending ? 'Submitting…' : 'Submit for Approval'}
      </button>
    </section>
  )
}

export function ChangeDetailPage() {
  const { changeId } = useParams<{ changeId: string }>()
  const { data: change, isLoading, error } = useChangeDetail(changeId ?? '')

  if (!changeId) return <p>No change ID.</p>
  if (isLoading) return <p>Loading…</p>
  if (error || !change) return <p className="banner banner--error">Change not found.</p>

  return (
    <div className="stack-md">
      <h2>Change Dossier</h2>
      <ChangeOverview change={change} />
      <SubmitChangeSection change={change} />
      <ChangeTargetsList change={change} />
      <ApprovalSection change={change} />
      <ExecutionBindingSection change={change} />
    </div>
  )
}
