import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BreakglassActivationModal } from './BreakglassActivationModal'
import { createJsonResponse } from '../../../test/fetchResponse'
import { renderRoute } from '../../../test/renderRoute'

const mockSession = {
  id: 'bg-session-1',
  change_record_id: 'change-1',
  status: 'active' as const,
  scope_sha256: 'abc123'.padEnd(64, '0'),
  reason: 'Production incident',
  activated_by_id: 'user-1',
  started_at: '2026-05-06T10:00:00Z',
  expires_at: '2026-05-06T12:00:00Z',
  ended_at: null,
  end_reason: '',
  review_due_at: '2026-05-07T10:00:00Z',
  review_status: 'pending' as const,
  created_at: '2026-05-06T10:00:00Z',
  updated_at: '2026-05-06T10:00:00Z',
}

describe('BreakglassActivationModal', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  function renderModal(changeId = 'change-1') {
    const onClose = vi.fn()
    const onSuccess = vi.fn()
    renderRoute(
      <BreakglassActivationModal changeId={changeId} onClose={onClose} onSuccess={onSuccess} />,
      {
        path: '/changes/:changeId',
        route: `/changes/${changeId}`,
        auth: { activeOrganizationId: 'org-1' },
      }
    )
    return { onClose, onSuccess }
  }

  it('renders the activation dialog', () => {
    renderModal()
    expect(screen.getByRole('dialog', { name: /activate breakglass/i })).toBeInTheDocument()
  })

  it('rejects submission with empty reason', async () => {
    renderModal()

    await userEvent.type(screen.getByLabelText(/expires at/i), '2099-01-01T12:00')
    await userEvent.type(screen.getByLabelText(/allowed actions/i), 'dispatch')
    await userEvent.type(screen.getByLabelText(/gate types/i), 'window_overrun')
    await userEvent.type(screen.getByLabelText(/target ids/i), 'target-1')
    await userEvent.click(screen.getByLabelText(/confirm breakglass activation/i))

    await userEvent.click(screen.getByRole('button', { name: /activate breakglass/i }))

    await waitFor(() => {
      expect(screen.getByText(/reason is required/i)).toBeInTheDocument()
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects submission with empty scope fields', async () => {
    renderModal()

    await userEvent.type(screen.getByLabelText(/reason/i), 'Emergency')
    await userEvent.type(screen.getByLabelText(/expires at/i), '2099-01-01T12:00')
    // Leave allowed actions empty
    await userEvent.click(screen.getByLabelText(/confirm breakglass activation/i))

    await userEvent.click(screen.getByRole('button', { name: /activate breakglass/i }))

    await waitFor(() => {
      expect(screen.getByText(/scope must include/i)).toBeInTheDocument()
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects open-ended expiry (no expiry value)', async () => {
    renderModal()

    await userEvent.type(screen.getByLabelText(/reason/i), 'Emergency')
    await userEvent.type(screen.getByLabelText(/allowed actions/i), 'dispatch')
    await userEvent.type(screen.getByLabelText(/gate types/i), 'window_overrun')
    await userEvent.type(screen.getByLabelText(/target ids/i), 'target-1')
    await userEvent.click(screen.getByLabelText(/confirm breakglass activation/i))
    // Do NOT fill expires_at

    await userEvent.click(screen.getByRole('button', { name: /activate breakglass/i }))

    await waitFor(() => {
      expect(screen.getByText(/expiry is required/i)).toBeInTheDocument()
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('requires confirmation checkbox before submitting', async () => {
    renderModal()
    // Confirm button is disabled without checkbox
    const submitBtn = screen.getByRole('button', { name: /activate breakglass/i })
    expect(submitBtn).toBeDisabled()
  })

  it('submits with correct payload when all fields are filled', async () => {
    fetchMock.mockResolvedValueOnce(createJsonResponse(mockSession, { status: 201 }))

    renderModal()

    await userEvent.type(screen.getByLabelText(/reason/i), 'Production incident')
    // Use fireEvent for datetime-local to avoid issues
    fireEvent.change(screen.getByLabelText(/expires at/i), {
      target: { value: '2099-12-31T23:59' },
    })
    await userEvent.type(screen.getByLabelText(/allowed actions/i), 'dispatch')
    await userEvent.type(screen.getByLabelText(/gate types/i), 'window_overrun')
    await userEvent.type(screen.getByLabelText(/target ids/i), 'target-1, target-2')
    await userEvent.click(screen.getByLabelText(/confirm breakglass activation/i))

    await userEvent.click(screen.getByRole('button', { name: /activate breakglass/i }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const [, call] = [fetchMock.mock.calls[0][0], fetchMock.mock.calls[0][1]] as [
      string,
      RequestInit,
    ]
    const body = JSON.parse(call.body as string) as Record<string, unknown>
    expect(body.reason).toBe('Production incident')
    expect((body.scope_json as Record<string, unknown>).allowed_actions).toContain('dispatch')
    expect((body.scope_json as Record<string, unknown>).target_ids).toContain('target-1')
    expect(body.expires_at).toBeDefined()
  })

  it('does not call /api/v1/internal/ endpoints', async () => {
    renderModal()
    const allCalls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(allCalls.every((url) => !url.includes('/api/v1/internal/'))).toBe(true)
  })
})
