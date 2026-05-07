import { apiRequest } from '../../../shared/api/client'
import { buildApiUrl } from '../../../shared/api/env'
import {
  getAccessToken,
  getActiveOrganizationId,
} from '../../auth/authTokenStore'
import type {
  CreateEvidenceBundleInput,
  CreateEvidenceExportInput,
  CreateLegalHoldInput,
  EvidenceBundle,
  EvidenceExport,
  LegalHold,
} from '../types'

export function getLatestEvidenceBundle(changeId: string) {
  return apiRequest<EvidenceBundle>(
    `/api/v1/changes/${changeId}/evidence-bundles/latest/`
  )
}

export function createEvidenceBundle(changeId: string, input: CreateEvidenceBundleInput) {
  return apiRequest<EvidenceBundle>(`/api/v1/changes/${changeId}/evidence-bundles/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function sealEvidenceBundle(bundleId: string) {
  return apiRequest<EvidenceBundle>(`/api/v1/evidence-bundles/${bundleId}/seal/`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function createEvidenceExport(bundleId: string, input: CreateEvidenceExportInput) {
  return apiRequest<EvidenceExport>(`/api/v1/evidence-bundles/${bundleId}/exports/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createLegalHold(bundleId: string, input: CreateLegalHoldInput) {
  return apiRequest<LegalHold>(`/api/v1/evidence-bundles/${bundleId}/legal-hold/`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function triggerExportDownload(exportId: string, filename?: string): Promise<void> {
  const url = buildApiUrl(`/api/v1/evidence-exports/${exportId}/download/`)
  const headers = new Headers({ Accept: 'application/zip' })

  const token = getAccessToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const orgId = getActiveOrganizationId()
  if (orgId) {
    headers.set('X-Organization-Id', orgId)
  }

  const response = await fetch(url, { method: 'GET', credentials: 'include', headers })

  if (!response.ok) {
    throw new Error(`Download failed with status ${response.status}.`)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename ?? `evidence-export-${exportId}.zip`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(objectUrl)
}
