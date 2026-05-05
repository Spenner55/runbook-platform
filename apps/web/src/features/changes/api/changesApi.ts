import { apiRequest } from '../../../shared/api/client'
import type {
  ChangeRecord,
  ChangeWindow,
  CreateChangeInput,
  DispatchEligibilityCheck,
  OperationProfile,
  PatchWindowInput,
} from '../types'

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

export function patchWindow(changeId: string, input: PatchWindowInput) {
  return apiRequest<ChangeWindow>(`/api/v1/changes/${changeId}/window/`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function runPreflight(changeId: string) {
  return apiRequest<DispatchEligibilityCheck>(`/api/v1/changes/${changeId}/preflight/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function getLatestPreflight(changeId: string) {
  return apiRequest<DispatchEligibilityCheck>(`/api/v1/changes/${changeId}/preflight/latest/`)
}

export function dispatchChange(changeId: string) {
  return apiRequest<ChangeRecord>(`/api/v1/changes/${changeId}/dispatch/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}
