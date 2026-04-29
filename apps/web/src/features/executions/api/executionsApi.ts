import { apiRequest } from '../../../shared/api/client'
import type { CreateExecutionInput, ExecutionDetail, ExecutionSummary } from '../types'

export function listExecutions() {
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
