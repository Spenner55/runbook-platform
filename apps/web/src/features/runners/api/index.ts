import { apiRequest } from '../../../shared/api/client'

export interface CapacitySummary {
  max_concurrent_executions: number
  active_executions: number
  available_capacity: number
}

export interface RunnerPool {
  id: string
  organization_id: string
  key: string
  name: string
  display_name: string
  description: string
  environment: string
  network_zone: string
  status: 'active' | 'draining' | 'disabled'
  max_concurrent_executions: number
  max_concurrent_per_target: number
  default_for_non_change_executions: boolean
  labels: Record<string, string>
  capabilities: string[]
  drain_requested_at: string | null
  disabled_at: string | null
  active_runner_count: number
  active_execution_count: number
  capacity_summary: CapacitySummary
  created_at: string
}

export interface Runner {
  id: string
  organization_id: string
  pool_id: string
  display_name: string
  status: 'registered' | 'active' | 'draining' | 'offline' | 'disabled' | 'revoked'
  runner_version: string
  hostname: string
  last_heartbeat_at: string | null
  last_seen_at: string | null
  drain_requested_at: string | null
  disabled_at: string | null
  revoked_at: string | null
  active_execution_count: number
  created_at: string
}

export interface TargetConnectivityRoute {
  id: string
  organization_id: string
  environment: string
  target_type: string
  normalized_identifier_pattern: string
  pool_id: string
  required_labels: Record<string, string>
  required_capabilities: string[]
  priority: number
  is_active: boolean
  created_at: string
}

export interface RunnerEligibility {
  eligible: boolean
  pool_key: string | null
  pool_id: string | null
  pool_status: string | null
  reason: string
  online_runners_count: number
}

export const fetchRunnerPools = (orgId: string) =>
  apiRequest<{ results: RunnerPool[] }>(`/api/v1/runner-pools/?organization_id=${orgId}`)

export const fetchRunnerPool = (id: string) =>
  apiRequest<RunnerPool>(`/api/v1/runner-pools/${id}/`)

export const fetchRunner = (id: string) =>
  apiRequest<Runner>(`/api/v1/runners/${id}/`)

export const fetchRunners = (orgId: string) =>
  apiRequest<{ results: Runner[] }>(`/api/v1/runners/?organization_id=${orgId}`)

export const drainPool = (id: string) =>
  apiRequest(`/api/v1/runner-pools/${id}/drain/`, { method: 'POST' })

export const disablePool = (id: string) =>
  apiRequest(`/api/v1/runner-pools/${id}/disable/`, { method: 'POST' })

export const reactivatePool = (id: string) =>
  apiRequest(`/api/v1/runner-pools/${id}/reactivate/`, { method: 'POST' })

export const drainRunner = (id: string) =>
  apiRequest(`/api/v1/runners/${id}/drain/`, { method: 'POST' })

export const disableRunner = (id: string) =>
  apiRequest(`/api/v1/runners/${id}/disable/`, { method: 'POST' })

export const revokeRunner = (id: string) =>
  apiRequest(`/api/v1/runners/${id}/revoke/`, { method: 'POST' })

export const fetchTargetConnectivityRoutes = (orgId: string) =>
  apiRequest<{ results: TargetConnectivityRoute[] }>(
    `/api/v1/target-connectivity-routes/?organization_id=${orgId}`
  )

export const deactivateRoute = (id: string) =>
  apiRequest(`/api/v1/target-connectivity-routes/${id}/deactivate/`, { method: 'POST' })

export const reactivateRoute = (id: string) =>
  apiRequest(`/api/v1/target-connectivity-routes/${id}/reactivate/`, { method: 'POST' })

export const fetchRunnerEligibility = (changeId: string) =>
  apiRequest<RunnerEligibility>(`/api/v1/changes/${changeId}/runner-eligibility/`, {
    method: 'POST',
  })
