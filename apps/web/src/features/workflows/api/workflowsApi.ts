import { apiRequest } from '../../../shared/api/client'
import type { CreateWorkflowInput, WorkflowDetail } from '../types'

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
