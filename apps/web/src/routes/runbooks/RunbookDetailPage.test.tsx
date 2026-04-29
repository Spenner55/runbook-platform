import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RunbookDetailPage } from './RunbookDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const RUNBOOK_ID = 'rb-1'

const runbookDetail = {
  id: RUNBOOK_ID,
  title: 'Deploy API Service',
  slug: 'deploy-api-service',
  status: 'draft',
  organization_id: 'org-1',
  raw_content: '1. Verify\n2. Apply migrations\n3. Restart',
  created_at: '2026-04-29T10:00:00Z',
  updated_at: '2026-04-29T10:00:00Z',
}

function makeWorkflow(overrides: Record<string, unknown> = {}) {
  return {
    id: 'wf-1',
    name: 'Deploy API Service',
    version: 1,
    status: 'draft',
    definition_schema_version: '1.0',
    requires_review: false,
    parse_source: 'ai_parse',
    runbook_id: RUNBOOK_ID,
    organization_id: 'org-1',
    created_at: '2026-04-29T10:00:00Z',
    updated_at: '2026-04-29T10:00:00Z',
    ...overrides,
  }
}

describe('RunbookDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows runbook title and slug', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runbookDetail)) // runbook detail
      .mockResolvedValueOnce(createJsonResponse([])) // workflows list

    renderRoute(<RunbookDetailPage />, {
      path: '/runbooks/:runbookId',
      route: `/runbooks/${RUNBOOK_ID}`,
    })

    await waitFor(() => {
      expect(screen.getByText('Deploy API Service')).toBeInTheDocument()
    })
    expect(screen.getByText('deploy-api-service')).toBeInTheDocument()
  })

  it('shows associated workflows with links', async () => {
    const workflow = makeWorkflow()

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runbookDetail))
      .mockResolvedValueOnce(createJsonResponse([workflow]))

    renderRoute(<RunbookDetailPage />, {
      path: '/runbooks/:runbookId',
      route: `/runbooks/${RUNBOOK_ID}`,
    })

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'View' })).toBeInTheDocument()
    })

    const viewLink = screen.getByRole('link', { name: 'View' })
    expect(viewLink).toHaveAttribute('href', `/workflows/${workflow.id}`)
  })

  it('shows Needs review pill for workflows requiring review', async () => {
    const workflow = makeWorkflow({ requires_review: true })

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runbookDetail))
      .mockResolvedValueOnce(createJsonResponse([workflow]))

    renderRoute(<RunbookDetailPage />, {
      path: '/runbooks/:runbookId',
      route: `/runbooks/${RUNBOOK_ID}`,
    })

    await waitFor(() => {
      expect(screen.getByText('Needs review')).toBeInTheDocument()
    })
  })

  it('links Generate workflow button to workflow create page', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(runbookDetail))
      .mockResolvedValueOnce(createJsonResponse([]))

    renderRoute(<RunbookDetailPage />, {
      path: '/runbooks/:runbookId',
      route: `/runbooks/${RUNBOOK_ID}`,
    })

    await waitFor(() => {
      const link = screen.getByRole('link', { name: 'Generate workflow (AI)' })
      expect(link).toHaveAttribute('href', `/workflows/new?runbookId=${RUNBOOK_ID}`)
    })
  })
})
