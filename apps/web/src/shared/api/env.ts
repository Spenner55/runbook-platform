const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

export const apiBaseUrl = rawApiBaseUrl.replace(/\/$/, '')

export function buildApiUrl(path: string) {
  return apiBaseUrl ? `${apiBaseUrl}${path}` : path
}
