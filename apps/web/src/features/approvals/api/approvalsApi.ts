import { apiRequest } from '../../../shared/api/client'
import type { ApprovalRequest, DecideApprovalInput } from '../types'

export interface ListApprovalsParams {
  organization_id: string
  status?: string
  execution_id?: string
}

export function listApprovals(params: ListApprovalsParams) {
  const query = new URLSearchParams({ organization_id: params.organization_id })
  if (params.status) query.set('status', params.status)
  if (params.execution_id) query.set('execution_id', params.execution_id)
  return apiRequest<{ results: ApprovalRequest[] }>(`/api/v1/approvals/?${query}`)
}

export function getApproval(approvalId: string) {
  return apiRequest<ApprovalRequest>(`/api/v1/approvals/${approvalId}/`)
}

export function decideApproval(approvalId: string, input: DecideApprovalInput) {
  return apiRequest<ApprovalRequest>(`/api/v1/approvals/${approvalId}/decide/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
