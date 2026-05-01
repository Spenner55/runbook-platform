import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChangeCreatePage } from './ChangeCreatePage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const mockProfiles = [
  {
    id: 'profile-1',
    key: 'prod-maintenance',
    name: 'Production Maintenance',
    description: '',
    risk_level: 'high',
    requires_approval: true,
    verification_required: false,
    allowed_target_types: ['server'],
    allowed_workflows: [
      { id: 'workflow-1', name: 'Maintenance Workflow', version: 1 },
    ],
  },
]

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
  targets: [{ id: 't-1', position: 1, target_type: 'server', target_identifier: 'prod-01', display_name: '', environment: 'production' }],
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

  it('renders the create form with operation profile select', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: mockProfiles }))
    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/operation profile/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Production Maintenance/)).toBeInTheDocument()
  })

  it('shows workflow select after selecting a profile', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: mockProfiles }))
    renderPage()

    await waitFor(() => screen.getByLabelText(/operation profile/i))
    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')

    expect(screen.getByLabelText(/workflow/i)).toBeInTheDocument()
    expect(screen.getByText(/Maintenance Workflow/)).toBeInTheDocument()
  })

  it('submits the form and navigates to the new change on success', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: mockProfiles }))
      .mockResolvedValueOnce(createJsonResponse(mockChange, { status: 201 }))

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'Test Change')
    await userEvent.type(screen.getByLabelText(/justification/i), 'Needed')
    await userEvent.type(screen.getByLabelText(/target identifier/i), 'prod-01')

    await userEvent.click(screen.getByRole('button', { name: /create change/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })

  it('shows an error banner when create fails', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: mockProfiles }))
      .mockResolvedValueOnce(
        createJsonResponse({ errors: [{ code: 'invalid_operation_profile', detail: 'Profile not found.' }] }, { status: 400 }),
      )

    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'T')
    await userEvent.type(screen.getByLabelText(/justification/i), 'J')
    await userEvent.type(screen.getByLabelText(/target identifier/i), 'x')

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
})
