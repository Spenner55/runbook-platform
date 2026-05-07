import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RetroReviewPanel } from './RetroReviewPanel'
import { createJsonResponse } from '../../../test/fetchResponse'
import { renderRoute } from '../../../test/renderRoute'
import type { RetroReview } from '../../../features/changes/types'

function makeReview(overrides: Partial<RetroReview> = {}): RetroReview {
  return {
    id: 'review-1',
    change_record_id: 'change-1',
    change_record_title: 'Test change',
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

describe('RetroReviewPanel', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderPanel(reviews: RetroReview[]) {
    return renderRoute(<RetroReviewPanel changeId="change-1" reviews={reviews} />, {
      path: '/changes/:changeId',
      route: '/changes/change-1',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('shows no retro reviews message when empty', () => {
    renderPanel([])
    expect(screen.getByText(/no retro reviews required/i)).toBeInTheDocument()
  })

  it('renders a pending review with Submit Review button', () => {
    renderPanel([makeReview()])
    expect(screen.getByText(/pending/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit review/i })).toBeInTheDocument()
  })

  it('shows the submission form when Submit Review is clicked', async () => {
    renderPanel([makeReview()])
    await userEvent.click(screen.getByRole('button', { name: /submit review/i }))
    await waitFor(() => {
      expect(screen.getByLabelText(/disposition/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/summary/i)).toBeInTheDocument()
    })
  })

  it('submits retro review with correct payload', async () => {
    const submittedReview = makeReview({
      status: 'submitted',
      disposition: 'accepted',
      summary: 'All clear',
    })
    fetchMock.mockResolvedValueOnce(createJsonResponse(submittedReview))

    renderPanel([makeReview()])
    await userEvent.click(screen.getByRole('button', { name: /submit review/i }))

    await waitFor(() => screen.getByLabelText(/disposition/i))
    await userEvent.selectOptions(screen.getByLabelText(/disposition/i), 'accepted')
    await userEvent.type(screen.getByLabelText(/summary/i), 'All clear')

    await userEvent.click(screen.getAllByRole('button', { name: /submit review/i })[0])

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [, call] = [fetchMock.mock.calls[0][0], fetchMock.mock.calls[0][1]] as [
      string,
      RequestInit,
    ]
    const body = JSON.parse(call.body as string) as Record<string, unknown>
    expect(body.disposition).toBe('accepted')
    expect(body.summary).toBe('All clear')
    expect(body.retro_review_id).toBe('review-1')
  })

  it('displays self-review rejection error from API', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(
        {
          errors: [
            { code: 'self_review_rejected', detail: 'Self-review is not allowed for this review.' },
          ],
        },
        { status: 403 }
      )
    )

    renderPanel([makeReview()])
    await userEvent.click(screen.getByRole('button', { name: /submit review/i }))

    await waitFor(() => screen.getByLabelText(/disposition/i))
    await userEvent.selectOptions(screen.getByLabelText(/disposition/i), 'accepted')
    await userEvent.type(screen.getByLabelText(/summary/i), 'Test')

    await userEvent.click(screen.getAllByRole('button', { name: /submit review/i })[0])

    await waitFor(() => {
      expect(screen.getByTestId('retro-review-error')).toBeInTheDocument()
    })
  })

  it('renders submitted review without Submit button', () => {
    renderPanel([makeReview({ status: 'submitted', disposition: 'accepted', summary: 'OK' })])
    expect(screen.queryByRole('button', { name: /submit review/i })).not.toBeInTheDocument()
    expect(screen.getByText('accepted')).toBeInTheDocument()
  })

  it('shows breakglass badge when breakglass_session_id is set', () => {
    renderPanel([makeReview({ breakglass_session_id: 'bg-1' })])
    expect(screen.getByText('Breakglass')).toBeInTheDocument()
  })
})
