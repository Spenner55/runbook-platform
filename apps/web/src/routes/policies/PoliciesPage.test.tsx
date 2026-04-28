import { screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PoliciesPage } from './PoliciesPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const policy1 = {
  id: 'policy-1',
  organization_id: 'org-1',
  name: 'Production Safety Policy',
  description: 'Require approval for high-risk steps',
  is_active: true,
  rule_count: 2,
  created_at: '2026-04-01T10:00:00Z',
  updated_at: '2026-04-15T12:00:00Z',
}

const policy2 = {
  id: 'policy-2',
  organization_id: 'org-1',
  name: 'Dev Permissive Policy',
  description: '',
  is_active: false,
  rule_count: 0,
  created_at: '2026-04-02T10:00:00Z',
  updated_at: '2026-04-02T10:00:00Z',
}

describe('PoliciesPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows prompt when no org id is entered', () => {
    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    expect(screen.getByText(/Enter an organization ID/i)).toBeInTheDocument()
  })

  it('fetches and renders policy list after entering org id', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [policy1, policy2] }))

    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByText('Production Safety Policy')).toBeInTheDocument()
    })

    expect(screen.getByText('Dev Permissive Policy')).toBeInTheDocument()
    expect(screen.getByText('Require approval for high-risk steps')).toBeInTheDocument()
    expect(screen.getByText(/2 rules/i)).toBeInTheDocument()
  })

  it('renders active/inactive status pills', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [policy1, policy2] }))

    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByText('active')).toBeInTheDocument()
    })

    expect(screen.getByText('inactive')).toBeInTheDocument()
  })

  it('shows create policy form when Create policy button is clicked', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create policy/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Create policy/i }))

    expect(screen.getByLabelText(/Policy name/i)).toBeInTheDocument()
  })

  it('submits create policy form and refetches', async () => {
    const newPolicy = { ...policy1, id: 'policy-new', name: 'New Policy', rule_count: 0 }

    fetchMock.mockImplementation((url, init) => {
      if (init && (init as RequestInit).method === 'POST') {
        return Promise.resolve(createJsonResponse(newPolicy))
      }
      return Promise.resolve(createJsonResponse({ results: [policy1] }))
    })

    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create policy/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Create policy/i }))
    await userEvent.type(screen.getByLabelText(/Policy name/i), 'New Policy')
    await userEvent.click(screen.getByRole('button', { name: /^Create policy$/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/policies/'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })

  it('renders error banner on API failure', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ detail: 'Forbidden' }, { status: 403 }))

    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByText(/Forbidden/i)).toBeInTheDocument()
    })
  })

  it('shows empty state when no policies found', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<PoliciesPage />, { path: '/policies', route: '/policies' })

    await userEvent.type(screen.getByLabelText(/Organization ID/i), 'org-1')

    await waitFor(() => {
      expect(screen.getByText(/No policies found/i)).toBeInTheDocument()
    })
  })
})
