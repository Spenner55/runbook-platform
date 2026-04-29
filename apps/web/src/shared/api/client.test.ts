import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setAccessToken, setActiveOrganizationId } from '../../features/auth/authTokenStore'
import { createJsonResponse } from '../../test/fetchResponse'
import { apiRequest } from './client'

describe('apiRequest', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    setAccessToken(null)
    setActiveOrganizationId(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
    setAccessToken(null)
    setActiveOrganizationId(null)
  })

  it('uses the active organization header when the request has no organization id', async () => {
    setActiveOrganizationId('active-org')
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))

    await apiRequest('/api/v1/runbooks/')

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers
    expect(headers.get('X-Organization-Id')).toBe('active-org')
  })

  it('sends the in-memory access token and organization header', async () => {
    setAccessToken('access-token')
    fetchMock.mockResolvedValueOnce(createJsonResponse({ results: [] }))

    await apiRequest('/api/v1/policies/?organization_id=org-1')

    const init = fetchMock.mock.calls[0]?.[1]
    expect(init?.credentials).toBe('include')
    expect(init?.headers).toBeInstanceOf(Headers)
    const headers = init?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer access-token')
    expect(headers.get('X-Organization-Id')).toBe('org-1')
  })

  it('refreshes once and retries a request after a 401', async () => {
    fetchMock
      .mockResolvedValueOnce(createJsonResponse({ detail: 'Token expired.' }, { status: 401 }))
      .mockResolvedValueOnce(createJsonResponse({ access: 'fresh-token' }))
      .mockResolvedValueOnce(createJsonResponse({ ok: true }))

    await expect(apiRequest('/api/v1/organizations/')).resolves.toEqual({ ok: true })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/api/v1/auth/refresh/')
    const retryHeaders = fetchMock.mock.calls[2]?.[1]?.headers as Headers
    expect(retryHeaders.get('Authorization')).toBe('Bearer fresh-token')
  })

  it('blocks browser requests to internal runner endpoints', async () => {
    await expect(apiRequest('/api/v1/internal/executions/claim-next/')).rejects.toThrow(
      'Browser requests to internal API endpoints are not allowed.'
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
