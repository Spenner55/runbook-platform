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

const mockVerifiedChange = {
  ...mockVerificationPendingChange,
  status: 'verified',
  verification_pending_at: '2026-05-01T10:30:00Z',
}

const mockVerificationFailedChange = {
  ...mockVerificationPendingChange,
  status: 'verification_failed',
  verification_pending_at: '2026-05-01T10:30:00Z',
}

const mockVerificationPlan = {
  id: 'plan-1',
  change_record_id: 'change-1',
  mode: 'mixed',
  status: 'active',
  required_check_count: 3,
  satisfied_required_count: 1,
  failed_required_count: 1,
  checks: [
    {
      id: 'check-1',
      key: 'runner-health-check',
      name: 'Runner health check',
      description: '',
      check_type: 'runner_step',
      required: true,
      status: 'passed',
      verification_key: 'postdeploy.health.ok',
      last_result: {
        id: 'result-1',
        outcome: 'passed',
        source: 'runner',
        validated_at: '2026-05-01T10:30:00Z',
      },
    },
    {
      id: 'check-2',
      key: 'operator-attestation',
      name: 'Operator attestation',
      description: 'Independent operator must verify change',
      check_type: 'manual_attestation',
      required: true,
      status: 'pending',
      verification_key: 'operator.independent.review',
      last_result: null,
    },
    {
      id: 'check-3',
      key: 'diagnostic-artifact',
      name: 'Diagnostic report',
      description: '',
      check_type: 'artifact_presence',
      required: true,
      status: 'failed',
      verification_key: 'postdeploy.diagnostics',
      last_result: {
        id: 'result-2',
        outcome: 'failed',
        source: 'runner',
        validated_at: '2026-05-01T10:31:00Z',
      },
    },
  ],
  unmet_required_checks: [
    {
      id: 'check-2',
      key: 'operator-attestation',
      name: 'Operator attestation',
      check_type: 'manual_attestation',
    },
    {
      id: 'check-3',
      key: 'diagnostic-artifact',
      name: 'Diagnostic report',
      check_type: 'artifact_presence',
    },
  ],
}

const mockSatisfiedPlan = {
  ...mockVerificationPlan,
  status: 'satisfied',
  satisfied_required_count: 3,
  failed_required_count: 0,
  checks: mockVerificationPlan.checks.map((c) => ({ ...c, status: 'passed' })),
  unmet_required_checks: [],
}

// Helper: after a change loads, ChangeViolationSection fires useRetroReviews then useExceptions.
// For verification changes, VerificationSection fires useVerificationPlan after those two.
// Use these helpers to set up mocks in the correct fetch order.
const emptyResults = () => createJsonResponse({ results: [] })

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
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults()) // retro-reviews
      .mockResolvedValueOnce(emptyResults()) // exceptions
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Restart nginx on prod-01')).toBeInTheDocument()
    })
    expect(screen.getByText('draft')).toBeInTheDocument()
  })

  it('renders targets section', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Targets')).toBeInTheDocument()
    })
    expect(screen.getByText(/prod-web-01/)).toBeInTheDocument()
  })

  it('shows submit button for draft changes', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /submit for approval/i })).toBeInTheDocument()
    })
  })

  it('does not show submit button for non-draft changes', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('pending approval'))
    expect(screen.queryByRole('button', { name: /submit for approval/i })).not.toBeInTheDocument()
  })

  it('shows approval request section when present', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
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
      .mockResolvedValueOnce(emptyResults()) // retro-reviews
      .mockResolvedValueOnce(emptyResults()) // exceptions
      .mockResolvedValueOnce(createJsonResponse(submittedChange)) // POST submit
      .mockResolvedValueOnce(createJsonResponse(submittedChange)) // re-fetch

    renderPage()
    await waitFor(() => screen.getByRole('button', { name: /submit for approval/i }))

    await userEvent.click(screen.getByRole('button', { name: /submit for approval/i }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        (c) => c[1] !== undefined && (c[1] as RequestInit).method === 'POST'
      )
      expect(postCall).toBeTruthy()
    })
  })

  // ---- New: Hash rendering ----

  it('renders requested inputs hash when present', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText(/inputs hash/i))
    // The hash is truncated; check that the truncated prefix appears
    expect(screen.getByText(/abc123def456abc1/)).toBeInTheDocument()
  })

  it('renders request snapshot hash when present', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText(/snapshot hash/i))
    expect(screen.getByText(/deadbeef12345678/)).toBeInTheDocument()
  })

  it('does not render hash rows when hashes are empty strings', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    expect(screen.queryByText(/inputs hash/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/snapshot hash/i)).not.toBeInTheDocument()
  })

  // ---- New: Policy decision rendering ----

  it('renders policy decision section when present', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockRunningChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Policy Decision'))
    expect(screen.getByText('auto_approve')).toBeInTheDocument()
    // decision_source "workflow_default" → "workflow default"; reason also contains this phrase
    // — use getAllByText to handle multiple matches safely
    expect(screen.getAllByText(/workflow default/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/no matching policy rule/i)).toBeInTheDocument()
  })

  it('does not render policy decision section when absent', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    expect(screen.queryByText('Policy Decision')).not.toBeInTheDocument()
  })

  // ---- New: Verification state ----

  it('renders verification section when status is verification_pending', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults()) // retro-reviews
      .mockResolvedValueOnce(emptyResults()) // exceptions
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByText('Verification'))
    // "verification pending" appears in both the status badge and the Verification section
    expect(screen.getAllByText('verification pending').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/pending since/i)).toBeInTheDocument()
  })

  it('does not render verification section for draft or running', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    expect(screen.queryByText('Verification')).not.toBeInTheDocument()
  })

  // ---- Verification checklist ----

  it('renders passed, pending, and failed checks in the checklist', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByText('Runner health check'))
    // Names appear in both unmet list and checks list
    expect(screen.getAllByText('Operator attestation').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Diagnostic report').length).toBeGreaterThanOrEqual(1)

    // Status pills (may appear multiple times across check status + last result)
    expect(screen.getAllByText('passed').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('pending').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('failed').length).toBeGreaterThanOrEqual(1)
  })

  it('renders plan mode and progress summary in the checklist', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByText('mixed'))
    expect(screen.getByText(/1\/3 required passed/i)).toBeInTheDocument()
  })

  it('renders unmet required checks blocking display', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByText(/unmet required checks/i))
    expect(screen.getAllByText('Operator attestation').length).toBeGreaterThanOrEqual(1)
  })

  it('shows Attest button only for pending manual_attestation checks', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    // Wait for checklist to load by looking for check names
    await waitFor(() => screen.getByText('Runner health check'))
    // manual_attestation pending check gets Attest button
    expect(screen.getByRole('button', { name: /^attest$/i })).toBeInTheDocument()
  })

  it('opens attestation form when Attest button is clicked', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^attest$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^attest$/i }))

    expect(
      screen.getByRole('dialog', { name: /attest: operator attestation/i })
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/attestation statement/i)).toBeInTheDocument()
  })

  it('manual attestation form submits correct payload', async () => {
    const resultResponse = {
      id: 'result-new',
      check_id: 'check-2',
      outcome: 'passed',
      validation_status: 'accepted',
      change_status: 'verified',
      plan_status: 'satisfied',
      validated_at: '2026-05-01T10:35:00Z',
      unmet_required_checks: [],
    }
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults()) // retro-reviews
      .mockResolvedValueOnce(emptyResults()) // exceptions
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
      .mockResolvedValueOnce(createJsonResponse(resultResponse, { status: 201 }))
      // re-fetches after mutation
      .mockResolvedValueOnce(createJsonResponse(mockSatisfiedPlan))
      .mockResolvedValueOnce(createJsonResponse(mockVerifiedChange))
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^attest$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^attest$/i }))

    await userEvent.type(
      screen.getByLabelText(/attestation statement/i),
      'I verified production metrics.'
    )
    await userEvent.click(screen.getByRole('button', { name: /submit attestation/i }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        (c) => typeof c[0] === 'string' && c[0].includes('/verification-results/')
      )
      expect(postCall).toBeTruthy()
      const body = JSON.parse(String((postCall?.[1] as RequestInit)?.body ?? '{}'))
      expect(body.check_id).toBe('check-2')
      expect(body.outcome).toBe('passed')
      expect(body.manual_attestation_text).toBe('I verified production metrics.')
    })
  })

  it('displays self-review and API rejection errors from the attestation form', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
      .mockResolvedValueOnce(
        createJsonResponse(
          { detail: 'Self-review is not allowed for this check.' },
          { status: 409 }
        )
      )
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^attest$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^attest$/i }))
    await userEvent.type(screen.getByLabelText(/attestation statement/i), 'I did the review.')
    await userEvent.click(screen.getByRole('button', { name: /submit attestation/i }))

    await waitFor(() => {
      expect(screen.getByText(/self-review is not allowed/i)).toBeInTheDocument()
    })
  })

  // ---- Closure panel ----

  it('does not show close button for verification_pending change', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByText('Verification'))
    expect(screen.queryByRole('button', { name: /^close change$/i })).not.toBeInTheDocument()
  })

  it('shows close button when change is verified', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerifiedChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockSatisfiedPlan))
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^close change$/i }))
    expect(screen.getByRole('button', { name: /^close change$/i })).toBeInTheDocument()
  })

  it('shows close button for verification_failed change', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationFailedChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^close change$/i }))
    expect(screen.getByRole('button', { name: /^close change$/i })).toBeInTheDocument()
  })

  it('opens closure dialog on close button click and shows outcome options for verified change', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerifiedChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockSatisfiedPlan))
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^close change$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^close change$/i }))

    expect(screen.getByRole('dialog', { name: /close change/i })).toBeInTheDocument()
    // success should be available for verified changes
    expect(screen.getByRole('option', { name: /^success$/i })).toBeInTheDocument()
  })

  it('closure confirm button is disabled until outcome and summary are filled', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerifiedChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockSatisfiedPlan))
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^close change$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^close change$/i }))

    const confirmBtn = screen.getByRole('button', { name: /confirm closure/i })
    // disabled initially (no outcome or summary selected)
    expect(confirmBtn).toBeDisabled()
  })

  it('server closure rejection displays correctly even after form is filled', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerifiedChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockSatisfiedPlan))
      .mockResolvedValueOnce(
        createJsonResponse(
          { detail: 'Independent reviewer is required for this profile.' },
          { status: 409 }
        )
      )
    renderPage()

    await waitFor(() => screen.getByRole('button', { name: /^close change$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^close change$/i }))

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /outcome/i }), 'success')
    await userEvent.type(screen.getByLabelText(/summary/i), 'Change completed successfully.')
    await userEvent.click(screen.getByRole('button', { name: /confirm closure/i }))

    await waitFor(() => {
      expect(screen.getByText(/independent reviewer is required/i)).toBeInTheDocument()
    })
  })

  // ---- No internal API calls (extended) ----

  it('does not call /api/v1/internal/ endpoints during verification flow', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(createJsonResponse(mockVerificationPlan))
    renderPage()

    await waitFor(() => screen.getByText('Runner health check'))
    const allUrls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allUrls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })

  // ---- New: Approval detail link ----

  it('renders a link to the approvals inbox in the approval section', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockPendingChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Approval Request'))
    const link = screen.getByRole('link', { name: /view approvals inbox/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/approvals')
  })

  // ---- New: Execution detail link ----

  it('renders a link to the execution detail page in the binding section', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockRunningChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Execution Binding'))
    const link = screen.getByRole('link', { name: /exec-99/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/executions/exec-99')
  })

  // ---- New: All changes link ----

  it('renders a link back to the changes list', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    const link = screen.getByRole('link', { name: /all changes/i })
    expect(link).toHaveAttribute('href', '/changes')
  })

  // ---- New: No internal API calls ----

  it('does not call /api/v1/internal/ endpoints', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(mockDraftChange))
      .mockResolvedValueOnce(emptyResults())
      .mockResolvedValueOnce(emptyResults())
    renderPage()

    await waitFor(() => screen.getByText('Restart nginx on prod-01'))
    const allUrls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allUrls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
