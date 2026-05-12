import type { PolicyEvaluationSummary } from '../policies/types'

export interface ExecutionSummary {
  id: string
  status: string
  workflow_id: string
  workflow_name: string | null
  organization_id: string
  workflow_version: number
  claimed_by_runner_id: string
  claimed_at: string | null
  last_heartbeat_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface ExecutionStep {
  id: string
  position: number
  step_key: string
  name: string
  step_type: string
  risk_level: string
  command?: string | null
  requires_approval: boolean
  status: string
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  error_message: string
  policy_evaluation: PolicyEvaluationSummary | null
  failure_kind: string | null
  timed_out: boolean
  cancelled: boolean
  sandbox_provider: string | null
  sandbox_run_id: string | null
  result_metadata: Record<string, unknown> | null
}

export interface ExecutionDetail {
  id: string
  status: string
  workflow_id: string
  organization_id: string
  workflow_version: number
  workflow_snapshot: Record<string, unknown>
  claimed_by_runner_id: string
  claim_token_present: boolean
  claimed_at: string | null
  last_heartbeat_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  cancel_requested_at: string | null
  cancel_requested_by: string | null
  cancel_reason: string | null
  steps: ExecutionStep[]
}

export interface CreateExecutionInput {
  workflow_id: string
}
