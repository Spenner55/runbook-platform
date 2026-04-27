import { useState } from 'react'

import { useApprovalsInbox } from '../../features/approvals/hooks/useApprovalsInbox'
import { useDecideApproval } from '../../features/approvals/hooks/useDecideApproval'
import type { ApprovalRequest } from '../../features/approvals/types'
import { getApiErrorMessage } from '../../shared/api/client'

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function getRiskClass(risk: string) {
  if (risk === 'high' || risk === 'critical') return 'pill pill--danger'
  if (risk === 'medium') return 'pill pill--warn'
  return 'pill'
}

interface DecideFormProps {
  approval: ApprovalRequest
  organizationId: string
  onDone: () => void
}

function DecideForm({ approval, organizationId, onDone }: DecideFormProps) {
  const [decision, setDecision] = useState<'approved' | 'rejected'>('approved')
  const [notes, setNotes] = useState('')
  const [actor, setActor] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const mutation = useDecideApproval(organizationId)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    mutation.mutate(
      {
        approvalId: approval.id,
        input: { decision, notes, actor_display_name: actor },
      },
      {
        onSuccess: () => onDone(),
        onError: (err) => setErrorMsg(getApiErrorMessage(err)),
      }
    )
  }

  return (
    <form className="stack-md" onSubmit={handleSubmit}>
      <div className="field">
        <label className="field__label" htmlFor="decision">Decision</label>
        <select
          id="decision"
          className="field__input"
          value={decision}
          onChange={(e) => setDecision(e.target.value as 'approved' | 'rejected')}
        >
          <option value="approved">Approve</option>
          <option value="rejected">Reject</option>
        </select>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="actor">Your name</label>
        <input
          id="actor"
          className="field__input"
          type="text"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="e.g. Jane Smith"
          required
        />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="notes">Notes (optional)</label>
        <textarea
          id="notes"
          className="field__input"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Rationale or context"
        />
      </div>
      {errorMsg ? <p className="banner banner--error">{errorMsg}</p> : null}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button type="submit" className="btn btn--primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Submitting…' : 'Submit decision'}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

interface ApprovalRowProps {
  approval: ApprovalRequest
  organizationId: string
}

function ApprovalRow({ approval, organizationId }: ApprovalRowProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <li className="step-list__item stack-md" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
        <div>
          <strong>{approval.step.name}</strong>
          <p className="muted">
            Execution{' '}
            <a href={`/executions/${approval.execution_id}`}>
              {approval.execution_id.slice(0, 8)}…
            </a>{' '}
            · step {approval.step.position} · runner {approval.requested_by_runner_id}
          </p>
          <p className="muted">
            Requested {formatDateTime(approval.requested_at)}
            {approval.expires_at
              ? ` · expires ${formatDateTime(approval.expires_at)}`
              : ''}
          </p>
        </div>
        <div className="step-list__meta">
          <span className={getRiskClass(approval.step.risk_level)}>
            risk: {approval.step.risk_level}
          </span>
          <span className="pill">{approval.status}</span>
          {approval.status === 'pending' ? (
            <button
              className="btn btn--primary"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'Cancel' : 'Decide'}
            </button>
          ) : null}
        </div>
      </div>

      {approval.decision ? (
        <p className="muted">
          {approval.decision.decision === 'approved' ? '✓ Approved' : '✗ Rejected'} by{' '}
          {approval.decision.decided_by_label} on {formatDateTime(approval.decision.decided_at)}
          {approval.decision.notes ? ` — "${approval.decision.notes}"` : ''}
        </p>
      ) : null}

      {expanded && approval.status === 'pending' ? (
        <DecideForm
          approval={approval}
          organizationId={organizationId}
          onDone={() => setExpanded(false)}
        />
      ) : null}
    </li>
  )
}

export function ApprovalsInboxPage() {
  const [orgId, setOrgId] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)

  const query = useApprovalsInbox(orgId || null, statusFilter)

  return (
    <section className="panel stack-lg">
      <div className="panel__header">
        <p className="eyebrow">Phase 10.1</p>
        <h2>Approvals Inbox</h2>
        <p className="muted">
          Review and approve or reject steps that are waiting for human authorization
          before command execution.
        </p>
      </div>

      <div className="stack-md">
        <div className="field">
          <label className="field__label" htmlFor="org-id">Organization ID</label>
          <input
            id="org-id"
            className="field__input"
            type="text"
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            placeholder="Paste an organization UUID"
          />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="status-filter">Status</label>
          <select
            id="status-filter"
            className="field__input"
            value={statusFilter ?? ''}
            onChange={(e) => setStatusFilter(e.target.value || undefined)}
          >
            <option value="">Pending (default)</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="timed_out">Timed out</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      {!orgId ? (
        <p className="muted">Enter an organization ID to load the inbox.</p>
      ) : null}

      {query.isLoading ? <p className="muted">Loading approvals…</p> : null}

      {query.error ? (
        <p className="banner banner--error">{getApiErrorMessage(query.error)}</p>
      ) : null}

      {query.data && (query.data.results?.length ?? 0) === 0 ? (
        <p className="muted">No approval requests match the current filter.</p>
      ) : null}

      {query.data && (query.data.results?.length ?? 0) > 0 ? (
        <ol className="step-list">
          {query.data.results.map((ar) => (
            <ApprovalRow key={ar.id} approval={ar} organizationId={orgId} />
          ))}
        </ol>
      ) : null}
    </section>
  )
}
