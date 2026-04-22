import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExecutionDetailPage } from './ExecutionDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

describe('ExecutionDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders execution detail and polls while the execution is active', async () => {
    const runningExecution = {
      id: 'execution-1',
      status: 'running',
      workflow_id: 'workflow-1',
      organization_id: 'organization-1',
      workflow_version: 1,
      workflow_snapshot: {},
      started_at: '2026-04-15T10:00:00Z',
      finished_at: null,
      created_at: '2026-04-15T10:00:00Z',
      updated_at: '2026-04-15T10:00:00Z',
      steps: [
        {
          id: 'step-1',
          position: 1,
          step_key: 'step-1',
          name: 'Verify prerequisites',
          step_type: 'manual',
          risk_level: 'low',
          command: '',
          requires_approval: false,
          status: 'running',
          started_at: '2026-04-15T10:00:05Z',
          finished_at: null,
          exit_code: null,
          error_message: '',
        },
      ],
    }

    const finishedExecution = {
      ...runningExecution,
      status: 'succeeded',
      finished_at: '2026-04-15T10:02:00Z',
      steps: [
        {
          ...runningExecution.steps[0],
          status: 'succeeded',
          finished_at: '2026-04-15T10:01:30Z',
          exit_code: 0,
        },
      ],
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runningExecution))
      .mockResolvedValueOnce(createJsonResponse(finishedExecution))

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    expect(screen.getByText('Loading execution…')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('Polling for runner updates…')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
    }, { timeout: 3000 })

    expect(screen.getAllByText('succeeded').length).toBeGreaterThan(0)
  })

  it('renders the Django error envelope when execution detail fails', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({ detail: 'execution unavailable' }, { status: 503 }),
    )

    renderRoute(<ExecutionDetailPage />, {
      path: '/executions/:executionId',
      route: '/executions/execution-1',
    })

    await waitFor(() => {
      expect(screen.getByText('execution unavailable')).toBeInTheDocument()
    })
  })
})
