import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunnerPoolDetailPage } from './RunnerPoolDetailPage'
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
  capabilities: ['docker', 'vault'],
  drain_requested_at: null,
  disabled_at: null,
  active_runner_count: 2,
  active_execution_count: 1,
  capacity_summary: { max_concurrent_executions: 5, active_executions: 1, available_capacity: 4 },
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

const makeRunner = (overrides: Record<string, unknown> = {}) => ({
  id: 'runner-1',
  organization_id: 'org-1',
  pool_id: 'pool-1',
  display_name: 'runner-prod-01',
  status: 'active',
  runner_version: '1.2.3',
  hostname: 'worker-01.prod.internal',
  last_heartbeat_at: new Date(Date.now() - 5000).toISOString(),
  last_seen_at: new Date(Date.now() - 5000).toISOString(),
  drain_requested_at: null,
  disabled_at: null,
  revoked_at: null,
  active_execution_count: 1,
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('RunnerPoolDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders pool detail with capacity info', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/pool-1')) return createJsonResponse(makePool())
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolDetailPage />, {
      path: '/runners/pools/:poolId',
      route: '/runners/pools/pool-1',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Production US East')).toBeInTheDocument()
    })

    expect(screen.getByText('prod-us-east')).toBeInTheDocument()
    expect(screen.getByText('production')).toBeInTheDocument()
    expect(screen.getByText('docker, vault')).toBeInTheDocument()
    expect(screen.getByText('1/5 (4 available)')).toBeInTheDocument()
  })

  it('renders runners with links to detail pages', async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/pool-1')) return createJsonResponse(makePool())
      if (url.includes('/runners/')) return createJsonResponse({ results: [makeRunner()] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolDetailPage />, {
      path: '/runners/pools/:poolId',
      route: '/runners/pools/pool-1',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'runner-prod-01' })).toBeInTheDocument()
    })

    const runnerLink = screen.getByRole('link', { name: 'runner-prod-01' })
    expect(runnerLink).toHaveAttribute('href', '/runners/runners/runner-1')
  })

  it('shows runner heartbeat liveness state', async () => {
    const staleTime = new Date(Date.now() - 60000).toISOString()
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/pool-1')) return createJsonResponse(makePool())
      if (url.includes('/runners/'))
        return createJsonResponse({
          results: [
            makeRunner({ last_heartbeat_at: new Date(Date.now() - 5000).toISOString() }),
            makeRunner({
              id: 'runner-2',
              display_name: 'runner-prod-02',
              last_heartbeat_at: staleTime,
              status: 'offline',
            }),
          ],
        })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolDetailPage />, {
      path: '/runners/pools/:poolId',
      route: '/runners/pools/pool-1',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('runner-prod-01')).toBeInTheDocument()
    })

    expect(screen.getByText('runner-prod-02')).toBeInTheDocument()
  })

  it('shows draining status with timestamp', async () => {
    const drainAt = '2026-05-14T10:00:00Z'
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/runner-pools/pool-1'))
        return createJsonResponse(makePool({ status: 'draining', drain_requested_at: drainAt }))
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolDetailPage />, {
      path: '/runners/pools/:poolId',
      route: '/runners/pools/pool-1',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('draining')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument()
  })

  it('pool detail fetches public API only', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/runner-pools/pool-1')) return createJsonResponse(makePool())
      if (url.includes('/runners/')) return createJsonResponse({ results: [] })
      return createJsonResponse({})
    })

    renderRoute(<RunnerPoolDetailPage />, {
      path: '/runners/pools/:poolId',
      route: '/runners/pools/pool-1',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Production US East')).toBeInTheDocument()
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
    expect(urls.every((u) => u.startsWith('http://localhost:8000/api/v1/'))).toBe(true)
  })
})
