export type BundleStatus = 'compiling' | 'sealed' | 'invalidated'
export type CompletenessStatus = 'complete' | 'incomplete' | 'invalid'
export type ExportStatus = 'creating' | 'ready' | 'failed' | 'expired'
export type LegalHoldStatus = 'active' | 'released'

export interface CompletenessItemEntry {
  item_type: string
  item_key: string
  canonical_path: string
  required: boolean
  present: boolean
  valid: boolean
  missing_reason: string
  validation_errors: unknown[]
}

export interface CompletenessSection {
  section: string
  status: CompletenessStatus
  items: CompletenessItemEntry[]
  required_count: number
  present_count: number
  invalid_count: number
}

export interface CompletenessReport {
  sections: CompletenessSection[]
  required_total: number
  present_total: number
  invalid_total: number
  missing_total: number
}

export interface EvidenceBundle {
  id: string
  change_record_id: string
  version: number
  status: BundleStatus
  completeness_status: CompletenessStatus
  is_current: boolean
  source_snapshot_sha256: string
  completeness_report: CompletenessReport | Record<string, unknown>
  manifest_sha256: string
  payload_checksums_sha256: string
  content_sha256: string
  content_size_bytes: number | null
  compiled_at: string
  sealed_at: string | null
  invalidated_at: string | null
  invalidation_reason: string
  retention_expires_at: string | null
  legal_hold_active: boolean
  storage_deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface ManifestEntry {
  path: string
  item_type: string
  media_type: string
  size_bytes: number
  sha256: string
  required: boolean
  source_refs: unknown[]
}

export interface ManifestBundle {
  id: string
  version: number
  status: string
  completeness_status: string
  compiled_at: string
  sealed_at: string | null
}

export interface ManifestChange {
  id: string
  status: string
  request_snapshot_sha256: string
  requested_inputs_sha256: string
}

export interface Manifest {
  manifest_schema_version: string
  package_type: string
  bundle: ManifestBundle
  change: ManifestChange
  source: {
    source_snapshot_sha256: string
    source_cutoff_at: string
    source_high_watermark: Record<string, unknown>
  }
  algorithms: {
    content_hash: string
    manifest_hash: string
    zip_method: string
  }
  entries: ManifestEntry[]
}

export interface EvidenceExport {
  id: string
  bundle_id: string
  status: ExportStatus
  redaction_policy_id: string | null
  requested_by_id: string | null
  requested_at: string
  ready_at: string | null
  expires_at: string | null
  source_manifest_sha256: string
  source_bundle_content_sha256: string
  manifest_sha256: string
  content_sha256: string
  content_size_bytes: number | null
  receipt_sha256: string
  redaction_summary: Record<string, unknown>
  failure_code: string
  storage_deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface LegalHold {
  id: string
  status: LegalHoldStatus
  change_record_id: string
  evidence_bundle_id: string | null
  reason: string
  external_reference: string
  placed_by_id: string | null
  placed_at: string
  released_at: string | null
  release_reason: string
  created_at: string
  updated_at: string
}

export interface RedactionPolicy {
  id: string
  name: string
  description: string
  is_active: boolean
  is_default: boolean
}

// Request inputs

export interface CreateEvidenceBundleInput {
  force_new_version?: boolean
}

export interface CreateEvidenceExportInput {
  redaction_policy_id?: string | null
}

export interface CreateLegalHoldInput {
  reason: string
  external_reference?: string
}
