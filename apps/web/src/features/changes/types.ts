export interface AllowedWorkflow {
  id: string
  name: string
  version: number
}

export interface OperationProfile {
  id: string
  key: string
  name: string
  description: string
  risk_level: string
  requires_approval: boolean
  verification_required: boolean
  allowed_target_types: string[]
  allowed_workflows: AllowedWorkflow[]
}

export interface OperationProfileSummary {
  id: string
  key: string
  name: string
}

export interface ChangeTarget {
  id: string
  position: number
  target_type: string
  target_identifier: string
  display_name: string
  environment: string
}

export interface ApprovalRequestSummary {
  id: string
  status: string
  requested_at: string | null
  expires_at: string | null
}

export interface ExecutionBindingSummary {
  id: string
  execution_id: string
  execution_status: string
  reserved_at: string
  bound_at: string | null
  operation_profile_key: string
  requested_inputs_sha256: string
}

export interface ChangeWindow {
  id: string
  status: string
  starts_at: string
  ends_at: string
  timezone: string
  reason: string
  approved_at: string | null
  opened_at: string | null
  expired_at: string | null
  overrun_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export interface PreflightCheckItem {
  name: string
  ok: boolean
  detail: string
}

export interface PreflightConflict {
  type: string
  target_type: string
  target_identifier: string
  reason: string
}

export interface DispatchEligibilityCheck {
  id: string
  result: string
  checked_at: string
  expires_at: string
  is_stale: boolean
  approved_status_ok: boolean
  policy_pass_ok: boolean
  window_open_ok: boolean
  freeze_conflicts_ok: boolean
  target_locks_ok: boolean
  actor_authorized_ok: boolean
  checks: PreflightCheckItem[]
  conflicts: PreflightConflict[]
  input_snapshot_sha256: string
  window_snapshot_sha256: string
}

export interface PatchWindowInput {
  starts_at: string
  ends_at: string
  timezone?: string
  reason?: string
}

export interface ChangeRecord {
  id: string
  status: string
  title: string
  summary: string
  justification: string
  operation_profile: OperationProfileSummary
  workflow_id: string
  workflow_version_snapshot: number | null
  requested_inputs_sha256: string
  request_snapshot_sha256: string
  operation_profile_key_snapshot: string
  scheduled_for: string | null
  submitted_at: string | null
  approved_at: string | null
  dispatchable_at: string | null
  running_at: string | null
  verification_pending_at: string | null
  closed_at: string | null
  rejected_at: string | null
  canceled_at: string | null
  expired_at: string | null
  terminal_reason: string
  targets: ChangeTarget[]
  approval_request: ApprovalRequestSummary | null
  policy_decision: Record<string, unknown> | null
  execution_binding: ExecutionBindingSummary | null
  window: ChangeWindow | null
  is_emergency?: boolean
  emergency_reason?: string
  retro_review_required?: boolean
  retro_review_due_at?: string | null
  retro_review_blocking_status?: string
  active_breakglass_session?: BreakglassSession | null
  created_at: string
  updated_at: string
}

// ----- Exception types -----

export type ExceptionType =
  | 'freeze_override'
  | 'window_overrun'
  | 'late_verification'
  | 'policy_override'
  | 'missing_artifact'

export type ExceptionStatus =
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'resolved'
  | 'expired'

export interface ChangeException {
  id: string
  change_record_id: string
  exception_type: ExceptionType
  status: ExceptionStatus
  reason: string
  scope_json: Record<string, unknown>
  requested_by_id: string | null
  requested_at: string
  approval_request_id: string | null
  approved_by_id: string | null
  approved_at: string | null
  rejected_at: string | null
  expires_at: string
  resolved_at: string | null
  resolution_note: string
  created_at: string
  updated_at: string
}

export interface CreateExceptionInput {
  exception_type: ExceptionType
  reason: string
  scope_json: Record<string, unknown>
  expires_at: string
}

// ----- Breakglass types -----

export type BreakglassStatus = 'active' | 'ended' | 'expired' | 'revoked'
export type BreakglassReviewStatus = 'pending' | 'submitted' | 'accepted' | 'overdue' | 'blocked'

export interface BreakglassSession {
  id: string
  change_record_id: string
  status: BreakglassStatus
  scope_sha256: string
  reason: string
  activated_by_id: string | null
  started_at: string
  expires_at: string
  ended_at: string | null
  end_reason: string
  review_due_at: string
  review_status: BreakglassReviewStatus
  created_at: string
  updated_at: string
}

export interface ActivateBreakglassInput {
  reason: string
  scope_json: {
    allowed_actions: string[]
    gate_types: string[]
    target_ids: string[]
    [key: string]: unknown
  }
  expires_at: string
}

// ----- Retro-review types -----

export type RetroReviewStatus = 'pending' | 'submitted' | 'superseded'
export type RetroReviewDisposition = 'accepted' | 'needs_remediation' | 'control_failure'

export interface RetroReview {
  id: string
  change_record_id: string
  change_record_title?: string
  breakglass_session_id: string | null
  change_exception_id: string | null
  status: RetroReviewStatus
  disposition: RetroReviewDisposition | ''
  reviewed_by_id: string | null
  reviewed_at: string | null
  due_at: string
  summary: string
  remediation_required: boolean
  remediation_reference: string
  control_failure_category: string
  evidence_json: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface SubmitRetroReviewInput {
  retro_review_id: string
  disposition: RetroReviewDisposition
  summary: string
  remediation_reference?: string
  evidence_json?: Record<string, unknown>
}

export type VerificationCheckType =
  | 'runner_step'
  | 'artifact_presence'
  | 'manual_attestation'
  | 'api_assertion'
  | 'external_reference'

export type VerificationCheckStatus = 'pending' | 'passed' | 'failed' | 'not_applicable'

export type VerificationPlanStatus = 'generated' | 'active' | 'satisfied' | 'failed' | 'canceled'

export type ClosureOutcome = 'success' | 'rolled_back' | 'partial_success' | 'failed' | 'canceled'

export interface VerificationResultSummary {
  id: string
  outcome: 'passed' | 'failed'
  source: 'runner' | 'user' | 'system'
  validated_at: string
}

export interface VerificationCheck {
  id: string
  key: string
  name: string
  description: string
  check_type: VerificationCheckType
  required: boolean
  status: VerificationCheckStatus
  verification_key: string
  last_result: VerificationResultSummary | null
}

export interface UnmetCheckSummary {
  id: string
  key: string
  name: string
  check_type: VerificationCheckType
}

export interface VerificationPlan {
  id: string
  change_record_id: string
  mode: 'automated' | 'manual' | 'mixed'
  status: VerificationPlanStatus
  required_check_count: number
  satisfied_required_count: number
  failed_required_count: number
  checks: VerificationCheck[]
  unmet_required_checks: UnmetCheckSummary[]
}

export interface SubmitVerificationResultInput {
  check_id: string
  outcome: 'passed' | 'failed'
  manual_attestation_text?: string
  external_reference?: string
  verification_key?: string
  observed_value?: Record<string, unknown>
}

export interface VerificationResultResponse {
  id: string
  check_id: string
  outcome: 'passed' | 'failed'
  validation_status: 'accepted' | 'rejected'
  change_status: string
  plan_status: string
  validated_at: string
  unmet_required_checks: UnmetCheckSummary[]
  validation_errors?: unknown[]
}

export interface CloseChangeInput {
  outcome: ClosureOutcome
  summary: string
  independent_reviewer_id?: string
}

export interface ClosureResponse {
  id: string
  change_record_id: string
  outcome: ClosureOutcome
  closed_at: string
  closed_by: { id: string; username: string }
  independent_reviewer: { id: string; username: string } | null
  change_status: string
}

export interface CreateChangeInput {
  operation_profile_key: string
  workflow_id: string
  title: string
  summary?: string
  justification?: string
  requested_inputs?: Record<string, unknown>
  scheduled_for?: string | null
  targets: Array<{
    target_type: string
    target_identifier: string
    environment: string
    display_name?: string
  }>
  is_emergency?: boolean
  emergency_reason?: string
}
