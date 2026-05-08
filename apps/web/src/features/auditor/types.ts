export interface AuditChangeSearchFilters {
  service?: string
  target?: string
  risk?: string
  status?: string
  change_type?: string
  bundle_status?: string
  control_id?: string
  coverage_status?: string
  external_system?: string
  has_exception?: string
  start_date?: string
  end_date?: string
  approver?: string
  executor?: string
  ordering?: string
  limit?: string
  offset?: string
}

export interface AuditTargetProjection {
  id: string
  label: string
  type: string
  identifier: string
}

export interface AuditBundleProjection {
  id: string
  status: string
  completeness_status: string
  version: number
  manifest_sha256: string
  content_sha256: string
}

export interface AuditExternalReferenceSummary {
  system: string
  reference_type: string
  external_key: string
  snapshot_status: string
}

export interface AuditChangeSummary {
  id: string
  title: string
  status: string
  risk: string
  change_type: string
  targets: AuditTargetProjection[]
  submitted_at: string | null
  audit_date: string
  audit_date_basis: string
  approved_at: string | null
  closed_at: string | null
  has_exception: boolean
  bundle: AuditBundleProjection | null
  external_references: AuditExternalReferenceSummary[]
  coverage_summary: Record<string, Record<string, number>>
}

export interface ExternalChangeReference {
  id: string
  change_record_id: string
  system: string
  reference_type: string
  external_id: string
  external_key: string
  display_label: string
  external_url: string
  snapshot: Record<string, unknown>
  snapshot_sha256: string
  snapshot_source: string
  snapshot_status: string
  snapshot_taken_at: string | null
  last_refresh_attempted_at: string | null
  last_refresh_error_code: string
  linked_by_id: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface ChangeControlCoverage {
  id: string
  evidence_bundle_id: string
  mapping_profile_id: string
  standard: string
  control_id: string
  control_title: string
  coverage_status: string
  matched_sections: string[]
  missing_sections: string[]
  evidence_paths: string[]
  coverage_fingerprint_sha256: string
  computed_at: string
  computed_by_id: string | null
}

export interface AuditChangeDetail extends AuditChangeSummary {
  summary: string
  justification: string
  external_references: ExternalChangeReference[]
  control_coverage: ChangeControlCoverage[]
  created_at: string
  updated_at: string
}

export interface PaginatedAuditChanges {
  count: number
  next: string | null
  previous: string | null
  meta?: {
    date_basis?: string
    date_filter_fields?: string[]
  }
  results: AuditChangeSummary[]
}

export interface AuditorAccessGrant {
  id: string
  user_id: string
  status: string
  scope: Record<string, unknown>
  reason: string
  starts_at: string | null
  expires_at: string | null
  revoked_at: string | null
  created_by_id: string | null
  revoked_by_id: string | null
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface CreateAuditorAccessGrantInput {
  user_id: string
  scope: Record<string, unknown>
  reason?: string
  starts_at?: string
  expires_at?: string
}
