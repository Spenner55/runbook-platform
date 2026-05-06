import { screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FreezeRulesPage } from './FreezeRulesPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

const adminUser = {
  id: 'user-1',
  email: 'admin@example.com',
  first_name: 'Admin',
  last_name: 'User',
  full_name: 'Admin User',
  is_staff: false,
  created_at: '2026-01-01T00:00:00Z',
  memberships: [
    {
      id: 'mem-1',
      role: 'admin' as const,
      organization: { id: 'org-1', name: 'Acme', slug: 'acme' },
    },
  ],
  active_organization_id: 'org-1',
}

const viewerUser = {
  ...adminUser,
  memberships: [
    {
      id: 'mem-1',
      role: 'viewer' as const,
      organization: { id: 'org-1', name: 'Acme', slug: 'acme' },
    },
  ],
}

const activeRule = {
  id: 'rule-1',
  name: 'Holiday Freeze',
  description: 'No deployments during holidays',
  is_active: true,
  behavior: 'block',
  starts_at: '2026-12-24T00:00:00Z',
  ends_at: '2026-12-26T23:59:59Z',
  scope_type: 'all_production',
  target_type: '',
  target_identifier: '',
  requires_exception_reference: false,
  created_at: '2026-12-01T10:00:00Z',
  updated_at: '2026-12-01T10:00:00Z',
}

const inactiveRule = {
  id: 'rule-2',
  name: 'Old Freeze',
  description: '',
  is_active: false,
  behavior: 'allow_with_exception',
  starts_at: '2026-01-01T00:00:00Z',
  ends_at: '2026-01-02T00:00:00Z',
  scope_type: 'target_type',
  target_type: 'database',
  target_identifier: '',
  requires_exception_reference: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('FreezeRulesPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('shows prompt when no active organization is selected', () => {
    renderRoute(<FreezeRulesPage />, { path: '/freeze-rules', route: '/freeze-rules' })

    expect(screen.getByText(/No active organization selected/i)).toBeInTheDocument()
  })

  it('fetches and renders freeze rule list', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [activeRule, inactiveRule] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Holiday Freeze')).toBeInTheDocument()
    })

    expect(screen.getByText('Old Freeze')).toBeInTheDocument()
    expect(screen.getByText(/No deployments during holidays/i)).toBeInTheDocument()
  })

  it('renders active/inactive status pills', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [activeRule, inactiveRule] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('active')).toBeInTheDocument()
    })

    expect(screen.getByText('inactive')).toBeInTheDocument()
  })

  it('shows empty state when no rules found', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText(/No freeze rules found/i)).toBeInTheDocument()
    })
  })

  it('renders error banner on API failure', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ detail: 'Forbidden' }, { status: 403 }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText(/Forbidden/i)).toBeInTheDocument()
    })
  })

  it('shows Create freeze rule button for admin users', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: adminUser },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create freeze rule/i })).toBeInTheDocument()
    })
  })

  it('hides Create freeze rule button for viewer users', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: viewerUser },
    })

    await waitFor(() => {
      expect(screen.getByText(/No freeze rules found/i)).toBeInTheDocument()
    })

    expect(screen.queryByRole('button', { name: /Create freeze rule/i })).not.toBeInTheDocument()
  })

  it('shows create form when Create freeze rule button is clicked', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: adminUser },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create freeze rule/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Create freeze rule/i }))

    expect(screen.getByLabelText(/^Name$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Behavior/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Scope/i)).toBeInTheDocument()
  })

  it('submits create form and posts to the API', async () => {
    const newRule = { ...activeRule, id: 'rule-new', name: 'Black Friday Freeze' }

    fetchMock.mockImplementation((_url, init) => {
      if (init?.method === 'POST') {
        return Promise.resolve(createJsonResponse(newRule, { status: 201 }))
      }
      return Promise.resolve(createJsonResponse({ results: [] }))
    })

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: adminUser },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create freeze rule/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Create freeze rule/i }))
    await userEvent.type(screen.getByLabelText(/^Name$/i), 'Black Friday Freeze')
    await userEvent.type(screen.getByLabelText(/Starts at/i), '2026-11-27T00:00')
    await userEvent.type(screen.getByLabelText(/Ends at/i), '2026-11-28T23:59')
    await userEvent.click(screen.getByRole('button', { name: /^Create freeze rule$/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/freeze-rules/'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })

  it('shows Deactivate button only for admin on active rules', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [activeRule] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: adminUser },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Deactivate/i })).toBeInTheDocument()
    })
  })

  it('hides Deactivate button for viewer users', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [activeRule] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: viewerUser },
    })

    await waitFor(() => {
      expect(screen.getByText('Holiday Freeze')).toBeInTheDocument()
    })

    expect(screen.queryByRole('button', { name: /Deactivate/i })).not.toBeInTheDocument()
  })

  it('calls deactivate endpoint when Deactivate is clicked', async () => {
    fetchMock.mockImplementation((_url, init) => {
      if (init?.method === 'POST') {
        return Promise.resolve(createJsonResponse({ ...activeRule, is_active: false }))
      }
      return Promise.resolve(createJsonResponse({ results: [activeRule] }))
    })

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1', user: adminUser },
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Deactivate/i })).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: /Deactivate/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/freeze-rules/rule-1/deactivate/'),
        expect.objectContaining({ method: 'POST' })
      )
    })
  })

  it('displays scope and behavior details for each rule', async () => {
    fetchMock.mockResolvedValue(createJsonResponse({ results: [activeRule, inactiveRule] }))

    renderRoute(<FreezeRulesPage />, {
      path: '/freeze-rules',
      route: '/freeze-rules',
      auth: { activeOrganizationId: 'org-1' },
    })

    await waitFor(() => {
      expect(screen.getByText('Holiday Freeze')).toBeInTheDocument()
    })

    expect(screen.getByText(/Allow with exception/i)).toBeInTheDocument()
    expect(screen.getByText(/All production/i)).toBeInTheDocument()
    expect(screen.getByText(/database/i)).toBeInTheDocument()
    expect(screen.getByText(/Exception reference required/i)).toBeInTheDocument()
  })
})
