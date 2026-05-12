import { apiRequest } from '../../../shared/api/client'
import type { CreateExecutionInput, ExecutionDetail, ExecutionSummary } from '../types'

export function listExecutions(statuses?: string[]) {
  if (statuses?.length) {
    const params = statuses.map((s) => `status=${encodeURIComponent(s)}`).join('&')
    return apiRequest<ExecutionSummary[]>(`/api/v1/executions/?${params}`)
  }
  return apiRequest<ExecutionSummary[]>('/api/v1/executions/')
}

export function createExecution(input: CreateExecutionInput) {
  return apiRequest<ExecutionDetail>('/api/v1/executions/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getExecution(executionId: string) {
  return apiRequest<ExecutionDetail>(`/api/v1/executions/${executionId}/`)
}
