import { apiRequest } from '../../../shared/api/client'
import type { ArtifactDownload, PaginatedArtifacts } from '../types'

export interface ListArtifactsFilters {
  step_id?: string
  kind?: string
  limit?: number
  offset?: number
}

export function listExecutionArtifacts(
  executionId: string,
  filters: ListArtifactsFilters = {},
): Promise<PaginatedArtifacts> {
  const params = new URLSearchParams()
  if (filters.step_id) params.set('step_id', filters.step_id)
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.limit != null) params.set('limit', String(filters.limit))
  if (filters.offset != null) params.set('offset', String(filters.offset))
  const query = params.toString()
  return apiRequest<PaginatedArtifacts>(
    `/api/v1/executions/${executionId}/artifacts/${query ? `?${query}` : ''}`,
  )
}

export function createArtifactDownloadUrl(artifactId: string): Promise<ArtifactDownload> {
  return apiRequest<ArtifactDownload>(`/api/v1/artifacts/${artifactId}/download/`, {
    method: 'POST',
  })
}
