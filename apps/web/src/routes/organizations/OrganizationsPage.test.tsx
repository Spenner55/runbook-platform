import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { OrganizationsPage } from './OrganizationsPage'
import { createJsonResponse } from '../../test/fetchResponse'
import { renderRoute } from '../../test/renderRoute'

describe('OrganizationsPage', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('lists organizations and creates a new one through Django', async () => {
    const organization = {
      id: '9d4fe0a4-5af0-4bc0-9090-0e9d7aeb73c1',
      name: 'Platform Ops',
      slug: 'platform-ops',
      created_at: '2026-04-15T00:00:00Z',
      updated_at: '2026-04-15T00:00:00Z',
    }

    fetchMock
      .mockResolvedValueOnce(createJsonResponse([]))
      .mockResolvedValueOnce(createJsonResponse(organization, { status: 201 }))
      .mockResolvedValueOnce(createJsonResponse([organization]))

    renderRoute(<OrganizationsPage />, {
      path: '/organizations',
      route: '/organizations',
    })

    expect(screen.getByText('Loading organizations…')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Name'), 'Platform Ops')
    await user.type(screen.getByLabelText('Slug'), 'platform-ops')
    await user.click(screen.getByRole('button', { name: 'Create organization' }))

    await waitFor(() => {
      expect(screen.getByText('Platform Ops')).toBeInTheDocument()
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://localhost:8000/api/v1/organizations/',
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'http://localhost:8000/api/v1/organizations/',
      expect.objectContaining({
        body: JSON.stringify({ name: 'Platform Ops', slug: 'platform-ops' }),
        method: 'POST',
      }),
    )
    expect(
      screen.getByRole('link', { name: 'View runbooks' }),
    ).toHaveAttribute(
      'href',
      `/runbooks?organizationId=${organization.id}`,
    )
  })
})
