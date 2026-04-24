import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkflowCreatePage } from './WorkflowCreatePage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

describe('WorkflowCreatePage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows runbook-selection prompt when runbookId param is absent', () => {
    renderRoute(<WorkflowCreatePage />, {
      path: '/workflows/new',
      route: '/workflows/new',
    })

    expect(screen.getByText('Select a runbook first')).toBeInTheDocument()
  })

  it('renders runbook detail and generate button when runbookId is present', async () => {
    const runbook = {
      id: 'rb-1',
      title: 'Rotate Creds',
      slug: 'rotate-creds',
      status: 'draft',
      organization_id: 'org-1',
      raw_content: '1. Verify IAM context',
      created_at: '',
      updated_at: '',
    }

    fetchMock.mockResolvedValueOnce(createJsonResponse(runbook))

    renderRoute(<WorkflowCreatePage />, {
      path: '/workflows/new',
      route: '/workflows/new?runbookId=rb-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Rotate Creds')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: 'Generate workflow' })).toBeInTheDocument()
  })

  it('calls Django workflow endpoint (not FastAPI) on generate click', async () => {
    const runbook = {
      id: 'rb-1',
      title: 'Rotate Creds',
      slug: 'rotate-creds',
      status: 'draft',
      organization_id: 'org-1',
      raw_content: '1. Verify IAM context',
      created_at: '',
      updated_at: '',
    }
    const workflow = {
      id: 'wf-1',
      name: 'Rotate Creds',
      version: 1,
      status: 'draft',
      definition: { name: 'Rotate Creds', steps: [] },
      definition_schema_version: 'workflow.schema.v1',
      runbook_id: 'rb-1',
      organization_id: 'org-1',
      created_at: '',
      updated_at: '',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runbook))
      .mockResolvedValueOnce(createJsonResponse(workflow, { status: 201 }))

    renderRoute(<WorkflowCreatePage />, {
      path: '/workflows/new',
      route: '/workflows/new?runbookId=rb-1',
    })

    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Generate workflow' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Generate workflow' }))

    await waitFor(() => {
      // Should have posted to Django's workflow endpoint, not to any AI service URL
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/workflows/') &&
          (opts as RequestInit)?.method === 'POST',
      )
      expect(postCall).toBeDefined()

      // AI service must NOT be called by the frontend
      const aiCall = fetchMock.mock.calls.find(
        ([url]) => typeof url === 'string' && url.includes(':8001'),
      )
      expect(aiCall).toBeUndefined()
    })
  })

  it('shows error banner when workflow creation fails', async () => {
    const runbook = {
      id: 'rb-1',
      title: 'Rotate Creds',
      slug: 'rotate-creds',
      status: 'draft',
      organization_id: 'org-1',
      raw_content: '1. Verify',
      created_at: '',
      updated_at: '',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runbook))
      .mockResolvedValueOnce(
        createJsonResponse({ detail: 'AI service unavailable' }, { status: 503 }),
      )

    renderRoute(<WorkflowCreatePage />, {
      path: '/workflows/new',
      route: '/workflows/new?runbookId=rb-1',
    })

    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Generate workflow' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Generate workflow' }))

    await waitFor(() => {
      expect(screen.getByText('AI service unavailable')).toBeInTheDocument()
    })
  })
})
