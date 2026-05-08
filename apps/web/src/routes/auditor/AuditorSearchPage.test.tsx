import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuditorSearchPage } from './AuditorSearchPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const emptySearch = {
  count: 0,
  next: null,
  previous: null,
  meta: { date_basis: 'submitted_at_with_created_at_fallback' },
  results: [],
}

const searchResult = {
  count: 1,
  next: null,
  previous: null,
  meta: { date_basis: 'submitted_at_with_created_at_fallback' },
  results: [
    {
      id: 'change-1',
      title: 'Rotate production credentials',
      status: 'closed',
      risk: 'high',
      change_type: 'standard',
      targets: [
        { id: 'target-1', label: 'payments-prod', type: 'service', identifier: 'payments-prod' },
      ],
      submitted_at: '2026-05-02T10:00:00Z',
      audit_date: '2026-05-02T10:00:00Z',
      audit_date_basis: 'submitted_at',
      approved_at: '2026-05-02T10:05:00Z',
      closed_at: '2026-05-02T11:00:00Z',
      has_exception: false,
      bundle: {
        id: 'bundle-1',
        status: 'sealed',
        completeness_status: 'complete',
        version: 1,
        manifest_sha256: 'a',
        content_sha256: 'b',
      },
      external_references: [],
      coverage_summary: {},
    },
  ],
}

describe('AuditorSearchPage', () => {
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
    return renderRoute(<AuditorSearchPage />, {
      path: '/audit/changes',
      route: '/audit/changes',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('renders the auditor search route', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(emptySearch))
    renderPage()

    await waitFor(() => screen.getByText('Audit Changes'))
    expect(screen.getByText(/read-only search/i)).toBeInTheDocument()
  })

  it('maps search filters to API query params including approver executor and dates', async () => {
    const user = userEvent.setup()
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(emptySearch))
      .mockResolvedValueOnce(createJsonResponse(searchResult))
    renderPage()

    await screen.findByText('Audit Changes')
    await user.type(screen.getByLabelText('Service'), 'payments-api')
    await user.type(screen.getByLabelText('Approver'), 'alice@example.com')
    await user.type(screen.getByLabelText('Executor'), 'runner-prod-7')
    await user.type(screen.getByLabelText('Start date'), '2026-05-02T00:00')
    await user.type(screen.getByLabelText('End date'), '2026-05-03T00:00')
    await user.click(screen.getByRole('button', { name: /apply filters/i }))

    await screen.findByText('Rotate production credentials')
    const url = new URL(String(fetchMock.mock.calls[1]?.[0]))
    expect(url.pathname).toContain('/api/v1/audit/changes/')
    expect(url.searchParams.get('service')).toBe('payments-api')
    expect(url.searchParams.get('approver')).toBe('alice@example.com')
    expect(url.searchParams.get('executor')).toBe('runner-prod-7')
    expect(url.searchParams.get('start_date')).toBe('2026-05-02T00:00')
    expect(url.searchParams.get('end_date')).toBe('2026-05-03T00:00')
  })

  it('does not call internal endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(emptySearch))
    renderPage()

    await screen.findByText('Audit Changes')
    const allUrls = fetchMock.mock.calls.map((call) => String(call[0]))
    expect(allUrls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
