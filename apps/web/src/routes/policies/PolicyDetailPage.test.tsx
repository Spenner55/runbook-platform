import { screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PolicyDetailPage } from './PolicyDetailPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const ruleHighRisk = {
  id: 'rule-1',
  name: 'High risk approval',
  description: 'Require approval for high risk steps',
  is_active: true,
  priority: 10,
  condition_type: 'risk_level' as const,
  condition_params: { operator: 'in', values: ['high', 'critical'] },
  outcome: 'approval_required' as const,
  reason: 'High risk requires human sign-off',
  created_at: '2026-04-01T10:00:00Z',
  updated_at: '2026-04-01T10:00:00Z',
}

const policyDetail = {
  id: 'policy-1',
  organization_id: 'org-1',
  name: 'Production Safety Policy',
  description: 'Safety policy for production',
  is_active: true,
  rule_count: 1,
  rules: [ruleHighRisk],
  created_at: '2026-04-01T10:00:00Z',
  updated_at: '2026-04-15T12:00:00Z',
}

describe('PolicyDetailPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('renders loading state initially', () => {
    fetchMock.mockReturnValue(new Promise(() => {}))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    expect(screen.getByText(/Loading policy/i)).toBeInTheDocument()
  })

  it('renders policy detail with name and description', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(policyDetail))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText('Production Safety Policy')).toBeInTheDocument()
    })

    expect(screen.getByText('Safety policy for production')).toBeInTheDocument()
    expect(screen.getAllByText('active').length).toBeGreaterThan(0)
  })

  it('renders rules list with rule names and outcomes', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(policyDetail))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText('High risk approval')).toBeInTheDocument()
    })

    expect(screen.getByText('Approval Required')).toBeInTheDocument()
    expect(screen.getByText(/Priority 10/i)).toBeInTheDocument()
  })

  it('shows empty state when no rules', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ ...policyDetail, rules: [], rule_count: 0 }))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText(/No rules yet/i)).toBeInTheDocument()
    })
  })

  it('shows rule form when Add rule button is clicked', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(policyDetail))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Add rule/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Add rule/i }))

    expect(screen.getByText('Rule name')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Add rule$/i })).toBeInTheDocument()
  })

  it('shows edit form when Edit details button is clicked', async () => {
    fetchMock.mockResolvedValue(createJsonResponse(policyDetail))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Edit details/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Edit details/i }))

    expect(screen.getByRole('button', { name: /Save/i })).toBeInTheDocument()
  })

  it('renders error banner on API failure', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ detail: 'Not found' }, { status: 404 }))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText(/Not found/i)).toBeInTheDocument()
    })
  })

  it('requires organization_id before loading detail', () => {
    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1',
    })

    expect(screen.getByText(/organization_id is required/i)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('submits metadata updates with organization scope', async () => {
    const updatedPolicy = { ...policyDetail, name: 'Updated Safety Policy' }
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(policyDetail))
      .mockResolvedValueOnce(createJsonResponse(updatedPolicy))
      .mockResolvedValueOnce(createJsonResponse(updatedPolicy))

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Edit details/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Edit details/i }))
    const nameInput = screen.getByLabelText('Name')
    await userEvent.clear(nameInput)
    await userEvent.type(nameInput, 'Updated Safety Policy')
    await userEvent.click(screen.getByRole('button', { name: /^Save$/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/policies/policy-1/?organization_id=org-1'),
        expect.objectContaining({ method: 'PATCH' })
      )
    })

    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(patchCall?.[1]?.body as string)).toMatchObject({
      name: 'Updated Safety Policy',
    })
  })

  it('submits rule deactivation with organization scope', async () => {
    fetchMock.mockImplementation((url, init) => {
      if (init?.method === 'DELETE') {
        return Promise.resolve(createJsonResponse(null, { status: 204 }))
      }
      if (String(url).includes('/api/v1/policies/policy-1/')) {
        return Promise.resolve(
          createJsonResponse({
            ...policyDetail,
            rules: fetchMock.mock.calls.some(([, callInit]) => callInit?.method === 'DELETE')
              ? [{ ...ruleHighRisk, is_active: false }]
              : [ruleHighRisk],
          })
        )
      }
      return Promise.resolve(createJsonResponse(policyDetail))
    })

    renderRoute(<PolicyDetailPage />, {
      path: '/policies/:policyId',
      route: '/policies/policy-1?organization_id=org-1',
    })

    await waitFor(() => {
      expect(screen.getByText('High risk approval')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /^Deactivate$/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/policies/policy-1/rules/rule-1/?organization_id=org-1'),
        expect.objectContaining({ method: 'DELETE' })
      )
    })
  })
})
