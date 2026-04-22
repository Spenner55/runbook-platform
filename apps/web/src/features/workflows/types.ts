export interface WorkflowStep {
  id: string
  name: string
  type: string
  risk: string
  requiresApproval: boolean
  command?: string
}

export interface WorkflowDetail {
  id: string
  name: string
  version: number
  status: string
  definition: {
    name: string
    steps: WorkflowStep[]
  }
  definition_schema_version: string
  runbook_id: string
  organization_id: string
  created_at: string
  updated_at: string
}

export interface CreateWorkflowInput {
  runbook_id: string
}
