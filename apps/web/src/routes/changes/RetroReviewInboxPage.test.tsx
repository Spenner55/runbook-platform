import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RetroReviewInboxPage } from './RetroReviewInboxPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'
import type { RetroReview } from '../../features/changes/types'

function makeReview(overrides: Partial<RetroReview> = {}): RetroReview {
  return {
    id: 'review-1',
    change_record_id: 'change-1',
    change_record_title: 'Rotate database credentials',
    breakglass_session_id: 'bg-1',
    change_exception_id: null,
    status: 'pending',
    disposition: '',
    reviewed_by_id: null,
    reviewed_at: null,
    due_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
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

function makeOverdueReview(overrides: Partial<RetroReview> = {}): RetroReview {
  return makeReview({
    id: 'review-overdue',
    due_at: new Date(Date.now() - 60 * 1000).toISOString(), // in the past
    ...overrides,
  })
}

describe('RetroReviewInboxPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderPage() {
    return renderRoute(<RetroReviewInboxPage />, {
      path: '/retro-reviews',
      route: '/retro-reviews',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('renders the inbox heading', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))
    renderPage()
    await waitFor(() => expect(screen.getByText(/retro review inbox/i)).toBeInTheDocument())
  })

  it('shows empty state when no pending reviews', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))
    renderPage()
    await waitFor(() => {
      expect(screen.getByText(/no pending retro-reviews/i)).toBeInTheDocument()
    })
  })

  it('shows pending reviews in the pending section', async () => {
    const pendingReview = makeReview()
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [pendingReview] }))
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('pending-reviews-list')).toBeInTheDocument()
    })
    expect(screen.getByTestId(`inbox-review-${pendingReview.id}`)).toBeInTheDocument()
    expect(screen.getByTestId('pending-badge')).toBeInTheDocument()
  })

  it('shows overdue reviews in the overdue section with danger badge', async () => {
    const overdueReview = makeOverdueReview()
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [overdueReview] }))
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('overdue-reviews-list')).toBeInTheDocument()
    })
    expect(screen.getByTestId(`inbox-review-${overdueReview.id}`)).toBeInTheDocument()
    expect(screen.getByTestId('overdue-badge')).toBeInTheDocument()
  })

  it('separates overdue and pending reviews into distinct sections', async () => {
    const overdue = makeOverdueReview({ id: 'overdue-1' })
    const pending = makeReview({ id: 'pending-1' })
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [overdue, pending] }))
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('overdue-reviews-list')).toBeInTheDocument()
      expect(screen.getByTestId('pending-reviews-list')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inbox-review-overdue-1')).toBeInTheDocument()
    expect(screen.getByTestId('inbox-review-pending-1')).toBeInTheDocument()
  })

  it('links to the change detail page from each review', async () => {
    const review = makeReview()
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [review] }))
    renderPage()
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /rotate database credentials/i })
      expect(link).toHaveAttribute('href', `/changes/${review.change_record_id}`)
    })
  })

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))
    renderPage()
    await waitFor(() => screen.getByText(/retro review inbox/i))
    const allCalls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allCalls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
