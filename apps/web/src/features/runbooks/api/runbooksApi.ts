import { apiRequest } from '../../../shared/api/client'
import type { CreateRunbookInput, Runbook, RunbookDetail } from '../types'

export function listRunbooks() {
  return apiRequest<Runbook[]>('/api/v1/runbooks/')
}

export function getRunbook(runbookId: string) {
  return apiRequest<RunbookDetail>(`/api/v1/runbooks/${runbookId}/`)
}

export function createRunbook(input: CreateRunbookInput) {
  return apiRequest<RunbookDetail>('/api/v1/runbooks/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
