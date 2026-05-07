import { apiRequest } from '../../../shared/api/client'
import type {
  ActivateBreakglassInput,
  BreakglassSession,
  ChangeException,
  ChangeRecord,
  ChangeWindow,
  CloseChangeInput,
  ClosureResponse,
  CreateChangeInput,
  CreateExceptionInput,
  DispatchEligibilityCheck,
  OperationProfile,
  PatchWindowInput,
  RetroReview,
  SubmitRetroReviewInput,
  SubmitVerificationResultInput,
  VerificationPlan,
  VerificationResultResponse,
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

export function getVerificationPlan(changeId: string) {
  return apiRequest<VerificationPlan>(`/api/v1/changes/${changeId}/verification-plan/`)
}

export function submitVerificationResult(changeId: string, input: SubmitVerificationResultInput) {
  return apiRequest<VerificationResultResponse>(
    `/api/v1/changes/${changeId}/verification-results/`,
    { method: 'POST', body: JSON.stringify(input) }
  )
}

export function closeChange(changeId: string, input: CloseChangeInput) {
  return apiRequest<ClosureResponse>(`/api/v1/changes/${changeId}/close/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

// ----- Exception APIs -----

export function listExceptions(changeId: string) {
  return apiRequest<{ results: ChangeException[] }>(
    `/api/v1/changes/${changeId}/exceptions/`
  ).then((r) => r.results)
}

export function createException(changeId: string, input: CreateExceptionInput) {
  return apiRequest<ChangeException>(`/api/v1/changes/${changeId}/exceptions/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

// ----- Breakglass APIs -----

export function activateBreakglass(changeId: string, input: ActivateBreakglassInput) {
  return apiRequest<BreakglassSession>(`/api/v1/changes/${changeId}/breakglass/activate/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function endBreakglass(changeId: string, endReason = 'manual_end') {
  return apiRequest<BreakglassSession>(`/api/v1/changes/${changeId}/breakglass/end/`, {
    method: 'POST',
    body: JSON.stringify({ end_reason: endReason }),
  })
}

// ----- Retro-review APIs -----

export function listRetroReviews(changeId: string) {
  return apiRequest<{ results: RetroReview[] }>(
    `/api/v1/changes/${changeId}/retro-reviews/`
  ).then((r) => r.results)
}

export function submitRetroReview(changeId: string, reviewId: string, input: SubmitRetroReviewInput) {
  return apiRequest<RetroReview>(
    `/api/v1/changes/${changeId}/retro-reviews/${reviewId}/submit/`,
    { method: 'POST', body: JSON.stringify(input) }
  )
}

export function listRetroReviewInbox() {
  return apiRequest<{ results: RetroReview[] }>('/api/v1/changes/retro-reviews/inbox/').then(
    (r) => r.results
  )
}
