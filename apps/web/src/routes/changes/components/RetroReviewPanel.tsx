import { useState } from 'react'

import { useSubmitRetroReview } from '../../../features/changes/hooks/useSubmitRetroReview'
import type { RetroReview, RetroReviewDisposition } from '../../../features/changes/types'
import { getApiErrorMessage } from '../../../shared/api/client'

const DISPOSITIONS: { value: RetroReviewDisposition; label: string; description: string }[] = [
  {
    value: 'accepted',
    label: 'Accepted',
    description: 'The emergency was justified and controls were followed appropriately.',
  },
  {
    value: 'needs_remediation',
    label: 'Needs Remediation',
    description: 'The situation was handled but a follow-up action is required.',
  },
  {
    value: 'control_failure',
    label: 'Control Failure',
    description: 'A control failure occurred. Requires admin/owner reviewer.',
  },
]

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function getStatusPillClass(status: string) {
  if (status === 'submitted') return 'pill pill--success'
  if (status === 'pending') return 'pill pill--warn'
  if (status === 'superseded') return 'pill'
  return 'pill'
}

interface RetroReviewItemProps {
  changeId: string
  review: RetroReview
}

function RetroReviewItem({ changeId, review }: RetroReviewItemProps) {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [disposition, setDisposition] = useState<RetroReviewDisposition | ''>('')
  const [summary, setSummary] = useState('')
  const [remediationRef, setRemediationRef] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const submitMutation = useSubmitRetroReview(changeId, review.id)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!disposition) return
    setErrorMsg(null)

    submitMutation.mutate(
      {
        retro_review_id: review.id,
        disposition,
        summary,
        remediation_reference: remediationRef || undefined,
      },
      {
        onSuccess: () => setIsSubmitting(false),
        onError: (err) => {
          const msg = getApiErrorMessage(err)
          if (msg.toLowerCase().includes('self') || msg.toLowerCase().includes('reviewer')) {
            setErrorMsg(`Self-review blocked: ${msg}`)
          } else {
            setErrorMsg(msg)
          }
        },
      }
    )
  }

  return (
    <div
      style={{
        border: '1px solid var(--color-border, #ccc)',
        borderRadius: '4px',
        padding: '1rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <strong>Review</strong>
        <span className={getStatusPillClass(review.status)}>{review.status}</span>
        {review.breakglass_session_id && <span className="pill pill--info">Breakglass</span>}
        {review.change_exception_id && <span className="pill">Exception</span>}
        <span className="muted" style={{ marginLeft: 'auto', fontSize: '0.85em' }}>
          Due: {formatDateTime(review.due_at)}
        </span>
      </div>

      {review.status === 'submitted' && (
        <dl
          style={{
            display: 'grid',
            gridTemplateColumns: '180px 1fr',
            rowGap: '0.25rem',
            marginTop: '0.75rem',
          }}
        >
          <dt className="muted">Disposition</dt>
          <dd>
            <span
              className={
                review.disposition === 'control_failure'
                  ? 'pill pill--danger'
                  : 'pill pill--success'
              }
            >
              {review.disposition?.replace(/_/g, ' ')}
            </span>
          </dd>
          <dt className="muted">Summary</dt>
          <dd>{review.summary}</dd>
          {review.remediation_reference && (
            <>
              <dt className="muted">Remediation ref</dt>
              <dd>{review.remediation_reference}</dd>
            </>
          )}
          <dt className="muted">Reviewed at</dt>
          <dd>{formatDateTime(review.reviewed_at)}</dd>
        </dl>
      )}

      {review.status === 'pending' && !isSubmitting && (
        <div style={{ marginTop: '0.75rem' }}>
          <button className="btn btn--primary" type="button" onClick={() => setIsSubmitting(true)}>
            Submit Review
          </button>
        </div>
      )}

      {review.status === 'pending' && isSubmitting && (
        <form className="stack-md" onSubmit={handleSubmit} style={{ marginTop: '0.75rem' }}>
          <div className="field">
            <label className="field__label" htmlFor={`disposition-${review.id}`}>
              Disposition
            </label>
            <select
              id={`disposition-${review.id}`}
              className="field__input"
              value={disposition}
              onChange={(e) => setDisposition(e.target.value as RetroReviewDisposition | '')}
              required
            >
              <option value="">Select disposition…</option>
              {DISPOSITIONS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          {disposition && (
            <p className="muted" style={{ fontSize: '0.85em' }}>
              {DISPOSITIONS.find((d) => d.value === disposition)?.description}
            </p>
          )}

          <div className="field">
            <label className="field__label" htmlFor={`summary-${review.id}`}>
              Summary
            </label>
            <textarea
              id={`summary-${review.id}`}
              className="field__input"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              rows={3}
              required
              placeholder="Describe what happened and your assessment…"
            />
          </div>

          {(disposition === 'needs_remediation' || disposition === 'control_failure') && (
            <div className="field">
              <label className="field__label" htmlFor={`remediation-ref-${review.id}`}>
                Remediation Reference (ticket or follow-up ID)
              </label>
              <input
                id={`remediation-ref-${review.id}`}
                className="field__input"
                type="text"
                value={remediationRef}
                onChange={(e) => setRemediationRef(e.target.value)}
                placeholder="e.g. INC-12345"
              />
            </div>
          )}

          {errorMsg && (
            <p className="banner banner--error" data-testid="retro-review-error">
              {errorMsg}
            </p>
          )}

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="btn btn--primary"
              type="submit"
              disabled={submitMutation.isPending || !disposition || !summary}
            >
              {submitMutation.isPending ? 'Submitting…' : 'Submit Review'}
            </button>
            <button className="btn" type="button" onClick={() => setIsSubmitting(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

interface RetroReviewPanelProps {
  changeId: string
  reviews: RetroReview[]
}

export function RetroReviewPanel({ changeId, reviews }: RetroReviewPanelProps) {
  if (reviews.length === 0) {
    return (
      <section>
        <h4>Retro Reviews</h4>
        <p className="muted">No retro reviews required for this change.</p>
      </section>
    )
  }

  return (
    <section className="stack-md">
      <h4>Retro Reviews</h4>
      <div className="stack-md">
        {reviews.map((review) => (
          <RetroReviewItem key={review.id} changeId={changeId} review={review} />
        ))}
      </div>
    </section>
  )
}
