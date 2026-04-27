import { screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApprovalsInboxPage } from './ApprovalsInboxPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const pendingApproval = {
  id: 'approval-1',
  organization_id: 'org-1',
  execution_id: 'exec-1',
  execution_status: 'claimed',
  status: 'pending',
  requested_by_runner_id: 'runner-dev',
  requested_at: '2026-04-27T10:00:00Z',
  timeout_seconds: 1800,
  expires_at: '2026-04-27T10:30:00Z',
  resolved_at: null,
  step: {
    id: 'step-1',
    position: 1,
    step_key: 'deploy',
    name: 'Deploy production service',
    step_type: 'shell',
    risk_level: 'high',
    status: 'waiting_for_approval',
    requires_approval: true,
  },
  decision: null,
}

const approvedApproval = {
  ...pendingApproval,
  status: 'approved',
  resolved_at: '2026-04-27T10:05:00Z',
  decision: {
    id: 'decision-1',
    decision: 'approved',
    source_type: 'human',
    decided_by_label: 'Test Operator',
    decided_at: '2026-04-27T10:05:00Z',
    notes: 'LGTM',
  },
}

describe('ApprovalsInboxPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows prompt when no org id is entered', () => {
    renderRoute(<ApprovalsInboxPage />, {
      path: '/approvals',
      route: '/approvals',
    })

    expect(screen.getByText(/Enter an organization ID/i)).toBeInTheDocument()
  })

  it('fetches and renders pending approval request', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({ results: [pendingApproval] })
    )

    renderRoute(<ApprovalsInboxPage />, {
      path: '/approvals',
      route: '/approvals',
    })

    const orgInput = screen.getByLabelText(/Organization ID/i)
    await userEvent.type(orgInput, 'org-1')

    await waitFor(() => {
      expect(screen.getByText('Deploy production service')).toBeInTheDocument()
    })

    expect(screen.getByText(/risk: high/i)).toBeInTheDocument()
    expect(screen.getByText('pending')).toBeInTheDocument()
  })

  it('renders approve/reject button for pending approvals', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({ results: [pendingApproval] })
    )

    renderRoute(<ApprovalsInboxPage />, {
      path: '/approvals',
      route: '/approvals',
    })

    const orgInput = screen.getByLabelText(/Organization ID/i)
    await userEvent.type(orgInput, 'org-1')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Decide/i })).toBeInTheDocument()
    })
  })

  it('submits an approval decision successfully', async () => {
    fetchMock.mockImplementation((url, init) => {
      if (init && (init as RequestInit).method === 'POST') {
        return Promise.resolve(createJsonResponse(approvedApproval))
      }
      return Promise.resolve(createJsonResponse({ results: [pendingApproval] }))
    })

    renderRoute(<ApprovalsInboxPage />, {
      path: '/approvals',
      route: '/approvals',
    })

    const orgInput = screen.getByLabelText(/Organization ID/i)
    await userEvent.type(orgInput, 'org-1')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Decide/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Decide/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/Your name/i)).toBeInTheDocument()
    })

    await userEvent.type(screen.getByLabelText(/Your name/i), 'Test Operator')
    await userEvent.click(screen.getByRole('button', { name: /Submit decision/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/decide/'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })

  it('renders error banner on API failure', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse({ detail: 'Server failed' }, { status: 500 })
    )

    renderRoute(<ApprovalsInboxPage />, {
      path: '/approvals',
      route: '/approvals',
    })

    const orgInput = screen.getByLabelText(/Organization ID/i)
    await userEvent.type(orgInput, 'org-1')

    await waitFor(() => {
      expect(screen.getByText(/Server failed/i)).toBeInTheDocument()
    })
  })
})
