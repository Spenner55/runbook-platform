export interface ExecutionStep {
  id: string
  position: number
  step_key: string
  name: string
  step_type: string
  risk_level: string
  command: string
  requires_approval: boolean
  status: string
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  error_message: string
}

export interface ExecutionDetail {
  id: string
  status: string
  workflow_id: string
  organization_id: string
  workflow_version: number
  workflow_snapshot: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  steps: ExecutionStep[]
}

export interface CreateExecutionInput {
  workflow_id: string
}
