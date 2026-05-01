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
  created_at: string
  updated_at: string
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
}
