import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useChangeDetail } from '../../features/changes/hooks/useChangeDetail'
import { useCloseChange } from '../../features/changes/hooks/useCloseChange'
import { useDispatchChange } from '../../features/changes/hooks/useDispatchChange'
import { useLatestPreflight } from '../../features/changes/hooks/useLatestPreflight'
import { usePatchWindow } from '../../features/changes/hooks/usePatchWindow'
import { useRunPreflight } from '../../features/changes/hooks/useRunPreflight'
import { useSubmitChange } from '../../features/changes/hooks/useSubmitChange'
import { useSubmitVerificationResult } from '../../features/changes/hooks/useSubmitVerificationResult'
import { useVerificationPlan } from '../../features/changes/hooks/useVerificationPlan'
import type {
  ChangeRecord,
  ClosureOutcome,
  DispatchEligibilityCheck,
  UnmetCheckSummary,
  VerificationCheck,
  VerificationPlan,
} from '../../features/changes/types'
import { getApiErrorMessage } from '../../shared/api/client'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function truncateHash(hash: string | null | undefined, len = 16) {
  if (!hash) return null
  return hash.length > len ? `${hash.slice(0, len)}…` : hash
}

function toDatetimeLocal(isoString: string): string {
  return isoString.slice(0, 16)
}

function getStatusPillClass(status: string) {
  if (status === 'draft') return 'pill'
  if (status === 'pending_approval') return 'pill pill--warn'
  if (status === 'approved' || status === 'dispatchable' || status === 'scheduled')
    return 'pill pill--info'
  if (status === 'running') return 'pill pill--info'
  if (status === 'verification_pending') return 'pill pill--warn'
  if (status === 'verification_failed') return 'pill pill--danger'
  if (status === 'verified') return 'pill pill--success'
  if (status === 'closed') return 'pill pill--success'
  if (status === 'rejected' || status === 'expired' || status === 'canceled')
    return 'pill pill--danger'
  return 'pill'
}

function getPlanStatusPillClass(status: string) {
  if (status === 'satisfied') return 'pill pill--success'
  if (status === 'failed') return 'pill pill--danger'
  if (status === 'active' || status === 'generated') return 'pill pill--info'
  if (status === 'canceled') return 'pill pill--danger'
  return 'pill'
}

function getCheckStatusPillClass(status: string) {
  if (status === 'passed') return 'pill pill--success'
  if (status === 'failed') return 'pill pill--danger'
  if (status === 'pending') return 'pill pill--warn'
  if (status === 'not_applicable') return 'pill'
  return 'pill'
}

function getWindowStatusPillClass(status: string) {
  if (status === 'open') return 'pill pill--success'
  if (status === 'scheduled') return 'pill pill--info'
  if (status === 'overrun') return 'pill pill--warn'
  if (status === 'expired' || status === 'closed') return 'pill pill--danger'
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
            <span className="pill">{t.environment}</span> <strong>{t.target_type}</strong>:{' '}
            {t.target_identifier}
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

function UnmetChecksBlockingDisplay({ checks }: { checks: UnmetCheckSummary[] }) {
  if (!checks.length) return null
  return (
    <div className="banner banner--warning">
      <strong>Unmet required checks ({checks.length}):</strong>
      <ul style={{ margin: '0.25rem 0 0', paddingLeft: '1.25rem' }}>
        {checks.map((c) => (
          <li key={c.id}>
            {c.name} <span className="pill">{c.check_type.replace(/_/g, ' ')}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

interface ManualAttestationModalProps {
  changeId: string
  check: VerificationCheck
  onClose: () => void
}

function ManualAttestationModal({ changeId, check, onClose }: ManualAttestationModalProps) {
  const submitMutation = useSubmitVerificationResult(changeId)
  const [attestationText, setAttestationText] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    submitMutation.mutate(
      {
        check_id: check.id,
        outcome: 'passed',
        manual_attestation_text: attestationText,
        verification_key: check.verification_key || undefined,
      },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Attest: ${check.name}`}
      style={{
        border: '1px solid var(--color-border, #ccc)',
        borderRadius: '4px',
        padding: '1rem',
        background: 'var(--color-surface, #fff)',
        marginTop: '0.75rem',
      }}
    >
      <h5 style={{ margin: '0 0 0.75rem' }}>Attest: {check.name}</h5>
      {check.description && <p className="muted">{check.description}</p>}
      <form className="stack-md" onSubmit={handleSubmit}>
        <div className="field">
          <label className="field__label" htmlFor="attestation-text">
            Attestation statement
          </label>
          <textarea
            id="attestation-text"
            className="field__input"
            value={attestationText}
            onChange={(e) => setAttestationText(e.target.value)}
            rows={4}
            required
            placeholder="Describe what you verified…"
          />
        </div>
        {errorMsg && <p className="banner banner--error">{errorMsg}</p>}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn btn--primary" type="submit" disabled={submitMutation.isPending}>
            {submitMutation.isPending ? 'Submitting…' : 'Submit attestation'}
          </button>
          <button className="btn" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

interface VerificationCheckItemProps {
  check: VerificationCheck
  onAttest?: () => void
}

function VerificationCheckItem({ check, onAttest }: VerificationCheckItemProps) {
  const canAttest =
    Boolean(onAttest) &&
    check.check_type === 'manual_attestation' &&
    (check.status === 'pending' || check.status === 'failed')

  return (
    <li className="step-list__item">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <span className={getCheckStatusPillClass(check.status)}>{check.status}</span>
        <span className="pill">{check.check_type.replace(/_/g, ' ')}</span>
        {!check.required && <span className="pill pill--info">optional</span>}
        <strong>{check.name}</strong>
        {canAttest && (
          <button className="btn" style={{ marginLeft: 'auto' }} type="button" onClick={onAttest}>
            Attest
          </button>
        )}
      </div>
      {check.last_result && (
        <div className="muted" style={{ fontSize: '0.85em', marginTop: '0.25rem' }}>
          Last result:{' '}
          <span
            className={
              check.last_result.outcome === 'passed' ? 'pill pill--success' : 'pill pill--danger'
            }
          >
            {check.last_result.outcome}
          </span>{' '}
          by {check.last_result.source} at {formatDateTime(check.last_result.validated_at)}
        </div>
      )}
    </li>
  )
}

interface VerificationChecklistPanelProps {
  change: ChangeRecord
  plan: VerificationPlan
}

function VerificationChecklistPanel({ change, plan }: VerificationChecklistPanelProps) {
  const [attestingCheck, setAttestingCheck] = useState<VerificationCheck | null>(null)
  const canAttest = change.status === 'verification_pending'

  return (
    <div className="stack-md">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <span className="pill">{plan.mode}</span>
        <span className={getPlanStatusPillClass(plan.status)}>
          {plan.status.replace(/_/g, ' ')}
        </span>
        <span className="muted">
          {plan.satisfied_required_count}/{plan.required_check_count} required passed
        </span>
        {plan.failed_required_count > 0 && (
          <span className="muted">{plan.failed_required_count} failed</span>
        )}
      </div>

      {plan.unmet_required_checks.length > 0 && (
        <UnmetChecksBlockingDisplay checks={plan.unmet_required_checks} />
      )}

      {plan.checks.length > 0 && (
        <ul className="step-list">
          {plan.checks.map((check) => (
            <VerificationCheckItem
              key={check.id}
              check={check}
              onAttest={canAttest ? () => setAttestingCheck(check) : undefined}
            />
          ))}
        </ul>
      )}

      {attestingCheck && (
        <ManualAttestationModal
          changeId={change.id}
          check={attestingCheck}
          onClose={() => setAttestingCheck(null)}
        />
      )}
    </div>
  )
}

const VERIFICATION_VISIBLE_STATUSES = new Set([
  'verification_pending',
  'verification_failed',
  'verified',
  'closed',
])

function VerificationSection({ change }: { change: ChangeRecord }) {
  const planQuery = useVerificationPlan(change.id, VERIFICATION_VISIBLE_STATUSES.has(change.status))

  if (!VERIFICATION_VISIBLE_STATUSES.has(change.status)) return null

  return (
    <section className="stack-md">
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

      {planQuery.isLoading && <p className="muted">Loading verification plan…</p>}
      {planQuery.error && <p className="banner banner--error">Could not load verification plan.</p>}
      {planQuery.data && <VerificationChecklistPanel change={change} plan={planQuery.data} />}
    </section>
  )
}

const CLOSURE_VISIBLE_STATUSES = new Set(['verified', 'verification_failed'])

const CLOSURE_OUTCOMES_BY_STATUS: Record<string, ClosureOutcome[]> = {
  verified: ['success', 'partial_success', 'rolled_back'],
  verification_failed: ['failed', 'rolled_back'],
}

interface ClosureDialogProps {
  change: ChangeRecord
  onClose: () => void
}

function ClosureDialog({ change, onClose }: ClosureDialogProps) {
  const closeMutation = useCloseChange(change.id)
  const [outcome, setOutcome] = useState<ClosureOutcome | ''>('')
  const [summary, setSummary] = useState('')
  const [reviewerId, setReviewerId] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const outcomeOptions = CLOSURE_OUTCOMES_BY_STATUS[change.status] ?? []

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!outcome) return
    setErrorMsg(null)
    closeMutation.mutate(
      {
        outcome,
        summary,
        independent_reviewer_id: reviewerId || undefined,
      },
      {
        onSuccess: onClose,
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Close change"
      style={{
        border: '1px solid var(--color-border, #ccc)',
        borderRadius: '4px',
        padding: '1rem',
        background: 'var(--color-surface, #fff)',
        marginTop: '0.75rem',
      }}
    >
      <h5 style={{ margin: '0 0 0.75rem' }}>Close Change</h5>
      <form className="stack-md" onSubmit={handleSubmit}>
        <div className="field">
          <label className="field__label" htmlFor="closure-outcome">
            Outcome
          </label>
          <select
            id="closure-outcome"
            className="field__input"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as ClosureOutcome | '')}
            required
          >
            <option value="">Select outcome…</option>
            {outcomeOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="closure-summary">
            Summary
          </label>
          <textarea
            id="closure-summary"
            className="field__input"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={3}
            required
            placeholder="Describe the outcome of this change…"
          />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="reviewer-id">
            Independent reviewer ID (if required)
          </label>
          <input
            id="reviewer-id"
            className="field__input"
            type="text"
            value={reviewerId}
            onChange={(e) => setReviewerId(e.target.value)}
            placeholder="User ID of independent reviewer"
          />
        </div>
        {errorMsg && <p className="banner banner--error">{errorMsg}</p>}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn btn--primary"
            type="submit"
            disabled={closeMutation.isPending || !outcome || !summary}
          >
            {closeMutation.isPending ? 'Closing…' : 'Confirm closure'}
          </button>
          <button className="btn" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

function ClosurePanel({ change }: { change: ChangeRecord }) {
  const [isOpen, setIsOpen] = useState(false)

  if (!CLOSURE_VISIBLE_STATUSES.has(change.status)) return null

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <h4 style={{ margin: 0 }}>Close Change</h4>
        {!isOpen && (
          <button className="btn btn--primary" onClick={() => setIsOpen(true)}>
            Close Change
          </button>
        )}
      </div>
      {isOpen && <ClosureDialog change={change} onClose={() => setIsOpen(false)} />}
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

const WINDOW_EDITABLE_STATUSES = new Set(['draft', 'pending_approval', 'approved', 'scheduled'])
const WINDOW_INVALIDATION_STATUSES = new Set(['approved', 'scheduled'])

interface WindowFormProps {
  changeId: string
  changeStatus: string
  initialStartsAt: string
  initialEndsAt: string
  initialTz: string
  initialReason: string
  onCancel: () => void
}

function WindowEditForm({
  changeId,
  changeStatus,
  initialStartsAt,
  initialEndsAt,
  initialTz,
  initialReason,
  onCancel,
}: WindowFormProps) {
  const patchMutation = usePatchWindow(changeId)
  const [startsAt, setStartsAt] = useState(initialStartsAt)
  const [endsAt, setEndsAt] = useState(initialEndsAt)
  const [tz, setTz] = useState(initialTz)
  const [reason, setReason] = useState(initialReason)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    patchMutation.mutate(
      {
        starts_at: new Date(startsAt).toISOString(),
        ends_at: new Date(endsAt).toISOString(),
        timezone: tz || undefined,
        reason: reason || undefined,
      },
      {
        onSuccess: onCancel,
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <form className="stack-md" onSubmit={handleSave}>
      {WINDOW_INVALIDATION_STATUSES.has(changeStatus) && (
        <p className="banner banner--warning">
          Updating the window for an approved change may invalidate the existing approval.
        </p>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
        <div className="field">
          <label className="field__label" htmlFor="window-starts-at">
            Starts at
          </label>
          <input
            id="window-starts-at"
            className="field__input"
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="window-ends-at">
            Ends at
          </label>
          <input
            id="window-ends-at"
            className="field__input"
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            required
          />
        </div>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="window-timezone">
          Timezone (optional)
        </label>
        <input
          id="window-timezone"
          className="field__input"
          type="text"
          value={tz}
          onChange={(e) => setTz(e.target.value)}
          placeholder="e.g. America/New_York"
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="window-reason">
          Reason (optional)
        </label>
        <textarea
          id="window-reason"
          className="field__input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          placeholder="Why this window was chosen"
        />
      </div>
      {errorMsg && <p className="banner banner--error">{errorMsg}</p>}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="btn btn--primary" type="submit" disabled={patchMutation.isPending}>
          {patchMutation.isPending ? 'Saving…' : 'Save window'}
        </button>
        <button className="btn" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function WindowPanel({ change }: { change: ChangeRecord }) {
  const isEditable = WINDOW_EDITABLE_STATUSES.has(change.status)
  const win = change.window
  const [isEditing, setIsEditing] = useState(false)

  if (!isEditable && !win) return null

  return (
    <section className="stack-md">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <h4 style={{ margin: 0 }}>Execution Window</h4>
        {win && <span className={getWindowStatusPillClass(win.status)}>{win.status}</span>}
        {isEditable && !isEditing && (
          <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => setIsEditing(true)}>
            {win ? 'Edit window' : 'Set window'}
          </button>
        )}
      </div>

      {win && !isEditing && (
        <dl style={{ display: 'grid', gridTemplateColumns: '140px 1fr', rowGap: '0.25rem' }}>
          <dt className="muted">Starts</dt>
          <dd>{formatDateTime(win.starts_at)}</dd>
          <dt className="muted">Ends</dt>
          <dd>{formatDateTime(win.ends_at)}</dd>
          {win.timezone && (
            <>
              <dt className="muted">Timezone</dt>
              <dd>{win.timezone}</dd>
            </>
          )}
          {win.reason && (
            <>
              <dt className="muted">Reason</dt>
              <dd>{win.reason}</dd>
            </>
          )}
          {win.opened_at && (
            <>
              <dt className="muted">Opened</dt>
              <dd>{formatDateTime(win.opened_at)}</dd>
            </>
          )}
        </dl>
      )}

      {isEditing && (
        <WindowEditForm
          key={win?.updated_at ?? 'new'}
          changeId={change.id}
          changeStatus={change.status}
          initialStartsAt={win ? toDatetimeLocal(win.starts_at) : ''}
          initialEndsAt={win ? toDatetimeLocal(win.ends_at) : ''}
          initialTz={win?.timezone ?? ''}
          initialReason={win?.reason ?? ''}
          onCancel={() => setIsEditing(false)}
        />
      )}
    </section>
  )
}

const CHECK_LABELS: Record<string, string> = {
  approved_status: 'Approved status',
  approved_status_ok: 'Approved status',
  policy_pass: 'Policy pass',
  policy_pass_ok: 'Policy pass',
  window_open: 'Window open',
  window_open_ok: 'Window open',
  freeze_conflicts: 'No freeze conflicts',
  freeze_conflicts_ok: 'No freeze conflicts',
  target_locks: 'No target locks',
  target_locks_ok: 'No target locks',
  actor_authorized: 'Actor authorized',
  actor_authorized_ok: 'Actor authorized',
}

function preflightCheckRows(check: DispatchEligibilityCheck) {
  return [
    { name: 'approved_status_ok', ok: check.approved_status_ok },
    { name: 'policy_pass_ok', ok: check.policy_pass_ok },
    { name: 'window_open_ok', ok: check.window_open_ok },
    { name: 'freeze_conflicts_ok', ok: check.freeze_conflicts_ok },
    { name: 'target_locks_ok', ok: check.target_locks_ok },
    { name: 'actor_authorized_ok', ok: check.actor_authorized_ok },
  ]
}

function ConflictDrawer({ check }: { check: DispatchEligibilityCheck }) {
  const [open, setOpen] = useState(true)
  if (!check.conflicts.length) return null

  return (
    <div>
      <button
        className="btn"
        type="button"
        style={{ marginBottom: '0.5rem' }}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? 'Hide' : 'Show'} {check.conflicts.length} conflict
        {check.conflicts.length !== 1 ? 's' : ''}
      </button>
      {open && (
        <ul className="step-list">
          {check.conflicts.map((c, i) => (
            <li key={i} className="step-list__item">
              <span className="pill pill--danger">{c.type.replace(/_/g, ' ')}</span>{' '}
              <strong>{c.target_type}</strong>: {c.target_identifier}
              {c.reason && <span className="muted"> — {c.reason}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const PREFLIGHT_VISIBLE_STATUSES = new Set(['approved', 'scheduled', 'dispatchable'])
const DISPATCH_FROM_STATUSES = new Set(['approved', 'scheduled'])

function PreflightCard({ change }: { change: ChangeRecord }) {
  const preflightQuery = useLatestPreflight(
    change.id,
    PREFLIGHT_VISIBLE_STATUSES.has(change.status)
  )
  const runPreflightMutation = useRunPreflight(change.id)
  const dispatchMutation = useDispatchChange(change.id)
  const [dispatchError, setDispatchError] = useState<string | null>(null)

  if (!PREFLIGHT_VISIBLE_STATUSES.has(change.status)) return null

  const check = preflightQuery.data ?? null
  const isPassed = check?.result === 'passed'
  const isFresh = check ? !check.is_stale : false
  const canDispatch =
    DISPATCH_FROM_STATUSES.has(change.status) && isPassed && isFresh && !dispatchMutation.isPending

  return (
    <section className="stack-md">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <h4 style={{ margin: 0 }}>Dispatch Preflight</h4>
        {check && (
          <span className={isPassed ? 'pill pill--success' : 'pill pill--danger'}>
            {isPassed ? 'eligible' : 'ineligible'}
          </span>
        )}
        {check && check.is_stale && <span className="pill pill--warn">stale</span>}
      </div>

      {preflightQuery.isLoading && <p className="muted">Loading preflight…</p>}
      {preflightQuery.error && (
        <p className="banner banner--error">{getApiErrorMessage(preflightQuery.error)}</p>
      )}

      {check && (
        <>
          <dl style={{ display: 'grid', gridTemplateColumns: '200px 1fr', rowGap: '0.25rem' }}>
            <dt className="muted">Checked at</dt>
            <dd>{formatDateTime(check.checked_at)}</dd>
            <dt className="muted">Expires at</dt>
            <dd>{formatDateTime(check.expires_at)}</dd>
          </dl>

          <ul className="step-list">
            {preflightCheckRows(check).map(({ name, ok }) => (
              <li key={name} className="step-list__item">
                <span className={ok ? 'pill pill--success' : 'pill pill--danger'}>
                  {ok ? '✓' : '✗'}
                </span>{' '}
                {CHECK_LABELS[name] ?? name.replace(/_/g, ' ')}
              </li>
            ))}
          </ul>

          <ConflictDrawer check={check} />
        </>
      )}

      {!check && !preflightQuery.isLoading && (
        <p className="muted">No preflight result yet. Run preflight before dispatching.</p>
      )}

      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <button
          className="btn"
          disabled={runPreflightMutation.isPending}
          onClick={() => runPreflightMutation.mutate()}
        >
          {runPreflightMutation.isPending
            ? 'Running…'
            : check
              ? 'Rerun preflight'
              : 'Run preflight'}
        </button>

        {DISPATCH_FROM_STATUSES.has(change.status) && (
          <button
            className="btn btn--primary"
            disabled={!canDispatch}
            title={
              !check
                ? 'Run preflight first'
                : !isPassed
                  ? 'Preflight must pass before dispatch'
                  : check.is_stale
                    ? 'Preflight result is stale — rerun first'
                    : dispatchMutation.isPending
                      ? 'Dispatch in progress…'
                      : 'Dispatch change for execution'
            }
            onClick={() => {
              setDispatchError(null)
              dispatchMutation.mutate(undefined, {
                onError: (err) => setDispatchError(getApiErrorMessage(err)),
              })
            }}
          >
            {dispatchMutation.isPending ? 'Dispatching…' : 'Dispatch'}
          </button>
        )}
      </div>

      {dispatchError && <p className="banner banner--error">{dispatchError}</p>}
      {runPreflightMutation.isError && (
        <p className="banner banner--error">{getApiErrorMessage(runPreflightMutation.error)}</p>
      )}
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
      <WindowPanel change={change} />
      <PreflightCard change={change} />
      <VerificationSection change={change} />
      <ClosurePanel change={change} />
      <ExecutionBindingSection change={change} />
    </div>
  )
}
