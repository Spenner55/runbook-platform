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
  requires_review: false,
  parse_source: 'manual',
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
  definition_hash_sha256: '',
  catalog_version: '',
  validation_status: 'not_applicable',
  validation_report: { valid: true, errors: [], warnings: [] },
  runbook_id: 'rb-1',
  organization_id: 'org-1',
  created_at: '',
  updated_at: '',
}

const V2_WORKFLOW = {
  id: 'wf-2',
  name: 'Deploy App',
  version: 2,
  status: 'draft',
  requires_review: false,
  parse_source: 'manual',
  definition: {
    schemaVersion: '2',
    name: 'Deploy App',
    catalogVersion: 'pilot.v1',
    steps: [
      {
        id: 'step-1',
        name: 'Run deploy script',
        type: 'shell_command',
        risk: 'high',
        requiresApproval: false,
        action: {
          type: 'shell_command',
          version: 'pilot.v1',
          params: { command: './deploy.sh' },
        },
        secrets: ['DEPLOY_TOKEN'],
        artifacts: [{ key: 'deploy-log', kind: 'stdout' }],
        retry: { maxAttempts: 2 },
        idempotency: { mode: 'natural' },
      },
    ],
    secrets: [{ key: 'DEPLOY_TOKEN', displayName: 'Deploy Token' }],
  },
  definition_schema_version: 'workflow.schema.v2',
  definition_hash_sha256: 'abc123',
  catalog_version: 'pilot.v1',
  validation_status: 'valid',
  validation_report: { valid: true, errors: [], warnings: [] },
  runbook_id: 'rb-1',
  organization_id: 'org-1',
  created_at: '',
  updated_at: '',
}

const INVALID_V2_WORKFLOW = {
  ...V2_WORKFLOW,
  id: 'wf-3',
  validation_status: 'invalid',
  validation_report: {
    valid: false,
    errors: [
      {
        code: 'retry_requires_idempotency',
        detail: "Step 'step-1': retry.maxAttempts=3 requires idempotency.mode other than 'none'.",
      },
    ],
    warnings: [],
  },
}

const PUBLISHED_WORKFLOW = { ...DRAFT_WORKFLOW, status: 'published' }
const PENDING_REVIEW_WORKFLOW = {
  ...DRAFT_WORKFLOW,
  status: 'published',
  requires_review: true,
  parse_source: 'ai_parse',
}


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

  it('create execution button is disabled for pending-review workflow', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(PENDING_REVIEW_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create execution' })).toBeDisabled()
    })
    expect(
      screen.getByText(/requires review before it can be published or executed/i)
    ).toBeInTheDocument()
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

  it('v1 workflow shows migrate to v2 button', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(DRAFT_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Migrate to v2' })).toBeInTheDocument()
    })
  })

  it('v2 workflow renders action type, version, catalog, and step details', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(V2_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-2',
    })

    await waitFor(() => {
      expect(screen.getByText('Deploy App')).toBeInTheDocument()
    })

    expect(screen.getByText('workflow.schema.v2')).toBeInTheDocument()
    expect(screen.getByText('Run deploy script')).toBeInTheDocument()
    // action type shown in step list
    expect(screen.getAllByText(/shell_command/).length).toBeGreaterThan(0)
    // action version shown (catalog grid + step muted line)
    expect(screen.getAllByText(/pilot\.v1/).length).toBeGreaterThan(0)
    // command shown
    expect(screen.getByText('./deploy.sh')).toBeInTheDocument()
    // secret key shown, not a value input
    expect(screen.getAllByText(/DEPLOY_TOKEN/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('textbox', { name: /DEPLOY_TOKEN/i })).not.toBeInTheDocument()
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0)
    // artifact key shown
    expect(screen.getByText(/deploy-log/)).toBeInTheDocument()
    // no migrate button for v2
    expect(screen.queryByRole('button', { name: 'Migrate to v2' })).not.toBeInTheDocument()
  })

  it('displays validation errors for invalid v2 workflow', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(INVALID_V2_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-3',
    })

    await waitFor(() => {
      expect(screen.getByText('Validation errors')).toBeInTheDocument()
    })

    expect(screen.getByText(/retry_requires_idempotency/)).toBeInTheDocument()
    expect(screen.getByText(/retry\.maxAttempts=3 requires idempotency/)).toBeInTheDocument()
  })

  it('secret declaration keys are shown read-only, no secret value inputs', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(V2_WORKFLOW))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-2',
    })

    await waitFor(() => {
      expect(screen.getByText('Declared secrets')).toBeInTheDocument()
    })

    expect(screen.getByText('DEPLOY_TOKEN')).toBeInTheDocument()
    // no password or text input rendered for secrets
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0)
  })

  it('migrate to v2 button calls create-v2-draft endpoint and navigates', async () => {
    const newV2Workflow = { ...V2_WORKFLOW, id: 'wf-99' }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse(DRAFT_WORKFLOW))
      .mockResolvedValueOnce(createJsonResponse(newV2Workflow, { status: 201 }))

    renderRoute(<WorkflowDetailPage />, {
      path: '/workflows/:workflowId',
      route: '/workflows/wf-1',
    })

    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Migrate to v2' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Migrate to v2' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/v1/workflows/wf-1/create-v2-draft/') &&
          (opts as RequestInit)?.method === 'POST'
      )
      expect(postCall).toBeDefined()
    })
  })
})
