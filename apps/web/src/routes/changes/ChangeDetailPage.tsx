import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useChangeDetail } from '../../features/changes/hooks/useChangeDetail'
import { useSubmitChange } from '../../features/changes/hooks/useSubmitChange'
import type { ChangeRecord } from '../../features/changes/types'
import { getApiErrorMessage } from '../../shared/api/client'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function truncateHash(hash: string | null | undefined, len = 16) {
  if (!hash) return null
  return hash.length > len ? `${hash.slice(0, len)}…` : hash
}

function getStatusPillClass(status: string) {
  if (status === 'draft') return 'pill'
  if (status === 'pending_approval') return 'pill pill--warn'
  if (status === 'approved' || status === 'dispatchable' || status === 'scheduled')
    return 'pill pill--info'
  if (status === 'running') return 'pill pill--info'
  if (status === 'verification_pending') return 'pill pill--warn'
  if (status === 'verified') return 'pill pill--success'
  if (status === 'closed') return 'pill pill--success'
  if (status === 'rejected' || status === 'expired' || status === 'canceled')
    return 'pill pill--danger'
  return 'pill'
}

function ChangeStatusBadge({ status }: { status: string }) {
  return <span className={getStatusPillClass(status)}>{status.replace(/_/g, ' ')}</span>
}

function ChangeOverview({ change }: { change: ChangeRecord }) {
  const inputsHash = truncateHash(change.requested_inputs_sha256)
  const snapshotHash = truncateHash(change.request_snapshot_sha256)

  return (
    <section className="stack-md">
      <div>
        <h3>{change.title}</h3>
        <ChangeStatusBadge status={change.status} />
      </div>
      {change.summary ? <p>{change.summary}</p> : null}
      <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '0.25rem' }}>
        <dt className="muted">Profile</dt>
        <dd>
          {change.operation_profile.name} ({change.operation_profile.key})
        </dd>
        <dt className="muted">Workflow</dt>
        <dd>
          {change.workflow_id}
          {change.workflow_version_snapshot != null && (
            <span className="muted"> v{change.workflow_version_snapshot}</span>
          )}
        </dd>
        <dt className="muted">Justification</dt>
        <dd>{change.justification || <em className="muted">None provided</em>}</dd>

        {inputsHash && (
          <>
            <dt className="muted">Inputs hash</dt>
            <dd>
              <code title={change.requested_inputs_sha256}>{inputsHash}</code>
            </dd>
          </>
        )}
        {snapshotHash && (
          <>
            <dt className="muted">Snapshot hash</dt>
            <dd>
              <code title={change.request_snapshot_sha256}>{snapshotHash}</code>
            </dd>
          </>
        )}

        {change.scheduled_for && (
          <>
            <dt className="muted">Scheduled for</dt>
            <dd>{formatDateTime(change.scheduled_for)}</dd>
          </>
        )}
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
        {change.verification_pending_at && (
          <>
            <dt className="muted">Verification pending</dt>
            <dd>{formatDateTime(change.verification_pending_at)}</dd>
          </>
        )}
        {change.closed_at && (
          <>
            <dt className="muted">Closed</dt>
            <dd>{formatDateTime(change.closed_at)}</dd>
          </>
        )}
        {change.rejected_at && (
          <>
            <dt className="muted">Rejected</dt>
            <dd>{formatDateTime(change.rejected_at)}</dd>
          </>
        )}
        {change.expired_at && (
          <>
            <dt className="muted">Expired</dt>
            <dd>{formatDateTime(change.expired_at)}</dd>
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
            {t.display_name && <span className="muted"> ({t.display_name})</span>}
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
        <dd>
          <span className="pill">{ar.status}</span>
        </dd>
        <dt className="muted">Requested</dt>
        <dd>{formatDateTime(ar.requested_at)}</dd>
        <dt className="muted">Expires</dt>
        <dd>{formatDateTime(ar.expires_at)}</dd>
        <dt className="muted">Approvals</dt>
        <dd>
          <Link to="/approvals">View approvals inbox</Link>
        </dd>
      </dl>
    </section>
  )
}

function PolicyDecisionSection({ change }: { change: ChangeRecord }) {
  const pd = change.policy_decision
  if (!pd) return null

  const outcome = pd.outcome as string | undefined
  const effectiveOutcome = pd.effective_outcome as string | undefined
  const reason = pd.reason as string | undefined
  const decisionSource = pd.decision_source as string | undefined

  return (
    <section>
      <h4>Policy Decision</h4>
      <dl style={{ display: 'grid', gridTemplateColumns: '160px 1fr', rowGap: '0.25rem' }}>
        {outcome && (
          <>
            <dt className="muted">Outcome</dt>
            <dd>
              <span className="pill">{outcome}</span>
            </dd>
          </>
        )}
        {effectiveOutcome && effectiveOutcome !== outcome && (
          <>
            <dt className="muted">Effective outcome</dt>
            <dd>
              <span className="pill">{effectiveOutcome}</span>
            </dd>
          </>
        )}
        {decisionSource && (
          <>
            <dt className="muted">Decision source</dt>
            <dd>{decisionSource.replace(/_/g, ' ')}</dd>
          </>
        )}
        {reason && (
          <>
            <dt className="muted">Reason</dt>
            <dd>{reason}</dd>
          </>
        )}
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
        <dd>
          <Link to={`/executions/${binding.execution_id}`}>{binding.execution_id}</Link>
        </dd>
        <dt className="muted">Execution status</dt>
        <dd>
          <span className="pill">{binding.execution_status}</span>
        </dd>
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

function VerificationSection({ change }: { change: ChangeRecord }) {
  if (change.status !== 'verification_pending' && change.status !== 'verified') return null
  return (
    <section>
      <h4>Verification</h4>
      <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '0.25rem' }}>
        <dt className="muted">Status</dt>
        <dd>
          <ChangeStatusBadge status={change.status} />
        </dd>
        {change.verification_pending_at && (
          <>
            <dt className="muted">Pending since</dt>
            <dd>{formatDateTime(change.verification_pending_at)}</dd>
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
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <h2>Change Dossier</h2>
        <Link to="/changes" className="muted">
          ← All changes
        </Link>
      </div>
      <ChangeOverview change={change} />
      <SubmitChangeSection change={change} />
      <ChangeTargetsList change={change} />
      <ApprovalSection change={change} />
      <PolicyDecisionSection change={change} />
      <VerificationSection change={change} />
      <ExecutionBindingSection change={change} />
    </div>
  )
}
