import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BreakglassStatusPanel } from './BreakglassStatusPanel'
import type { BreakglassSession } from '../../../features/changes/types'

const futureExpiry = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString()
const pastExpiry = new Date(Date.now() - 60 * 1000).toISOString()
const reviewDue = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()

function makeSession(overrides: Partial<BreakglassSession> = {}): BreakglassSession {
  return {
    id: 'bg-1',
    change_record_id: 'change-1',
    status: 'active',
    scope_sha256: 'abc123'.padEnd(64, '0'),
    reason: 'Production incident requires immediate action',
    activated_by_id: 'user-1',
    started_at: '2026-05-06T10:00:00Z',
    expires_at: futureExpiry,
    ended_at: null,
    end_reason: '',
    review_due_at: reviewDue,
    review_status: 'pending',
    created_at: '2026-05-06T10:00:00Z',
    updated_at: '2026-05-06T10:00:00Z',
    ...overrides,
  }
}

describe('BreakglassStatusPanel', () => {
  it('renders the session status badge', () => {
    render(<BreakglassStatusPanel session={makeSession()} />)
    expect(screen.getByTestId('breakglass-status-badge')).toHaveTextContent('active')
  })

  it('shows countdown for active session using server expires_at', () => {
    render(<BreakglassStatusPanel session={makeSession({ expires_at: futureExpiry })} />)
    // Countdown should be visible for active sessions with future expiry
    expect(screen.getByTestId('breakglass-countdown')).toBeInTheDocument()
    expect(screen.getByTestId('breakglass-countdown').textContent).toMatch(/expires in/i)
  })

  it('shows Expired in countdown when expires_at is in the past', () => {
    // expires_at is in the past but status is still active (server hasn't updated yet)
    render(<BreakglassStatusPanel session={makeSession({ expires_at: pastExpiry })} />)
    expect(screen.getByTestId('breakglass-countdown')).toHaveTextContent('Expired')
  })

  it('does not show countdown for non-active sessions', () => {
    render(<BreakglassStatusPanel session={makeSession({ status: 'expired' })} />)
    expect(screen.queryByTestId('breakglass-countdown')).not.toBeInTheDocument()
  })

  it('displays review_due_at from server timestamp', () => {
    render(<BreakglassStatusPanel session={makeSession({ review_due_at: reviewDue })} />)
    expect(screen.getByTestId('breakglass-review-due-at')).toBeInTheDocument()
    expect(screen.getByTestId('breakglass-review-due-at').textContent).not.toBe('—')
  })

  it('shows overdue review status as danger pill', () => {
    render(<BreakglassStatusPanel session={makeSession({ review_status: 'overdue' })} />)
    const badge = screen.getByTestId('breakglass-review-status')
    expect(badge).toHaveClass('pill--danger')
    expect(badge).toHaveTextContent('overdue')
  })

  it('displays expires_at from server', () => {
    render(<BreakglassStatusPanel session={makeSession()} />)
    expect(screen.getByTestId('breakglass-expires-at')).toBeInTheDocument()
    expect(screen.getByTestId('breakglass-expires-at').textContent).not.toBe('—')
  })
})
