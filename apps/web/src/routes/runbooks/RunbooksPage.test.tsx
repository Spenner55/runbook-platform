import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunbooksPage } from './RunbooksPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

describe('RunbooksPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows organization-selection prompt when organizationId is absent', () => {
    fetchMock.mockResolvedValue(createJsonResponse([]))

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks',
    })

    expect(screen.getByText('Select an organization first')).toBeInTheDocument()
  })

  it('renders runbook create form when organizationId is present', async () => {
    const org = { id: 'org-1', name: 'Acme', slug: 'acme', created_at: '', updated_at: '' }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse([org]))  // organizations
      .mockResolvedValueOnce(createJsonResponse([]))     // runbooks

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks?organizationId=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Create a runbook')).toBeInTheDocument()
    })
  })

  it('submits the create form and calls Django runbooks endpoint', async () => {
    const org = { id: 'org-1', name: 'Acme', slug: 'acme', created_at: '', updated_at: '' }
    const newRunbook = {
      id: 'rb-1',
      title: 'Deploy API',
      slug: 'deploy-api',
      status: 'draft',
      organization_id: 'org-1',
      created_at: '',
      raw_content: '1. Verify',
      updated_at: '',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse([org]))             // organizations
      .mockResolvedValueOnce(createJsonResponse([]))                // runbooks (initial)
      .mockResolvedValueOnce(createJsonResponse(newRunbook, { status: 201 })) // create
      .mockResolvedValueOnce(createJsonResponse([]))                // organizations refetch
      .mockResolvedValueOnce(createJsonResponse([newRunbook]))      // runbooks refetch

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks?organizationId=org-1',
    })

    const user = userEvent.setup()

    await waitFor(() => expect(screen.getByText('Create a runbook')).toBeInTheDocument())

    const titleInput = screen.getByPlaceholderText('Deploy API service')
    const slugInput = screen.getByPlaceholderText('deploy-api-service')
    await user.type(titleInput, 'Deploy API')
    await user.type(slugInput, 'deploy-api')
    await user.click(screen.getByRole('button', { name: 'Create runbook' }))

    // Verify the POST went to Django's runbook endpoint, not FastAPI
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/runbooks/') &&
          (opts as RequestInit)?.method === 'POST',
      )
      expect(postCall).toBeDefined()
    })
  })

  it('shows existing runbooks with generate-workflow links', async () => {
    const org = { id: 'org-1', name: 'Acme', slug: 'acme', created_at: '', updated_at: '' }
    const runbook = {
      id: 'rb-1',
      title: 'Rotate Creds',
      slug: 'rotate-creds',
      status: 'draft',
      organization_id: 'org-1',
      created_at: '',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse([org]))
      .mockResolvedValueOnce(createJsonResponse([runbook]))

    renderRoute(<RunbooksPage />, {
      path: '/runbooks',
      route: '/runbooks?organizationId=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Rotate Creds')).toBeInTheDocument()
    })

    const link = screen.getByRole('link', { name: 'Generate workflow' })
    expect(link).toHaveAttribute('href', `/workflows/new?runbookId=${runbook.id}`)
  })
})
