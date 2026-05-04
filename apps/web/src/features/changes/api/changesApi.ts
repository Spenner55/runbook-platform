import { apiRequest } from '../../../shared/api/client'
import type { ChangeRecord, CreateChangeInput, OperationProfile } from '../types'

export function listOperationProfiles() {
  return apiRequest<{ results: OperationProfile[] }>('/api/v1/changes/operation-profiles/').then(
    (r) => r.results
  )
}

export function listChanges() {
  return apiRequest<{ results: ChangeRecord[] }>('/api/v1/changes/', { method: 'GET' })
}

export function createChange(input: CreateChangeInput) {
  return apiRequest<ChangeRecord>('/api/v1/changes/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getChange(changeId: string) {
  return apiRequest<ChangeRecord>(`/api/v1/changes/${changeId}/`)
}

export function submitChange(changeId: string) {
  return apiRequest<ChangeRecord>(`/api/v1/changes/${changeId}/submit/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}
