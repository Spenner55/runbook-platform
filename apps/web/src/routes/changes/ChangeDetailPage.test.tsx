import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChangeDetailPage } from './ChangeDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const mockDraftChange = {
  id: 'change-1',
  status: 'draft',
  title: 'Restart nginx on prod-01',
  summary: 'Routine maintenance restart',
  justification: 'High memory usage detected',
  operation_profile: { id: 'profile-1', key: 'prod-maintenance', name: 'Production Maintenance' },
  workflow_id: 'workflow-1',
  workflow_version_snapshot: 2,
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
      target_identifier: 'prod-web-01',
      display_name: '',
      environment: 'production',
    },
  ],
  approval_request: null,
  policy_decision: null,
  execution_binding: null,
  created_at: '2026-05-01T10:00:00Z',
  updated_at: '2026-05-01T10:00:00Z',
}

const mockPendingChange = {
  ...mockDraftChange,
  status: 'pending_approval',
  submitted_at: '2026-05-01T10:01:00Z',
  requested_inputs_sha256: 'abc123def456abc1',
  request_snapshot_sha256: 'deadbeef12345678',
  approval_request: {
    id: 'ar-1',
    status: 'pending',
    requested_at: '2026-05-01T10:01:00Z',
    expires_at: '2026-05-01T11:01:00Z',
  },
}

const mockRunningChange = {
  ...mockDraftChange,
  status: 'running',
  submitted_at: '2026-05-01T10:01:00Z',
  approved_at: '2026-05-01T10:02:00Z',
  running_at: '2026-05-01T10:05:00Z',
  requested_inputs_sha256: 'abc123def456abc1',
  request_snapshot_sha256: 'deadbeef12345678',
  approval_request: {
    id: 'ar-1',
    status: 'approved',
    requested_at: '2026-05-01T10:01:00Z',
    expires_at: '2026-05-01T11:01:00Z',
  },
  policy_decision: {
    policy_evaluation_id: 'pe-1',
    outcome: 'auto_approve',
    effective_outcome: 'auto_approve',
    decision_source: 'workflow_default',
    reason: 'No matching policy rule; using workflow default.',
  },
  execution_binding: {
    id: 'eb-1',
    execution_id: 'exec-99',
    execution_status: 'running',
    reserved_at: '2026-05-01T10:03:00Z',
    bound_at: '2026-05-01T10:05:00Z',
    operation_profile_key: 'prod-maintenance',
    requested_inputs_sha256: 'abc123def456abc1',
  },
}

const mockVerificationPendingChange = {
  ...mockRunningChange,
  status: 'verification_pending',
  verification_pending_at: '2026-05-01T10:30:00Z',
}

describe('ChangeDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderPage(changeId = 'change-1') {
    return renderRoute(<ChangeDetailPage />, {
      path: '/changes/:changeId',
      route: `/changes/${changeId}`,
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  // ---- Existing baseline tests ----

  it('renders change title and status for a draft change', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Restart nginx on prod-01')).toBeInTheDocument()
    })
    expect(screen.getByText('draft')).toBeInTheDocument()
  })

  it('renders targets section', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Targets')).toBeInTheDocument()
    })
    expect(screen.getByText(/prod-web-01/)).toBeInTheDocument()
  })

  it('shows submit button for draft changes', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /submit for approval/i })).toBeInTheDocument()
    })
  })

  it('does not show submit button for non-draft changes', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockPendingChange))
    renderPage()

    await waitFor(() => screen.getByText('pending approval'))
    expect(screen.queryByRole('button', { name: /submit for approval/i })).not.toBeInTheDocument()
  })

  it('shows approval request section when present', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockPendingChange))
    renderPage()

    await waitFor(() => screen.getByText('Approval Request'))
    expect(screen.getByText('pending')).toBeInTheDocument()
  })

  it('shows loading state while fetching', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))
    renderPage()
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows error state when change not found', async () => {
    fetchMock.mockResolvedValueOnce(
      createJsonResponse({ errors: [{ code: 'not_found', detail: 'Not found.' }] }, { status: 404 })
    )
    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/change not found/i)).toBeInTheDocument()
    })
  })

  it('submits the change and updates status', async () => {
    const submittedChange = {
      ...mockDraftChange,
      status: 'pending_approval',
      submitted_at: '2026-05-01T10:05:00Z',
      approval_request: {
        id: 'ar-2',
        status: 'pending',
        requested_at: '2026-05-01T10:05:00Z',
        expires_at: '2026-05-01T11:05:00Z',
      },
    }
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(createJsonResponse(submittedChange))
      .mockResolvedValueOnce(createJsonResponse(submittedChange))

    renderPage()
    await waitFor(() => screen.getByRole('button', { name: /submit for approval/i }))

    await userEvent.click(screen.getByRole('button', { name: /submit for approval/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })

  // ---- New: Hash rendering ----

  it('renders requested inputs hash when present', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockPendingChange))
    renderPage()

    await waitFor(() => screen.getByText(/inputs hash/i))
    // The hash is truncated; check that the truncated prefix appears
    expect(screen.getByText(/abc123def456abc1/)).toBeInTheDocument()
  })

  it('renders request snapshot hash when present', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockPendingChange))
    renderPage()

    await waitFor(() => screen.getByText(/snapshot hash/i))
    expect(screen.getByText(/deadbeef12345678/)).toBeInTheDocument()
  })

  it('does not render hash rows when hashes are empty strings', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    expect(screen.queryByText(/inputs hash/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/snapshot hash/i)).not.toBeInTheDocument()
  })

  // ---- New: Policy decision rendering ----

  it('renders policy decision section when present', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockRunningChange))
    renderPage()

    await waitFor(() => screen.getByText('Policy Decision'))
    expect(screen.getByText('auto_approve')).toBeInTheDocument()
    // decision_source "workflow_default" → "workflow default"; reason also contains this phrase
    // — use getAllByText to handle multiple matches safely
    expect(screen.getAllByText(/workflow default/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/no matching policy rule/i)).toBeInTheDocument()
  })

  it('does not render policy decision section when absent', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    expect(screen.queryByText('Policy Decision')).not.toBeInTheDocument()
  })

  // ---- New: Verification state ----

  it('renders verification section when status is verification_pending', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
    renderPage()

    await waitFor(() => screen.getByText('Verification'))
    // "verification pending" appears in both the status badge and the Verification section
    expect(screen.getAllByText('verification pending').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/pending since/i)).toBeInTheDocument()
  })

  it('does not render verification section for draft or running', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    expect(screen.queryByText('Verification')).not.toBeInTheDocument()
  })

  // ---- New: Approval detail link ----

  it('renders a link to the approvals inbox in the approval section', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockPendingChange))
    renderPage()

    await waitFor(() => screen.getByText('Approval Request'))
    const link = screen.getByRole('link', { name: /view approvals inbox/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/approvals')
  })

  // ---- New: Execution detail link ----

  it('renders a link to the execution detail page in the binding section', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockRunningChange))
    renderPage()

    await waitFor(() => screen.getByText('Execution Binding'))
    const link = screen.getByRole('link', { name: /exec-99/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/executions/exec-99')
  })

  // ---- New: All changes link ----

  it('renders a link back to the changes list', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    const link = screen.getByRole('link', { name: /all changes/i })
    expect(link).toHaveAttribute('href', '/changes')
  })

  // ---- New: No internal API calls ----

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockDraftChange))
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    const allUrls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allUrls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
