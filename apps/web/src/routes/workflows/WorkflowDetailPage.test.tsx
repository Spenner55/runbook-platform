import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkflowDetailPage } from './WorkflowDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const DRAFT_WORKFLOW = {
  id: 'wf-1',
  name: 'Rotate Creds',
  version: 1,
  status: 'draft',
  definition: {
    name: 'Rotate Creds',
    steps: [
      {
        id: 'step-1',
        name: 'Verify IAM context',
        type: 'manual_task',
        risk: 'medium',
        requiresApproval: false,
      },
      {
        id: 'step-2',
        name: 'Create replacement key',
        type: 'manual_task',
        risk: 'high',
        requiresApproval: true,
      },
    ],
  },
  definition_schema_version: 'workflow.schema.v1',
  runbook_id: 'rb-1',
  organization_id: 'org-1',
  created_at: '',
  updated_at: '',
}

const PUBLISHED_WORKFLOW = { ...DRAFT_WORKFLOW, status: 'published' }

describe('WorkflowDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows loading state while workflow query is pending', () => {
    fetchMock.mockReturnValue(new Promise(() => {})) // never resolves

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    expect(screen.getByText('Loading workflow…')).toBeInTheDocument()
  })

  it('renders workflow name, version, status and step list', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(DRAFT_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Rotate Creds')).toBeInTheDocument()
    })

    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
    expect(screen.getByText('Verify IAM context')).toBeInTheDocument()
    expect(screen.getByText('Create replacement key')).toBeInTheDocument()
  })

  it('shows publish button for draft workflow, not for published', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(DRAFT_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Publish workflow' })).toBeInTheDocument()
    })
  })

  it('create execution button is disabled for draft workflow', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(DRAFT_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create execution' })).toBeDisabled()
    })
  })

  it('create execution button is enabled for published workflow', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(PUBLISHED_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create execution' })).not.toBeDisabled()
    })
  })

  it('clicking create execution calls Django executions endpoint', async () => {
    const execution = {
      id: 'exe-1',
      status: 'queued',
      workflow_id: 'wf-1',
      organization_id: 'org-1',
      workflow_version: 1,
      workflow_snapshot: {},
      steps: [],
      created_at: '',
      updated_at: '',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(PUBLISHED_WORKFLOW))
      .mockResolvedValueOnce(createJsonResponse(execution, { status: 201 }))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create execution' })).not.toBeDisabled()
    })

    await user.click(screen.getByRole('button', { name: 'Create execution' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/executions/') &&
          (opts as RequestInit)?.method === 'POST'
      )
      expect(postCall).toBeDefined()
    })
  })

  it('shows error banner when workflow query fails', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ detail: 'Not found' }, { status: 404 }))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Not found')).toBeInTheDocument()
    })
  })
})
