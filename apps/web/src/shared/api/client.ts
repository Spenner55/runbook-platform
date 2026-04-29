import { buildApiUrl } from './env'
import {
  getAccessToken,
  getActiveOrganizationId,
  setAccessToken,
} from '../../features/auth/authTokenStore'
import type { RefreshResponse } from '../../features/auth/types'

// Frontend HTTP stays behind this Django API client. Do not add direct calls to
// the FastAPI AI service, runner service, or `/api/v1/internal/` endpoints here.
type ErrorPayload = Record<string, unknown>

interface ApiRequestInit extends RequestInit {
  organizationId?: string
  skipAuthRefresh?: boolean
}

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(message: string, status: number, data: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

function getDetailMessage(data: unknown): string | undefined {
  if (!data || typeof data !== 'object') {
    return undefined
  }

  const errors = (data as ErrorPayload).errors
  if (Array.isArray(errors) && errors.length > 0) {
    const first = errors[0]
    if (first && typeof first === 'object') {
      const detail = (first as ErrorPayload).detail
      if (typeof detail === 'string') {
        return detail
      }
    }
  }

  const detail = (data as ErrorPayload).detail
  return typeof detail === 'string' ? detail : undefined
}

function getFieldMessage(data: unknown, fieldName: string): string | undefined {
  if (!data || typeof data !== 'object') {
    return undefined
  }

  const value = (data as ErrorPayload)[fieldName]
  if (typeof value === 'string') {
    return value
  }
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string').join(', ')
  }
  return undefined
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return getDetailMessage(error.data) ?? error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Request failed.'
}

export function getApiFieldError(error: unknown, fieldName: string): string | undefined {
  if (!(error instanceof ApiError)) {
    return undefined
  }
  return getFieldMessage(error.data, fieldName)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function getOrganizationIdFromBody(body: BodyInit | null | undefined) {
  if (typeof body !== 'string') {
    return undefined
  }

  try {
    const data = JSON.parse(body) as unknown
    if (!isRecord(data)) {
      return undefined
    }
    const organizationId = data.organization_id
    return typeof organizationId === 'string' ? organizationId : undefined
  } catch {
    return undefined
  }
}

function getOrganizationIdFromPath(path: string) {
  const queryStart = path.indexOf('?')
  if (queryStart === -1) {
    return undefined
  }

  const params = new URLSearchParams(path.slice(queryStart))
  return params.get('organization_id') ?? undefined
}

let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = fetch(buildApiUrl('/api/v1/auth/refresh/'), {
      method: 'POST',
      credentials: 'include',
      headers: {
        Accept: 'application/json',
      },
    })
      .then(async (response) => {
        if (!response.ok) {
          setAccessToken(null)
          return null
        }

        const contentType = response.headers.get('content-type') ?? ''
        if (!contentType.includes('application/json')) {
          setAccessToken(null)
          return null
        }

        const data = (await response.json()) as RefreshResponse
        if (!data.access) {
          setAccessToken(null)
          return null
        }

        setAccessToken(data.access)
        return data.access
      })
      .catch(() => {
        setAccessToken(null)
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

function notifyUnauthorized() {
  window.dispatchEvent(new Event('runbook-platform:unauthorized'))
}

async function executeRequest(path: string, init: ApiRequestInit, accessToken: string | null) {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')

  const hasBody = init.body !== undefined && init.body !== null
  if (hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const organizationId =
    init.organizationId ??
    getOrganizationIdFromPath(path) ??
    getOrganizationIdFromBody(init.body) ??
    getActiveOrganizationId()
  if (organizationId) {
    headers.set('X-Organization-Id', organizationId)
  }

  return fetch(buildApiUrl(path), {
    ...init,
    credentials: init.credentials ?? 'include',
    headers,
  })
}

export async function apiRequest<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  if (path.startsWith('/api/v1/internal/')) {
    throw new Error('Browser requests to internal API endpoints are not allowed.')
  }

  const response = await executeRequest(path, init, getAccessToken())

  if (response.status === 401 && !init.skipAuthRefresh) {
    const nextAccessToken = await refreshAccessToken()
    if (nextAccessToken) {
      const retryResponse = await executeRequest(path, init, nextAccessToken)
      if (retryResponse.status === 401) {
        setAccessToken(null)
        notifyUnauthorized()
      }
      return parseApiResponse<T>(retryResponse)
    }

    notifyUnauthorized()
  }

  return parseApiResponse<T>(response)
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') ?? ''
  const isJson = contentType.includes('application/json')
  const data = isJson ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(
      getDetailMessage(data) ?? `Request failed with status ${response.status}.`,
      response.status,
      data
    )
  }

  return data as T
}
