import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunnerPoolsPage } from './RunnerPoolsPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const makePool = (overrides: Record<string, unknown> = {}) => ({
  id: 'pool-1',
  organization_id: 'org-1',
  key: 'prod-us-east',
  name: 'Production US East',
  display_name: 'Production US East',
  description: '',
  environment: 'production',
  network_zone: 'us-east-1',
  status: 'active',
  max_concurrent_executions: 5,
  max_concurrent_per_target: 1,
  default_for_non_change_executions: false,
  labels: {},
  capabilities: [],
  drain_requested_at: null,
  disabled_at: null,
  active_runner_count: 2,
  active_execution_count: 1,
  capacity_summary: { max_concurrent_executions: 5, active_executions: 1, available_capacity: 4 },
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('RunnerPoolsPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders pool list with health states', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/')) {
        return createJsonResponse({
          results: [
            makePool({ id: 'pool-1', key: 'prod-us-east', status: 'active' }),
            makePool({ id: 'pool-2', key: 'staging-pool', name: 'Staging', status: 'draining' }),
            makePool({
              id: 'pool-3',
              key: 'offline-pool',
              name: 'Disabled Pool',
              status: 'disabled',
            }),
          ],
        })
      }
      if (url.includes('/runners/')) {
        return createJsonResponse({ results: [] })
      }
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Production US East')).toBeInTheDocument()
    })

    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('draining')).toBeInTheDocument()
    expect(screen.getAllByText('disabled').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Staging')).toBeInTheDocument()
    expect(screen.getByText('Disabled Pool')).toBeInTheDocument()
  })

  it('shows active executions and capacity', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/')) {
        return createJsonResponse({
          results: [
            makePool({
              active_execution_count: 3,
              capacity_summary: {
                max_concurrent_executions: 5,
                active_executions: 3,
                available_capacity: 2,
              },
            }),
          ],
        })
      }
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Production US East')).toBeInTheDocument()
    })

    expect(screen.getByText('3/5')).toBeInTheDocument()
  })

  it('shows capacity full indicator when pool is at capacity', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/')) {
        return createJsonResponse({
          results: [
            makePool({
              capacity_summary: {
                max_concurrent_executions: 2,
                active_executions: 2,
                available_capacity: 0,
              },
            }),
          ],
        })
      }
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('2/2')).toBeInTheDocument()
    })
  })

  it('shows reactivate button for draining pool', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/')) {
        return createJsonResponse({ results: [makePool({ status: 'draining' })] })
      }
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument()
    })
  })

  it('drain action calls public API only', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/runner-pools/') && url.includes('/drain/')) {
        return createJsonResponse(makePool({ status: 'draining' }))
      }
      if (url.includes('/runner-pools/')) {
        return createJsonResponse({ results: [makePool()] })
      }
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Drain' })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Drain' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(urls.some((u) => u.includes('/drain/'))).toBe(true)
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
    expect(urls.every((u) => u.startsWith('http://localhost:8000/api/v1/'))).toBe(true)
  })

  it('disable action calls public API only', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/runner-pools/') && url.includes('/disable/')) {
        return createJsonResponse(makePool({ status: 'disabled' }))
      }
      if (url.includes('/runner-pools/')) {
        return createJsonResponse({ results: [makePool()] })
      }
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Disable' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(urls.some((u) => u.includes('/disable/'))).toBe(true)
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
  })

  it('shows empty state when no pools', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/')) return createJsonResponse({ results: [] })
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(
        screen.getByText('No runner pools configured for this organization.')
      ).toBeInTheDocument()
    })
  })

  it('shows link to connectivity routes', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/')) return createJsonResponse({ results: [] })
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolsPage />, {
      path: '/runners',
      route: '/runners',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'Connectivity Routes' })).toBeInTheDocument()
    })
  })
})
