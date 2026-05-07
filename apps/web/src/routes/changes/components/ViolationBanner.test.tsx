import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ViolationBanner } from './ViolationBanner'
import type {
  BreakglassSession,
  ChangeException,
  RetroReview,
} from '../../../features/changes/types'

function makeReview(overrides: Partial<RetroReview> = {}): RetroReview {
  return {
    id: 'review-1',
    change_record_id: 'change-1',
    breakglass_session_id: null,
    change_exception_id: null,
    status: 'pending',
    disposition: '',
    reviewed_by_id: null,
    reviewed_at: null,
    due_at: new Date(Date.now() - 1000).toISOString(), // overdue
    summary: '',
    remediation_required: false,
    remediation_reference: '',
    control_failure_category: '',
    evidence_json: {},
    created_at: '2026-05-06T00:00:00Z',
    updated_at: '2026-05-06T00:00:00Z',
    ...overrides,
  }
}

function makeException(overrides: Partial<ChangeException> = {}): ChangeException {
  return {
    id: 'exc-1',
    change_record_id: 'change-1',
    exception_type: 'missing_artifact',
    status: 'approved',
    reason: 'Missing artifact',
    scope_json: {},
    requested_by_id: 'user-1',
    requested_at: '2026-05-06T00:00:00Z',
    approval_request_id: null,
    approved_by_id: 'user-2',
    approved_at: '2026-05-06T01:00:00Z',
    rejected_at: null,
    expires_at: '2026-05-07T00:00:00Z',
    resolved_at: null,
    resolution_note: '',
    created_at: '2026-05-06T00:00:00Z',
    updated_at: '2026-05-06T00:00:00Z',
    ...overrides,
  }
}

function makeBreakglass(overrides: Partial<BreakglassSession> = {}): BreakglassSession {
  return {
    id: 'bg-1',
    change_record_id: 'change-1',
    status: 'active',
    scope_sha256: 'abc'.padEnd(64, '0'),
    reason: 'Incident',
    activated_by_id: 'user-1',
    started_at: '2026-05-06T00:00:00Z',
    expires_at: '2026-05-06T02:00:00Z',
    ended_at: null,
    end_reason: '',
    review_due_at: '2026-05-07T00:00:00Z',
    review_status: 'pending',
    created_at: '2026-05-06T00:00:00Z',
    updated_at: '2026-05-06T00:00:00Z',
    ...overrides,
  }
}

describe('ViolationBanner', () => {
  it('renders nothing when no violations', () => {
    const { container } = render(<ViolationBanner />)
    expect(container.firstChild).toBeNull()
  })

  it('renders overdue breakglass review banner', () => {
    render(<ViolationBanner activeBreakglass={makeBreakglass({ review_status: 'overdue' })} />)
    expect(screen.getByTestId('violation-overdue-breakglass-review')).toBeInTheDocument()
    expect(screen.getByText(/overdue breakglass review/i)).toBeInTheDocument()
  })

  it('renders overdue retro-review banner', () => {
    render(<ViolationBanner overdueReviews={[makeReview()]} />)
    expect(screen.getByTestId('violation-overdue-retro-review')).toBeInTheDocument()
    expect(screen.getByText(/overdue retro-review/i)).toBeInTheDocument()
  })

  it('renders missing artifact exception banner', () => {
    render(<ViolationBanner missingArtifactExceptions={[makeException()]} />)
    expect(screen.getByTestId('violation-missing-artifact')).toBeInTheDocument()
    expect(screen.getByText(/missing artifact exception/i)).toBeInTheDocument()
  })

  it('renders control failure violation banner', () => {
    render(
      <ViolationBanner
        controlFailureReviews={[
          makeReview({ disposition: 'control_failure', status: 'submitted' }),
        ]}
      />
    )
    expect(screen.getByTestId('violation-control-failure')).toBeInTheDocument()
    expect(screen.getAllByText(/control failure/i).length).toBeGreaterThan(0)
  })

  it('renders self-review error banner', () => {
    render(<ViolationBanner selfReviewError="Self-review is not allowed." />)
    expect(screen.getByTestId('violation-self-review')).toBeInTheDocument()
    expect(screen.getByText(/self-review blocked/i)).toBeInTheDocument()
  })

  it('has role=alert on the container', () => {
    render(<ViolationBanner overdueReviews={[makeReview()]} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('does not render when breakglass review is not overdue', () => {
    const { container } = render(
      <ViolationBanner activeBreakglass={makeBreakglass({ review_status: 'pending' })} />
    )
    expect(container.firstChild).toBeNull()
  })
})
