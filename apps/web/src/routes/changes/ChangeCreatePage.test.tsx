import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChangeCreatePage } from './ChangeCreatePage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const mockProfileSingleType = {
  id: 'profile-1',
  key: 'prod-maintenance',
  name: 'Production Maintenance',
  description: '',
  risk_level: 'high',
  requires_approval: true,
  verification_required: false,
  allowed_target_types: ['server'],
  allowed_workflows: [{ id: 'workflow-1', name: 'Maintenance Workflow', version: 1 }],
}

const mockProfileMultiType = {
  id: 'profile-2',
  key: 'prod-database',
  name: 'Database Ops',
  description: '',
  risk_level: 'critical',
  requires_approval: true,
  verification_required: true,
  allowed_target_types: ['database', 'cache'],
  allowed_workflows: [{ id: 'workflow-2', name: 'DB Workflow', version: 2 }],
}

const mockChange = {
  id: 'change-1',
  status: 'draft',
  title: 'Test Change',
  summary: '',
  justification: 'Needed',
  operation_profile: { id: 'profile-1', key: 'prod-maintenance', name: 'Production Maintenance' },
  workflow_id: 'workflow-1',
  workflow_version_snapshot: null,
  requested_inputs_sha256: '',
  request_snapshot_sha256: '',
  operation_profile_key_snapshot: '',
  scheduled_for: null,
  submitted_at: null,
  approved_at: null,
  dispatchable_at: null,
  running_at: null,
  verification_pending_at: null,
  closed_at: null,
  rejected_at: null,
  canceled_at: null,
  expired_at: null,
  terminal_reason: '',
  targets: [
    {
      id: 't-1',
      position: 1,
      target_type: 'server',
      target_identifier: 'prod-01',
      display_name: '',
      environment: 'production',
    },
  ],
  approval_request: null,
  policy_decision: null,
  execution_binding: null,
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
}

describe('ChangeCreatePage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderPage() {
    return renderRoute(<ChangeCreatePage />, {
      path: '/changes/new',
      route: '/changes/new',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  // ---- Existing baseline tests ----

  it('renders the create form with operation profile select', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/operation profile/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Production Maintenance/)).toBeInTheDocument()
  })

  it('shows workflow select after selecting a profile', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()

    await waitFor(() => screen.getByLabelText(/operation profile/i))
    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')

    expect(screen.getByLabelText(/workflow/i)).toBeInTheDocument()
    expect(screen.getByText(/Maintenance Workflow/)).toBeInTheDocument()
  })

  it('submits the form and navigates to the new change on success', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
      .mockResolvedValueOnce(createJsonResponse(mockChange, { status: 201 }))

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'Test Change')
    await userEvent.type(screen.getByLabelText(/justification/i), 'Needed')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'prod-01')

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })

  it('shows an error banner when create fails', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
      .mockResolvedValueOnce(
        createJsonResponse(
          { errors: [{ code: 'invalid_operation_profile', detail: 'Profile not found.' }] },
          { status: 400 },
        ),
      )

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'x')

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => {
      expect(screen.getByText(/Profile not found/)).toBeInTheDocument()
    })
  })

  it('shows loading state when profiles are fetching', async () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getByText(/Loading profiles/i)).toBeInTheDocument()
  })

  // ---- New: Summary field ----

  it('renders the summary field', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/summary/i))
    expect(screen.getByLabelText(/summary/i)).toBeInTheDocument()
  })

  // ---- New: Requested inputs ----

  it('renders the requested inputs textarea', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/requested inputs/i))
    expect(screen.getByLabelText(/requested inputs/i)).toBeInTheDocument()
  })

  it('shows an error when requested inputs is invalid JSON', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    // Wait for profile select (profiles loaded) then interact
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'x')

    // Use fireEvent to avoid userEvent treating '{' as a key modifier
    fireEvent.change(screen.getByLabelText(/requested inputs/i), {
      target: { value: 'not valid json' },
    })

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => {
      expect(screen.getByText(/invalid json/i)).toBeInTheDocument()
    })
    // Should NOT have called the create API
    expect(fetchMock).toHaveBeenCalledTimes(1) // only profile load
  })

  it('shows an error when requested inputs is a JSON array, not object', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'x')

    fireEvent.change(screen.getByLabelText(/requested inputs/i), {
      target: { value: '[1,2,3]' },
    })

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => {
      expect(screen.getByText(/must be a json object/i)).toBeInTheDocument()
    })
  })

  it('sends requested inputs JSON in create payload', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
      .mockResolvedValueOnce(createJsonResponse(mockChange, { status: 201 }))

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'x')

    // Use fireEvent so curly braces are not interpreted as key modifiers
    fireEvent.change(screen.getByLabelText(/requested inputs/i), {
      target: { value: '{"ticket":"CHG-99"}' },
    })

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [, createCall] = fetchMock.mock.calls
    const body = JSON.parse((createCall[1] as RequestInit).body as string) as Record<string, unknown>
    expect(body.requested_inputs).toEqual({ ticket: 'CHG-99' })
  })

  // ---- New: Scheduling field ----

  it('renders the scheduled for field', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/scheduled for/i))
    expect(screen.getByLabelText(/scheduled for/i)).toBeInTheDocument()
  })

  it('sends scheduled_for as ISO string when filled', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
      .mockResolvedValueOnce(createJsonResponse(mockChange, { status: 201 }))

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'x')

    const scheduleInput = screen.getByLabelText(/scheduled for/i)
    await userEvent.type(scheduleInput, '2026-06-01T04:00')

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [, createCall] = fetchMock.mock.calls
    const body = JSON.parse((createCall[1] as RequestInit).body as string) as Record<string, unknown>
    expect(typeof body.scheduled_for).toBe('string')
    expect(body.scheduled_for).toContain('2026-06-01')
  })

  // ---- New: Multiple targets ----

  it('starts with one target row', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    expect(screen.queryByLabelText(/Target 1 identifier/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/Target 2 identifier/i)).not.toBeInTheDocument()
  })

  it('adds a second target row when Add Target is clicked', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.click(screen.getByRole('button', { name: /add target/i }))

    expect(screen.getByLabelText(/Target 2 identifier/i)).toBeInTheDocument()
  })

  it('removes a target row when Remove is clicked', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.click(screen.getByRole('button', { name: /add target/i }))
    await waitFor(() => screen.getByLabelText(/Target 2 identifier/i))

    await userEvent.click(screen.getByRole('button', { name: /remove target 2/i }))

    expect(screen.queryByLabelText(/Target 2 identifier/i)).not.toBeInTheDocument()
  })

  it('does not show remove button when only one target', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    expect(screen.queryByRole('button', { name: /remove target 1/i })).not.toBeInTheDocument()
  })

  it('sends multiple targets in the create payload', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
      .mockResolvedValueOnce(createJsonResponse(mockChange, { status: 201 }))

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'prod-01')

    await userEvent.click(screen.getByRole('button', { name: /add target/i }))
    await userEvent.type(screen.getByLabelText(/Target 2 identifier/i), 'prod-02')

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [, createCall] = fetchMock.mock.calls
    const body = JSON.parse((createCall[1] as RequestInit).body as string) as { targets: unknown[] }
    expect(body.targets).toHaveLength(2)
  })

  // ---- New: Duplicate target prevention ----

  it('shows a duplicate target error and does not call create API', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/Target 1 identifier/i), 'prod-01')

    await userEvent.click(screen.getByRole('button', { name: /add target/i }))
    await userEvent.type(screen.getByLabelText(/Target 2 identifier/i), 'PROD-01') // same after normalize

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => {
      expect(screen.getByText(/duplicate target/i)).toBeInTheDocument()
    })
    expect(fetchMock).toHaveBeenCalledTimes(1) // only profile load
  })

  // ---- New: Profile-driven target-type reset ----

  it('resets target type to first allowed type when profile changes', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({ results: [mockProfileSingleType, mockProfileMultiType] }),
    )
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    // Select first profile — allowed types: ['server']
    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await waitFor(() => screen.getByLabelText(/Target 1 type/i))
    expect(screen.getByLabelText(/Target 1 type/i)).toHaveValue('server')

    // Switch to second profile — allowed types: ['database', 'cache']
    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-database')
    await waitFor(() => {
      expect(screen.getByLabelText(/Target 1 type/i)).toHaveValue('database')
    })
  })

  it('resets targets to a single row when profile changes', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({ results: [mockProfileSingleType, mockProfileMultiType] }),
    )
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.click(screen.getByRole('button', { name: /add target/i }))
    expect(screen.getByLabelText(/Target 2 identifier/i)).toBeInTheDocument()

    // Switching profile should reset to 1 target
    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-database')
    expect(screen.queryByLabelText(/Target 2 identifier/i)).not.toBeInTheDocument()
  })

  // ---- No internal API calls ----

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfileSingleType] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    const allCalls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allCalls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
