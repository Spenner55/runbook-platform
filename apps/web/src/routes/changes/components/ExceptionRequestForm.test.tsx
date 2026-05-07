import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExceptionRequestForm } from './ExceptionRequestForm'
import { createJsonResponse } from '../../../test/fetchResponse'
import { renderRoute } from '../../../test/renderRoute'

const mockException = {
  id: 'exc-1',
  change_record_id: 'change-1',
  exception_type: 'freeze_override',
  status: 'pending_approval',
  reason: 'Emergency fix',
  scope_json: { freeze_rule_id: 'rule-1', target_ids: ['t-1'] },
  requested_by_id: 'user-1',
  requested_at: '2026-05-06T00:00:00Z',
  approval_request_id: null,
  approved_by_id: null,
  approved_at: null,
  rejected_at: null,
  expires_at: '2026-05-07T00:00:00Z',
  resolved_at: null,
  resolution_note: '',
  created_at: '2026-05-06T00:00:00Z',
  updated_at: '2026-05-06T00:00:00Z',
}

describe('ExceptionRequestForm', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderForm(changeId = 'change-1') {
    return renderRoute(<ExceptionRequestForm changeId={changeId} />, {
      path: '/changes/:changeId',
      route: `/changes/${changeId}`,
      auth: { activeOrganizationId: 'org-1' },
    })
  }

  it('renders the exception type selector', () => {
    renderForm()
    expect(screen.getByLabelText(/exception type/i)).toBeInTheDocument()
  })

  it('shows freeze_override scope fields when that type is selected', async () => {
    renderForm()
    await userEvent.selectOptions(screen.getByLabelText(/exception type/i), 'freeze_override')
    await waitFor(() => {
      expect(screen.getByLabelText(/freeze rule id/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/target ids/i)).toBeInTheDocument()
    })
  })

  it('shows window_overrun scope fields when that type is selected', async () => {
    renderForm()
    await userEvent.selectOptions(screen.getByLabelText(/exception type/i), 'window_overrun')
    await waitFor(() => {
      expect(screen.getByLabelText(/change window id/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/allowed until/i)).toBeInTheDocument()
    })
  })

  it('shows late_verification scope fields when that type is selected', async () => {
    renderForm()
    await userEvent.selectOptions(screen.getByLabelText(/exception type/i), 'late_verification')
    await waitFor(() => {
      expect(screen.getByLabelText(/verification plan id/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/verification check ids/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/due at/i)).toBeInTheDocument()
    })
  })

  it('shows policy_override scope fields when that type is selected', async () => {
    renderForm()
    await userEvent.selectOptions(screen.getByLabelText(/exception type/i), 'policy_override')
    await waitFor(() => {
      expect(screen.getByLabelText(/policy evaluation id/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/policy rule ids/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/overridden outcome/i)).toBeInTheDocument()
    })
  })

  it('shows missing_artifact scope fields when that type is selected', async () => {
    renderForm()
    await userEvent.selectOptions(screen.getByLabelText(/exception type/i), 'missing_artifact')
    await waitFor(() => {
      expect(screen.getByLabelText(/verification check id/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/expected artifact kind/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/replacement evidence/i)).toBeInTheDocument()
    })
  })

  it('submits with correct payload for freeze_override type', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ results: [] })) // exceptions list fetch might happen
      .mockResolvedValueOnce(createJsonResponse(mockException, { status: 201 }))

    // Use a simpler mock: just the create call
    fetchMock.mockReset()
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockException, { status: 201 }))

    renderForm()
    await userEvent.selectOptions(screen.getByLabelText(/exception type/i), 'freeze_override')
    await userEvent.type(screen.getByLabelText(/reason/i), 'Emergency fix')
    await userEvent.type(screen.getByLabelText(/expires at/i), '2026-06-01T10:00')
    await userEvent.type(screen.getByLabelText(/freeze rule id/i), 'rule-abc')
    await userEvent.type(screen.getByLabelText(/target ids/i), 't-1, t-2')

    await userEvent.click(screen.getByRole('button', { name: /request exception/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const call = fetchMock.mock.calls[0]
    const body = JSON.parse((call[1] as RequestInit).body as string) as Record<string, unknown>
    expect(body.exception_type).toBe('freeze_override')
    expect(body.reason).toBe('Emergency fix')
    expect((body.scope_json as Record<string, unknown>).freeze_rule_id).toBe('rule-abc')
    expect((body.scope_json as Record<string, unknown>).target_ids).toEqual(['t-1', 't-2'])
  })

  it('does not call /api/v1/internal/ endpoints', async () => {
    renderForm()
    const allCalls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allCalls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
