import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExecutionsPage } from './ExecutionsPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const ORG_ID = 'org-1'

function makeExecution(overrides: Record<string, unknown> = {}) {
  return {
    id: 'exec-aaaa-bbbb-cccc-dddd',
    status: 'succeeded',
    workflow_id: 'wf-1111-2222-3333-4444',
    organization_id: ORG_ID,
    workflow_version: 1,
    claimed_by_runner_id: 'runner-1',
    claimed_at: '2026-04-29T10:00:00Z',
    last_heartbeat_at: null,
    started_at: '2026-04-29T10:00:01Z',
    finished_at: '2026-04-29T10:05:00Z',
    created_at: '2026-04-29T10:00:00Z',
    updated_at: '2026-04-29T10:05:00Z',
    ...overrides,
  }
}

describe('ExecutionsPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows loading state while fetching', () => {
    fetchMock.mockReturnValue(new Promise(() => {}))

    renderRoute(<ExecutionsPage />, {
      path: '/executions',
      route: '/executions',
      auth: { activeOrganizationId: ORG_ID },
    })

    expect(screen.getByText('Loading executions…')).toBeInTheDocument()
  })

  it('shows error state when request fails', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ detail: 'Server error' }, { status: 500 }))

    renderRoute(<ExecutionsPage />, {
      path: '/executions',
      route: '/executions',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument()
    })
  })

  it('shows empty state when there are no executions', async () => {
    fetchMock.mockResolvedValue(createJsonResponse([]))

    renderRoute(<ExecutionsPage />, {
      path: '/executions',
      route: '/executions',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getByText('No executions yet.')).toBeInTheDocument()
    })
  })

  it('renders execution rows with status and link to detail', async () => {
    const execution = makeExecution()
    fetchMock.mockResolvedValue(createJsonResponse([execution]))

    renderRoute(<ExecutionsPage />, {
      path: '/executions',
      route: '/executions',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getByText('exec-aaa…')).toBeInTheDocument()
    })

    expect(screen.getByText('succeeded')).toBeInTheDocument()
    const viewLink = screen.getByRole('link', { name: 'View' })
    expect(viewLink).toHaveAttribute('href', `/executions/${execution.id}`)
  })

  it('filters executions by status when a filter button is clicked', async () => {
    const succeeded = makeExecution({ id: 'exec-succeeded', status: 'succeeded' })
    const failed = makeExecution({ id: 'exec-failed', status: 'failed' })

    fetchMock.mockResolvedValue(createJsonResponse([succeeded, failed]))

    const user = userEvent.setup()

    renderRoute(<ExecutionsPage />, {
      path: '/executions',
      route: '/executions',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: 'View' })).toHaveLength(2)
    })

    // Filter to only failed
    await user.click(screen.getByRole('button', { name: 'Failed' }))

    await waitFor(() => {
      expect(screen.getAllByRole('link', { name: 'View' })).toHaveLength(1)
    })
    expect(screen.getByText('failed')).toBeInTheDocument()
  })
})
