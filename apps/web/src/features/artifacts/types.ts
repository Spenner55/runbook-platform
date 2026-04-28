export interface Artifact {
  id: string
  execution_id: string
  step_id: string | null
  kind: 'stdout' | 'stderr' | 'file' | 'report' | 'diagnostic'
  name: string
  mime_type: string
  size_bytes: number
  checksum_sha256: string
  uploaded_by_runner_id: string
  uploaded_at: string
  metadata: Record<string, unknown>
}

export interface ArtifactDownload {
  artifact_id: string
  download_url: string
  expires_at: string
  method: 'GET'
  content_disposition: 'attachment' | 'inline'
  filename: string
}

export interface PaginatedArtifacts {
  count: number
  next: number | null
  previous: number | null
  results: Artifact[]
}
