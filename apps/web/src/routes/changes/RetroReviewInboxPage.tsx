import { Link } from 'react-router-dom'

import { useRetroReviewInbox } from '../../features/changes/hooks/useRetroReviewInbox'
import type { RetroReview } from '../../features/changes/types'
import { getApiErrorMessage } from '../../shared/api/client'

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function isOverdue(review: RetroReview): boolean {
  return review.status === 'pending' && new Date(review.due_at) < new Date()
}

function ReviewRow({ review }: { review: RetroReview }) {
  const overdue = isOverdue(review)

  return (
    <li
      className="step-list__item"
      data-testid={`inbox-review-${review.id}`}
      style={overdue ? { borderLeft: '3px solid var(--color-danger, #d00)', paddingLeft: '0.5rem' } : {}}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <span
          className={overdue ? 'pill pill--danger' : 'pill pill--warn'}
          data-testid={overdue ? 'overdue-badge' : 'pending-badge'}
        >
          {overdue ? 'overdue' : 'pending'}
        </span>
        {review.breakglass_session_id && <span className="pill pill--info">Breakglass</span>}
        {review.change_exception_id && <span className="pill">Exception</span>}
        <Link to={`/changes/${review.change_record_id}`}>
          {review.change_record_title || review.change_record_id}
        </Link>
        <span className="muted" style={{ marginLeft: 'auto', fontSize: '0.85em' }}>
          Due: {formatDateTime(review.due_at)}
        </span>
      </div>
    </li>
  )
}

export function RetroReviewInboxPage() {
  const { data: reviews, isLoading, error } = useRetroReviewInbox()

  const overdueReviews = reviews?.filter(isOverdue) ?? []
  const pendingReviews = reviews?.filter((r) => !isOverdue(r)) ?? []

  return (
    <div className="stack-md">
      <div>
        <h2>Retro Review Inbox</h2>
        <p className="muted">
          Mandatory after-the-fact reviews for emergency exceptions and breakglass sessions.
        </p>
      </div>

      {isLoading && <p>Loading…</p>}
      {error && <p className="banner banner--error">{getApiErrorMessage(error)}</p>}

      {reviews && reviews.length === 0 && (
        <p className="muted">No pending retro-reviews.</p>
      )}

      {overdueReviews.length > 0 && (
        <section>
          <h3 style={{ color: 'var(--color-danger, #d00)' }}>
            Overdue ({overdueReviews.length})
          </h3>
          <ul className="step-list" data-testid="overdue-reviews-list">
            {overdueReviews.map((review) => (
              <ReviewRow key={review.id} review={review} />
            ))}
          </ul>
        </section>
      )}

      {pendingReviews.length > 0 && (
        <section>
          <h3>Pending ({pendingReviews.length})</h3>
          <ul className="step-list" data-testid="pending-reviews-list">
            {pendingReviews.map((review) => (
              <ReviewRow key={review.id} review={review} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
