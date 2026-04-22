import { apiRequest } from '../../../shared/api/client'
import type { CreateExecutionInput, ExecutionDetail } from '../types'

export function createExecution(input: CreateExecutionInput) {
  return apiRequest<ExecutionDetail>('/api/v1/executions/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getExecution(executionId: string) {
  return apiRequest<ExecutionDetail>(`/api/v1/executions/${executionId}/`)
}
