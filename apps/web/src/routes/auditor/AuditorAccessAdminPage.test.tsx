import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AuditorAccessAdminPage } from './AuditorAccessAdminPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const auth = {
  activeOrganizationId: 'org-1',
  user: {
    id: 'admin-1',
    email: 'admin@example.com',
    first_name: 'Admin',
    last_name: 'User',
    full_name: 'Admin User',
    is_staff: false,
    created_at: '2026-05-01T00:00:00Z',
    active_organization_id: 'org-1',
    memberships: [
      {
        id: 'membership-1',
        role: 'admin' as const,
        organization: { id: 'org-1', name: 'Acme', slug: 'acme' },
      },
    ],
  },
}

const emptyGrants = { results: [] }

describe('AuditorAccessAdminPage', () => {
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
    return renderRoute(<AuditorAccessAdminPage />, {
      path: '/audit/access',
      route: '/audit/access',
      auth,
    })
  }

  it('submits valid grant data', async () => {
    const user = userEvent.setup()
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(emptyGrants))
      .mockResolvedValueOnce(
        createJsonResponse({
          id: 'grant-1',
          user_id: 'user-1',
          status: 'active',
          scope: { all: true },
          reason: 'annual audit',
          starts_at: null,
          expires_at: null,
          revoked_at: null,
          created_by_id: 'admin-1',
          revoked_by_id: null,
          last_used_at: null,
          created_at: '2026-05-02T00:00:00Z',
          updated_at: '2026-05-02T00:00:00Z',
        })
      )
      .mockResolvedValueOnce(createJsonResponse(emptyGrants))
    renderPage()

    await screen.findByText('Auditor Access Grants')
    await user.type(screen.getByLabelText('User ID'), 'user-1')
    await user.type(screen.getByLabelText('Reason'), 'annual audit')
    await user.click(screen.getByRole('button', { name: /create grant/i }))

    const init = fetchMock.mock.calls[1]?.[1]
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain('/api/v1/audit/access-grants/')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({
      user_id: 'user-1',
      scope: { all: true },
      reason: 'annual audit',
    })
  })

  it('renders grant creation validation errors', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValueOnce(createJsonResponse(emptyGrants))
    renderPage()

    await screen.findByText('Auditor Access Grants')
    await user.type(screen.getByLabelText('User ID'), 'user-1')
    const scopeBox = screen.getByLabelText('Scope JSON')
    await user.clear(scopeBox)
    fireEvent.change(scopeBox, { target: { value: '{invalid' } })
    await user.click(screen.getByRole('button', { name: /create grant/i }))

    expect(screen.getByText('Scope must be valid JSON.')).toBeInTheDocument()
  })
})
