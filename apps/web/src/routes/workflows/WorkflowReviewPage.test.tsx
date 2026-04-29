import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkflowReviewPage } from './WorkflowReviewPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const PENDING_REVIEW_WORKFLOW = {
  id: 'wf-1',
  name: 'Rotate Creds',
  version: 1,
  status: 'draft',
  requires_review: true,
  parse_source: 'ai_parse',
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
        type: 'shell_command',
        risk: 'high',
        requiresApproval: true,
        command: 'aws iam create-access-key',
      },
    ],
  },
  definition_schema_version: 'workflow.schema.v1',
  runbook_id: 'rb-1',
  organization_id: 'org-1',
  created_at: '',
  updated_at: '',
}

describe('WorkflowReviewPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders pending-review workflow details and messaging', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(PENDING_REVIEW_WORKFLOW))

    renderRoute(<WorkflowReviewPage />, {
      path: '/workflows/:workflowId/review',
      route: '/workflows/wf-1/review',
    })

    await waitFor(() => {
      expect(screen.getByText('Rotate Creds')).toBeInTheDocument()
    })
    expect(
      screen.getByText(/requires review before it can be published or executed/i)
    ).toBeInTheDocument()
    expect(screen.getByText('Verify IAM context')).toBeInTheDocument()
    expect(screen.getByText('Create replacement key')).toBeInTheDocument()
  })

  it('accept review action calls Django endpoint', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(PENDING_REVIEW_WORKFLOW))
      .mockResolvedValueOnce(
        createJsonResponse({ ...PENDING_REVIEW_WORKFLOW, requires_review: false })
      )

    renderRoute(<WorkflowReviewPage />, {
      path: '/workflows/:workflowId/review',
      route: '/workflows/wf-1/review',
    })

    const user = userEvent.setup()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Accept workflow' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Accept workflow' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/workflows/wf-1/accept-review/') &&
          (opts as RequestInit)?.method === 'POST'
      )
      expect(postCall).toBeDefined()
    })
  })

  it('reject review action calls Django endpoint', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(PENDING_REVIEW_WORKFLOW))
      .mockResolvedValueOnce(createJsonResponse({ ...PENDING_REVIEW_WORKFLOW, status: 'archived' }))

    renderRoute(<WorkflowReviewPage />, {
      path: '/workflows/:workflowId/review',
      route: '/workflows/wf-1/review',
    })

    const user = userEvent.setup()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Reject workflow' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Reject workflow' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/workflows/wf-1/reject-review/') &&
          (opts as RequestInit)?.method === 'POST'
      )
      expect(postCall).toBeDefined()
    })
  })
})
