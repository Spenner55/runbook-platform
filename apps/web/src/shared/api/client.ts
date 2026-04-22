import { buildApiUrl } from './env'

type ErrorPayload = Record<string, unknown>

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

  const detail = (data as ErrorPayload).detail
  return typeof detail === 'string' ? detail : undefined
}

function getFieldMessage(
  data: unknown,
  fieldName: string,
): string | undefined {
  if (!data || typeof data !== 'object') {
    return undefined
  }

  const value = (data as ErrorPayload)[fieldName]
  if (typeof value === 'string') {
    return value
  }
  if (Array.isArray(value)) {
    return value
      .filter((item): item is string => typeof item === 'string')
      .join(', ')
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

export function getApiFieldError(
  error: unknown,
  fieldName: string,
): string | undefined {
  if (!(error instanceof ApiError)) {
    return undefined
  }
  return getFieldMessage(error.data, fieldName)
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')

  const hasBody = init.body !== undefined && init.body !== null
  if (hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers,
  })

  const contentType = response.headers.get('content-type') ?? ''
  const isJson = contentType.includes('application/json')
  const data = isJson ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(
      getDetailMessage(data) ?? `Request failed with status ${response.status}.`,
      response.status,
      data,
    )
  }

  return data as T
}
