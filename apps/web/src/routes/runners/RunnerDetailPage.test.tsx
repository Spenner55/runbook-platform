import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunnerDetailPage } from './RunnerDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const makeRunner = (overrides: Record<string, unknown> = {}) => ({
  id: 'runner-1',
  organization_id: 'org-1',
  pool_id: 'pool-1',
  display_name: 'runner-prod-01',
  status: 'active',
  runner_version: '1.4.0',
  hostname: 'worker-01.prod.internal',
  last_heartbeat_at: new Date(Date.now() - 5000).toISOString(),
  last_seen_at: new Date(Date.now() - 5000).toISOString(),
  drain_requested_at: null,
  disabled_at: null,
  revoked_at: null,
  active_execution_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('RunnerDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders runner detail with canonical ID and display name', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner()))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('runner-prod-01')).toBeInTheDocument()
    })

    expect(screen.getByText('runner-1')).toBeInTheDocument()
    expect(screen.getByText('1.4.0')).toBeInTheDocument()
    expect(screen.getByText('worker-01.prod.internal')).toBeInTheDocument()
  })

  it('shows active (live) heartbeat state', async () => {
    const recentTs = new Date(Date.now() - 5000).toISOString()
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner({ last_heartbeat_at: recentTs })))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('runner-prod-01')).toBeInTheDocument()
    })

    const heartbeatLabel = screen.getByText(/5s ago/i)
    expect(heartbeatLabel).toBeInTheDocument()
  })

  it('shows OFFLINE state when heartbeat is stale', async () => {
    const staleTs = new Date(Date.now() - 200000).toISOString()
    fetchMock.mockResolvedValue(
      createJsonResponse(makeRunner({ last_heartbeat_at: staleTs, status: 'offline' }))
    )

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('OFFLINE')).toBeInTheDocument()
    })
  })

  it('shows STALE state when heartbeat is between 30s and 120s', async () => {
    const staleTs = new Date(Date.now() - 60000).toISOString()
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner({ last_heartbeat_at: staleTs })))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('STALE')).toBeInTheDocument()
    })
  })

  it('shows drain/disable/revoke action buttons', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner()))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Drain' })).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument()
  })

  it('disable button is disabled for revoked runner', async () => {
    fetchMock.mockResolvedValue(
      createJsonResponse(makeRunner({ status: 'revoked', revoked_at: '2026-05-14T10:00:00Z' }))
    )

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Disable' })).toBeDisabled()
    })

    expect(screen.getByRole('button', { name: 'Revoke' })).toBeDisabled()
  })

  it('links pool ID back to pool detail page', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner({ pool_id: 'pool-1' })))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('runner-prod-01')).toBeInTheDocument()
    })

    const poolLinks = screen.getAllByRole('link', { name: /pool-1/i })
    expect(poolLinks.length).toBeGreaterThan(0)
    expect(poolLinks[0]).toHaveAttribute('href', '/runners/pools/pool-1')
  })

  it('drain action calls public runners endpoint only', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/drain/')) return createJsonResponse(makeRunner({ status: 'draining' }))
      return createJsonResponse(makeRunner())
    })

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Drain' })).toBeInTheDocument()
    })

    const drainBtn = screen.getByRole('button', { name: 'Drain' })
    await drainBtn.click()

    await waitFor(() => {
      expect(urls.some((u) => u.includes('/runners/runner-1/drain/'))).toBe(true)
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
  })

  it('shows last seen timestamp', async () => {
    const seenAt = '2026-05-14T09:00:00Z'
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner({ last_seen_at: seenAt })))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Last Seen')).toBeInTheDocument()
    })
  })

  it('does not display tokens or credentials in DOM', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(makeRunner()))

    renderRoute(<RunnerDetailPage />, {
      path: '/runners/runners/:runnerId',
      route: '/runners/runners/runner-1',
    })

    await waitFor(() => {
      expect(screen.getByText('runner-prod-01')).toBeInTheDocument()
    })

    expect(screen.queryByText(/token_hash/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/fingerprint_sha256/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/RUNNER_REGISTRATION_TOKEN/i)).not.toBeInTheDocument()
  })
})
