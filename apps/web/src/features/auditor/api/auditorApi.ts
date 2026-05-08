import { apiRequest } from '../../../shared/api/client'
import type {
  AuditChangeDetail,
  AuditChangeSearchFilters,
  AuditorAccessGrant,
  CreateAuditorAccessGrantInput,
  PaginatedAuditChanges,
} from '../types'

function buildQuery(filters: AuditChangeSearchFilters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      params.set(key, String(value))
    }
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function searchAuditChanges(filters: AuditChangeSearchFilters = {}) {
  return apiRequest<PaginatedAuditChanges>(`/api/v1/audit/changes/${buildQuery(filters)}`)
}

export function getAuditChangeDetail(changeId: string) {
  return apiRequest<AuditChangeDetail>(`/api/v1/audit/changes/${changeId}/`)
}

export function listAuditorAccessGrants() {
  return apiRequest<{ results: AuditorAccessGrant[] }>('/api/v1/audit/access-grants/').then(
    (response) => response.results
  )
}

export function createAuditorAccessGrant(input: CreateAuditorAccessGrantInput) {
  return apiRequest<AuditorAccessGrant>('/api/v1/audit/access-grants/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function revokeAuditorAccessGrant(grantId: string) {
  return apiRequest<AuditorAccessGrant>(`/api/v1/audit/access-grants/${grantId}/revoke/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}
