import { apiRequest } from '../../../shared/api/client'

export interface RunnerPool {
  id: string
  key: string
  name: string
  environment: string
  network_zone: string
  status: 'active' | 'draining' | 'disabled'
  max_concurrent_executions: number
  labels: Record<string, string>
  capabilities: string[]
}

export interface Runner {
  id: string
  pool_id: string
  display_name: string
  status: 'registered' | 'active' | 'draining' | 'offline' | 'disabled' | 'revoked'
  runner_version: string
  hostname: string
  last_heartbeat_at: string | null
  last_seen_at: string | null
}

export const fetchRunnerPools = (orgId: string) =>
  apiRequest<{ results: RunnerPool[] }>(`/api/v1/runner-pools/?organization_id=${orgId}`)

export const fetchRunner = (id: string) =>
  apiRequest<Runner>(`/api/v1/runners/${id}/`)

export const fetchRunners = (orgId: string) =>
  apiRequest<{ results: Runner[] }>(`/api/v1/runners/?organization_id=${orgId}`)

export const drainPool = (id: string) =>
  apiRequest(`/api/v1/runner-pools/${id}/drain/`, { method: 'POST' })

export const disablePool = (id: string) =>
  apiRequest(`/api/v1/runner-pools/${id}/disable/`, { method: 'POST' })

export const drainRunner = (id: string) =>
  apiRequest(`/api/v1/runners/${id}/drain/`, { method: 'POST' })

export const revokeRunner = (id: string) =>
  apiRequest(`/api/v1/runners/${id}/revoke/`, { method: 'POST' })
