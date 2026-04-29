import { apiRequest } from '../../../shared/api/client'
import type { CreateWorkflowInput, WorkflowDetail, WorkflowSummary } from '../types'

export function listWorkflows() {
  return apiRequest<WorkflowSummary[]>('/api/v1/workflows/')
}

export function createWorkflow(input: CreateWorkflowInput) {
  return apiRequest<WorkflowDetail>('/api/v1/workflows/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getWorkflow(workflowId: string) {
  return apiRequest<WorkflowDetail>(`/api/v1/workflows/${workflowId}/`)
}

export function publishWorkflow(workflowId: string) {
  return apiRequest<WorkflowDetail>(`/api/v1/workflows/${workflowId}/publish/`, {
    method: 'POST',
  })
}

export function acceptWorkflowReview(workflowId: string) {
  return apiRequest<WorkflowDetail>(`/api/v1/workflows/${workflowId}/accept-review/`, {
    method: 'POST',
  })
}

export function rejectWorkflowReview(workflowId: string) {
  return apiRequest<WorkflowDetail>(`/api/v1/workflows/${workflowId}/reject-review/`, {
    method: 'POST',
  })
}
