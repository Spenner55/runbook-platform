export interface WorkflowSummary {
  id: string
  name: string
  version: number
  status: string
  definition_schema_version: string
  requires_review: boolean
  parse_source: 'manual' | 'ai_parse'
  runbook_id: string
  organization_id: string
  created_at: string
  updated_at: string
}

// --- v1 types (unchanged) ---

export interface WorkflowStep {
  id: string
  name: string
  type: string
  risk: string
  requiresApproval: boolean
  command?: string
}

export interface WorkflowDefinitionV1 {
  name: string
  steps: WorkflowStep[]
}

// --- v2 types ---

export interface RetrySpec {
  maxAttempts: number
  backoffSeconds?: number
  retryOn?: string[]
}

export interface IdempotencySpec {
  mode: 'none' | 'natural' | 'keyed' | 'external'
  key?: string
  reason?: string
}

export interface DryRunSpec {
  supported: boolean
  strategy: 'native' | 'validate_only' | 'mock' | 'unsupported'
  requiresSecrets?: boolean
}

export interface SecretDeclaration {
  key: string
  displayName?: string
  provider?: string
  ref?: string
  requiredBy?: string[]
}

export interface ArtifactDeclaration {
  key: string
  name?: string
  path?: string
  kind?: 'file' | 'report' | 'stdout' | 'stderr' | 'log'
  mimeType?: string
  required?: boolean
  maxBytes?: number
  evidenceRole?: string
}

export interface ActionInvocation {
  type: string
  version?: string
  params?: Record<string, unknown>
  inputs?: Record<string, unknown>
  outputs?: Record<string, unknown>
}

export interface WorkflowStepV2 {
  id: string
  name: string
  type: string
  risk: string
  requiresApproval?: boolean
  action: ActionInvocation
  timeoutSeconds?: number
  retry?: RetrySpec
  idempotency?: IdempotencySpec
  dryRun?: DryRunSpec
  secrets?: string[]
  artifacts?: ArtifactDeclaration[]
}

export interface WorkflowDefinitionV2 {
  schemaVersion: '2'
  name: string
  description?: string
  catalogVersion?: string
  defaults?: {
    timeoutSeconds?: number
    retry?: RetrySpec
  }
  secrets?: SecretDeclaration[]
  steps: WorkflowStepV2[]
}

export interface ValidationError {
  code: string
  detail: string
}

export interface ValidationReport {
  valid: boolean
  errors: ValidationError[]
  warnings: ValidationError[]
}

// --- WorkflowDetail ---

export interface WorkflowDetail {
  id: string
  name: string
  version: number
  status: string
  requires_review: boolean
  parse_source: 'manual' | 'ai_parse'
  definition: WorkflowDefinitionV1 | WorkflowDefinitionV2
  definition_schema_version: string
  definition_hash_sha256: string
  catalog_version: string
  validation_status: 'valid' | 'invalid' | 'pending' | 'not_applicable'
  validation_report: ValidationReport
  runbook_id: string
  organization_id: string
  created_at: string
  updated_at: string
}

export interface CreateWorkflowInput {
  runbook_id: string
}

export interface ValidateWorkflowInput {
  definition: Record<string, unknown>
  schema_version?: string
}
