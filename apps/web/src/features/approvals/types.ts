export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'timed_out'

export interface ApprovalDecision {
  id: string
  decision: 'approved' | 'rejected' | 'timed_out'
  source_type: 'human' | 'system'
  decided_by_label: string
  decided_at: string
  notes: string
}

export interface ApprovalRequestStep {
  id: string
  position: number
  step_key: string
  name: string
  step_type: string
  risk_level: string
  status: string
  requires_approval: boolean
}

export interface ApprovalRequest {
  id: string
  organization_id: string
  execution_id: string
  execution_status: string
  status: ApprovalStatus
  requested_by_runner_id: string
  requested_at: string
  timeout_seconds: number | null
  expires_at: string | null
  resolved_at: string | null
  step: ApprovalRequestStep
  decision: ApprovalDecision | null
}

export interface DecideApprovalInput {
  decision: 'approved' | 'rejected'
  notes?: string
  actor_display_name: string
}
