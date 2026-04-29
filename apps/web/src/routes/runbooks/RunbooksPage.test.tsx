import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunbooksPage } from './RunbooksPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const ORG_ID = 'org-1'

describe('RunbooksPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders runbook list without requiring ?organizationId= query param', async () => {
    fetchMock.mockResolvedValue(createJsonResponse([]))

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getByText('New runbook')).toBeInTheDocument()
    })
  })

  it('shows runbooks from the active org', async () => {
    const runbook = {
      id: 'rb-1',
      title: 'Rotate Creds',
      slug: 'rotate-creds',
      status: 'draft',
      organization_id: ORG_ID,
      created_at: '',
    }

    fetchMock.mockResolvedValueOnce(createJsonResponse([runbook]))

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getByText('Rotate Creds')).toBeInTheDocument()
    })

    const link = screen.getByRole('link', { name: 'View' })
    expect(link).toHaveAttribute('href', `/runbooks/${runbook.id}`)
  })

  it('submits the create form and calls Django runbooks endpoint', async () => {
    const newRunbook = {
      id: 'rb-1',
      title: 'Deploy API',
      slug: 'deploy-api',
      status: 'draft',
      organization_id: ORG_ID,
      created_at: '',
      raw_content: '1. Verify',
      updated_at: '',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse([])) // runbooks (initial)
      .mockResolvedValueOnce(createJsonResponse(newRunbook, { status: 201 })) // create
      .mockResolvedValueOnce(createJsonResponse([newRunbook])) // runbooks refetch

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks',
      auth: { activeOrganizationId: ORG_ID },
    })

    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByText('New runbook')).toBeInTheDocument())

    const titleInput = screen.getByPlaceholderText('Deploy API service')
    const slugInput = screen.getByPlaceholderText('deploy-api-service')
    await user.type(titleInput, 'Deploy API')
    await user.type(slugInput, 'deploy-api')
    await user.click(screen.getByRole('button', { name: 'Create runbook' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/runbooks/') &&
          (opts as RequestInit)?.method === 'POST'
      )
      expect(postCall).toBeDefined()
    })
  })

  it('shows empty state when there are no runbooks', async () => {
    fetchMock.mockResolvedValue(createJsonResponse([]))

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks',
      auth: { activeOrganizationId: ORG_ID },
    })

    await waitFor(() => {
      expect(screen.getByText('No runbooks yet.')).toBeInTheDocument()
    })
  })
})
