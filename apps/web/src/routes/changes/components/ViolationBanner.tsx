import type { BreakglassSession, ChangeException, RetroReview } from '../../../features/changes/types'

interface ViolationBannerProps {
  overdueReviews?: RetroReview[]
  missingArtifactExceptions?: ChangeException[]
  controlFailureReviews?: RetroReview[]
  selfReviewError?: string | null
  activeBreakglass?: BreakglassSession | null
}

export function ViolationBanner({
  overdueReviews = [],
  missingArtifactExceptions = [],
  controlFailureReviews = [],
  selfReviewError,
  activeBreakglass,
}: ViolationBannerProps) {
  const hasViolations =
    overdueReviews.length > 0 ||
    missingArtifactExceptions.length > 0 ||
    controlFailureReviews.length > 0 ||
    Boolean(selfReviewError) ||
    Boolean(activeBreakglass && activeBreakglass.review_status === 'overdue')

  if (!hasViolations) return null

  return (
    <div role="alert" aria-label="Violations" className="stack-md">
      {activeBreakglass && activeBreakglass.review_status === 'overdue' && (
        <div className="banner banner--error" data-testid="violation-overdue-breakglass-review">
          <strong>Overdue breakglass review:</strong> The mandatory retro-review for the active
          breakglass session is overdue. Closure is blocked until the review is submitted.
        </div>
      )}

      {overdueReviews.length > 0 && (
        <div className="banner banner--error" data-testid="violation-overdue-retro-review">
          <strong>Overdue retro-review ({overdueReviews.length}):</strong> The following reviews
          are past their due date:
          <ul style={{ margin: '0.25rem 0 0', paddingLeft: '1.25rem' }}>
            {overdueReviews.map((r) => (
              <li key={r.id}>Review due {new Date(r.due_at).toLocaleString()}</li>
            ))}
          </ul>
        </div>
      )}

      {missingArtifactExceptions.length > 0 && (
        <div className="banner banner--warning" data-testid="violation-missing-artifact">
          <strong>Missing artifact exception active:</strong> This change has a missing-artifact
          exception. Closure requires a retro-review with explicit remediation or control-failure
          disposition.
        </div>
      )}

      {controlFailureReviews.length > 0 && (
        <div className="banner banner--error" data-testid="violation-control-failure">
          <strong>Control failure recorded:</strong> A retro-review was marked as control failure.
          An admin or owner reviewer must complete the review before closure.
        </div>
      )}

      {selfReviewError && (
        <div className="banner banner--error" data-testid="violation-self-review">
          <strong>Self-review blocked:</strong> {selfReviewError}
        </div>
      )}
    </div>
  )
}
