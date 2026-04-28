import { apiRequest } from '../../../shared/api/client'
import type { AuditEventListResponse } from '../types'

function appendOptionalParam(params: URLSearchParams, key: string, value: string | number | undefined) {
  if (value !== undefined && value !== '') {
    params.set(key, String(value))
  }
}

export function getObjectAuditTrail(input: {
  organizationId: string
  objectType: string
  objectId: string
  limit?: number
  offset?: number
}) {
  const params = new URLSearchParams({
    organization_id: input.organizationId,
    object_type: input.objectType,
    object_id: input.objectId,
  })
  appendOptionalParam(params, 'limit', input.limit)
  appendOptionalParam(params, 'offset', input.offset)
  return apiRequest<AuditEventListResponse>(`/api/v1/audit/?${params.toString()}`)
}

export function getExecutionAuditTrail(input: {
  executionId: string
  organizationId: string
  limit?: number
  offset?: number
}) {
  const params = new URLSearchParams({
    organization_id: input.organizationId,
  })
  appendOptionalParam(params, 'limit', input.limit)
  appendOptionalParam(params, 'offset', input.offset)
  return apiRequest<AuditEventListResponse>(
    `/api/v1/executions/${input.executionId}/audit/?${params.toString()}`
  )
}
