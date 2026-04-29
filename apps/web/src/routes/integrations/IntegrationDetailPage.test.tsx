import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { IntegrationDetailPage } from './IntegrationDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const integration = {
  id: 'integration-1',
  organization_id: 'org-1',
  type: 'slack_webhook',
  name: 'Production alerts',
  config: {},
  event_types: ['execution.failed'],
  is_active: true,
  credentials_configured: true,
  last_delivery_at: '2026-04-24T10:00:00Z',
  last_delivery_status: 'failed',
  created_at: '2026-04-24T09:00:00Z',
  updated_at: '2026-04-24T10:00:00Z',
}

const successfulAttempt = {
  id: 'attempt-1',
  integration_id: 'integration-1',
  organization_id: 'org-1',
  event_type: 'approval.requested',
  payload_preview: { execution_id: 'execution-1' },
  http_status: 200,
  success: true,
  error_detail: '',
  latency_ms: 125,
  attempted_at: '2026-04-24T10:00:00Z',
  created_at: '2026-04-24T10:00:00Z',
  updated_at: '2026-04-24T10:00:00Z',
}

const failedAttempt = {
  id: 'attempt-2',
  integration_id: 'integration-1',
  organization_id: 'org-1',
  event_type: 'execution.failed',
  payload_preview: { execution_id: 'execution-2' },
  http_status: 500,
  success: false,
  error_detail: 'Remote endpoint returned 500.',
  latency_ms: 300,
  attempted_at: '2026-04-24T10:05:00Z',
  created_at: '2026-04-24T10:05:00Z',
  updated_at: '2026-04-24T10:05:00Z',
}

describe('IntegrationDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders delivery history', async () => {
    fetchMock.mockImplementation((url) => {
      if (String(url).includes('/delivery-attempts/')) {
        return Promise.resolve(createJsonResponse({ results: [successfulAttempt, failedAttempt] }))
      }
      return Promise.resolve(createJsonResponse(integration))
    })

    renderRoute(<IntegrationDetailPage />, {
      path: '/integrations/:integrationId',
      route: '/integrations/integration-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Production alerts')).toBeInTheDocument()
    })

    expect(screen.getByText('approval.requested')).toBeInTheDocument()
    expect(screen.getAllByText('execution.failed').length).toBeGreaterThan(0)
    expect(screen.getByText('HTTP 200')).toBeInTheDocument()
    expect(screen.getByText('HTTP 500')).toBeInTheDocument()
  })

  it('uses the active organization when the detail URL has no organization_id', async () => {
    fetchMock.mockImplementation((url) => {
      if (String(url).includes('/delivery-attempts/')) {
        return Promise.resolve(createJsonResponse({ results: [] }))
      }
      return Promise.resolve(createJsonResponse(integration))
    })

    renderRoute(<IntegrationDetailPage />, {
      path: '/integrations/:integrationId',
      route: '/integrations/integration-1',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Production alerts')).toBeInTheDocument()
    })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/integrations/integration-1/?organization_id=org-1'),
      expect.any(Object)
    )
  })

  it('shows failed delivery row as failed with error summary', async () => {
    fetchMock.mockImplementation((url) => {
      if (String(url).includes('/delivery-attempts/')) {
        return Promise.resolve(createJsonResponse({ results: [failedAttempt] }))
      }
      return Promise.resolve(createJsonResponse(integration))
    })

    renderRoute(<IntegrationDetailPage />, {
      path: '/integrations/:integrationId',
      route: '/integrations/integration-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getAllByText('execution.failed').length).toBeGreaterThan(0)
    })

    expect(screen.getByText('failed')).toBeInTheDocument()
    expect(screen.getByText('Remote endpoint returned 500.')).toBeInTheDocument()
  })

  it('requires organization_id before loading detail', () => {
    renderRoute(<IntegrationDetailPage />, {
      path: '/integrations/:integrationId',
      route: '/integrations/integration-1',
    })

    expect(screen.getByText(/organization_id is required/i)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
