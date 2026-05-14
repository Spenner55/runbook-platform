import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TargetConnectivityRoutesPage } from './TargetConnectivityRoutesPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const makeRoute = (overrides: Record<string, unknown> = {}) => ({
  id: 'route-1',
  organization_id: 'org-1',
  environment: 'production',
  target_type: 'host',
  normalized_identifier_pattern: 'db-*.prod.internal',
  pool_id: 'pool-1',
  required_labels: {},
  required_capabilities: ['vault'],
  priority: 10,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('TargetConnectivityRoutesPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders route list with target type and pattern', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [makeRoute()] }))

    renderRoute(<TargetConnectivityRoutesPage />, {
      path: '/runners/routes',
      route: '/runners/routes',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('host')).toBeInTheDocument()
    })

    expect(screen.getByText('db-*.prod.internal')).toBeInTheDocument()
    expect(screen.getByText('production')).toBeInTheDocument()
    expect(screen.getByText('vault')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('shows inactive route with reactivate button', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [makeRoute({ is_active: false })] }))

    renderRoute(<TargetConnectivityRoutesPage />, {
      path: '/runners/routes',
      route: '/runners/routes',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('inactive')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument()
  })

  it('deactivate action uses public API only', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/deactivate/')) return createJsonResponse(makeRoute({ is_active: false }))
      return createJsonResponse({ results: [makeRoute()] })
    })

    renderRoute(<TargetConnectivityRoutesPage />, {
      path: '/runners/routes',
      route: '/runners/routes',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Deactivate' })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Deactivate' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(urls.some((u) => u.includes('/deactivate/'))).toBe(true)
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
    expect(urls.every((u) => u.startsWith('http://localhost:8000/api/v1/'))).toBe(true)
  })

  it('reactivate action uses public API only', async () => {
    const urls: string[] = []
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      urls.push(url)
      if (url.includes('/reactivate/')) return createJsonResponse(makeRoute({ is_active: true }))
      return createJsonResponse({ results: [makeRoute({ is_active: false })] })
    })

    renderRoute(<TargetConnectivityRoutesPage />, {
      path: '/runners/routes',
      route: '/runners/routes',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Reactivate' })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Reactivate' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => {
      expect(urls.some((u) => u.includes('/reactivate/'))).toBe(true)
    })

    expect(urls.every((u) => !u.includes('/internal/'))).toBe(true)
  })

  it('shows empty state when no routes', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<TargetConnectivityRoutesPage />, {
      path: '/runners/routes',
      route: '/runners/routes',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(
        screen.getByText('No connectivity routes configured for this organization.')
      ).toBeInTheDocument()
    })
  })

  it('shows link back to runner pools', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<TargetConnectivityRoutesPage />, {
      path: '/runners/routes',
      route: '/runners/routes',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Runner Pools/i })).toBeInTheDocument()
    })
  })
})
