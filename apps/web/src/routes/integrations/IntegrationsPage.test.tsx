import { screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { IntegrationsPage } from './IntegrationsPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const activeIntegration = {
  id: 'integration-1',
  organization_id: 'org-1',
  type: 'slack_webhook',
  name: 'Production alerts',
  config: {},
  event_types: ['execution.failed'],
  is_active: true,
  credentials_configured: true,
  last_delivery_at: '2026-04-24T10:00:00Z',
  last_delivery_status: 'success',
  created_at: '2026-04-24T09:00:00Z',
  updated_at: '2026-04-24T10:00:00Z',
}

describe('IntegrationsPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders integration list', async () => {
    fetchMock.mockResolvedValue(createJsonResponse([activeIntegration]))

    renderRoute(<IntegrationsPage />, { path: '/integrations', route: '/integrations' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByText('Production alerts')).toBeInTheDocument()
    })

    expect(screen.getByText('Slack webhook')).toBeInTheDocument()
    expect(screen.getByText(/Credentials configured/i)).toBeInTheDocument()
    expect(screen.getByText(/execution.failed/i)).toBeInTheDocument()
  })

  it('renders empty state', async () => {
    fetchMock.mockResolvedValue(createJsonResponse([]))

    renderRoute(<IntegrationsPage />, { path: '/integrations', route: '/integrations' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByText(/No integrations configured/i)).toBeInTheDocument()
    })
  })

  it('submits create form through Django and removes plaintext URL from the DOM', async () => {
    const rawUrl = 'https://hooks.example.com/services/T000/B000/SECRET'
    const createdIntegration = {
      ...activeIntegration,
      id: 'integration-new',
      name: 'Webhook alerts',
      type: 'generic_webhook',
      event_types: ['execution.failed', 'approval.requested'],
    }

    fetchMock.mockImplementation((_url, init) => {
      if (init?.method === 'POST') {
        return Promise.resolve(createJsonResponse(createdIntegration, { status: 201 }))
      }
      return Promise.resolve(createJsonResponse([]))
    })

    renderRoute(<IntegrationsPage />, { path: '/integrations', route: '/integrations' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create integration/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Create integration/i }))
    await userEvent.type(screen.getByLabelText(/^Name$/i), 'Webhook alerts')
    await userEvent.selectOptions(screen.getByLabelText(/^Type$/i), 'generic_webhook')
    await userEvent.type(screen.getByLabelText(/Webhook URL/i), rawUrl)
    await userEvent.type(
      screen.getByLabelText(/Event types/i),
      'execution.failed, approval.requested'
    )
    await userEvent.click(screen.getByRole('button', { name: /^Create integration$/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/integrations/'),
        expect.objectContaining({ method: 'POST' })
      )
    })

    const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(postCall?.[1]?.body as string)).toMatchObject({
      organization_id: 'org-1',
      type: 'generic_webhook',
      name: 'Webhook alerts',
      credentials: { url: rawUrl },
      event_types: ['execution.failed', 'approval.requested'],
    })

    await waitFor(() => {
      expect(screen.queryByDisplayValue(rawUrl)).not.toBeInTheDocument()
    })
    expect(document.body).not.toHaveTextContent(rawUrl)
  })

  it('deactivates an active integration', async () => {
    fetchMock.mockImplementation((_url, init) => {
      if (init?.method === 'POST') {
        return Promise.resolve(createJsonResponse({ ...activeIntegration, is_active: false }))
      }
      return Promise.resolve(createJsonResponse([activeIntegration]))
    })

    renderRoute(<IntegrationsPage />, { path: '/integrations', route: '/integrations' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Deactivate/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Deactivate/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/integrations/integration-1/deactivate/'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })
})
