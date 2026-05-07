import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChangeEmergencyCreatePage } from './ChangeEmergencyCreatePage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const mockProfile = {
  id: 'profile-1',
  key: 'prod-maintenance',
  name: 'Production Maintenance',
  description: '',
  risk_level: 'high',
  requires_approval: true,
  verification_required: false,
  allow_emergency_changes: true,
  allowed_target_types: ['server'],
  allowed_workflows: [{ id: 'workflow-1', name: 'Maintenance Workflow', version: 1 }],
}

const mockChange = {
  id: 'change-emrg-1',
  status: 'draft',
  title: 'Emergency fix',
  summary: '',
  justification: 'Incident',
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
  targets: [],
  approval_request: null,
  policy_decision: null,
  execution_binding: null,
  window: null,
  is_emergency: true,
  emergency_reason: 'Production incident',
  retro_review_required: true,
  retro_review_due_at: null,
  retro_review_blocking_status: '',
  active_breakglass_session: null,
  created_at: '2026-05-06T00:00:00Z',
  updated_at: '2026-05-06T00:00:00Z',
}

describe('ChangeEmergencyCreatePage', () => {
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
    return renderRoute(<ChangeEmergencyCreatePage />, {
      path: '/changes/new/emergency',
      route: '/changes/new/emergency',
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('renders the emergency warning banner', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfile] }))
    renderPage()
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.getByText(/emergency mode/i)).toBeInTheDocument()
  })

  it('renders the emergency reason field', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfile] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/emergency reason/i))
    expect(screen.getByLabelText(/emergency reason/i)).toBeInTheDocument()
  })

  it('hides profiles that do not allow emergency changes', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({
        results: [
          mockProfile,
          {
            ...mockProfile,
            id: 'profile-2',
            key: 'standard-maintenance',
            name: 'Standard Maintenance',
            allow_emergency_changes: false,
          },
        ],
      })
    )
    renderPage()
    await waitFor(() => screen.getByLabelText(/operation profile/i))

    expect(screen.getByRole('option', { name: /production maintenance/i })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /standard maintenance/i })).not.toBeInTheDocument()
  })

  it('sends is_emergency=true and emergency_reason in the create payload', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [mockProfile] }))
      .mockResolvedValueOnce(createJsonResponse(mockChange, { status: 201 }))

    renderPage()
    await waitFor(() => screen.getByLabelText(/emergency reason/i))

    await userEvent.type(screen.getByLabelText(/emergency reason/i), 'Production incident')
    await userEvent.selectOptions(screen.getByLabelText(/operation profile/i), 'prod-maintenance')
    await userEvent.selectOptions(screen.getByLabelText(/workflow/i), 'workflow-1')
    await userEvent.type(screen.getByLabelText(/title/i), 'Emergency fix')
    await userEvent.type(screen.getByLabelText(/justification/i), 'Incident')
    await userEvent.type(screen.getByLabelText(/target 1 identifier/i), 'prod-01')

    await userEvent.click(screen.getByRole('button', { name: /create emergency change/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const [, createCall] = fetchMock.mock.calls
    const body = JSON.parse((createCall[1] as RequestInit).body as string) as Record<
      string,
      unknown
    >
    expect(body.is_emergency).toBe(true)
    expect(body.emergency_reason).toBe('Production incident')
  })

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [mockProfile] }))
    renderPage()
    await waitFor(() => screen.getByLabelText(/emergency reason/i))

    const allCalls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allCalls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
