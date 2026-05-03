import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChangesPage } from './ChangesPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const mockChanges = [
  {
    id: 'change-1',
    status: 'draft',
    title: 'Rotate credentials',
    summary: '',
    justification: 'Needed',
    operation_profile: { id: 'p-1', key: 'prod-db', name: 'Prod DB' },
    workflow_id: 'wf-1',
    workflow_version_snapshot: null,
    requested_inputs_sha256: '',
    request_snapshot_sha256: '',
    operation_profile_key_snapshot: '',
    scheduled_for: null,
    submitted_at: null,
    approved_at: null,
    dispatchable_at: null,
    running_at: null,
    verification_pending_at: null,
    closed_at: null,
    rejected_at: null,
    canceled_at: null,
    expired_at: null,
    terminal_reason: '',
    targets: [],
    approval_request: null,
    policy_decision: null,
    execution_binding: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
  },
  {
    id: 'change-2',
    status: 'pending_approval',
    title: 'Scale down replicas',
    summary: '',
    justification: 'Maintenance window',
    operation_profile: { id: 'p-1', key: 'prod-db', name: 'Prod DB' },
    workflow_id: 'wf-2',
    workflow_version_snapshot: 1,
    requested_inputs_sha256: 'abc',
    request_snapshot_sha256: 'def',
    operation_profile_key_snapshot: 'prod-db',
    scheduled_for: null,
    submitted_at: '2026-05-01T01:00:00Z',
    approved_at: null,
    dispatchable_at: null,
    running_at: null,
    verification_pending_at: null,
    closed_at: null,
    rejected_at: null,
    canceled_at: null,
    expired_at: null,
    terminal_reason: '',
    targets: [],
    approval_request: { id: 'ar-1', status: 'pending', requested_at: null, expires_at: null },
    policy_decision: null,
    execution_binding: null,
    created_at: '2026-05-01T01:00:00Z',
    updated_at: '2026-05-01T01:00:00Z',
  },
]

describe('ChangesPage', () => {
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
    return renderRoute(<ChangesPage />, {
      path: '/changes',
      route: '/changes',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('renders the page heading and New Change Request link', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))
    renderPage()

    await waitFor(() => screen.getByText('Changes'))
    expect(screen.getByRole('link', { name: /new change request/i })).toBeInTheDocument()
  })

  it('renders a list of changes', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: mockChanges }))
    renderPage()

    await waitFor(() => screen.getByText('Rotate credentials'))
    expect(screen.getByText('Scale down replicas')).toBeInTheDocument()
  })

  it('renders status badges for each change', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: mockChanges }))
    renderPage()

    await waitFor(() => screen.getByText('draft'))
    expect(screen.getByText('pending approval')).toBeInTheDocument()
  })

  it('renders links to change detail pages', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: mockChanges }))
    renderPage()

    await waitFor(() => screen.getByText('Rotate credentials'))
    const link = screen.getByRole('link', { name: /rotate credentials/i })
    expect(link).toHaveAttribute('href', '/changes/change-1')
  })

  it('shows empty state when no changes exist', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))
    renderPage()

    await waitFor(() => screen.getByText(/no changes yet/i))
  })

  it('shows loading state while fetching', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getByText(/loading changes/i)).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({ errors: [{ code: 'error', detail: 'Server error' }] }, { status: 500 }),
    )
    renderPage()

    await waitFor(() => screen.getByText(/failed to load changes/i))
  })

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))
    renderPage()

    await waitFor(() => screen.getByText('Changes'))
    const allUrls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allUrls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
