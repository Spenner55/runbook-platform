export type PolicyOutcome = 'approval_required' | 'auto_approve' | 'block'
export type PolicyConditionType = 'risk_level' | 'step_type' | 'time_window'

export interface Policy {
  id: string
  organization_id: string
  name: string
  description: string
  is_active: boolean
  rule_count: number
  created_at: string
  updated_at: string
}

export interface PolicyRule {
  id: string
  name: string
  description: string
  is_active: boolean
  priority: number
  condition_type: PolicyConditionType
  condition_params: Record<string, unknown>
  outcome: PolicyOutcome
  reason: string
  created_at: string
  updated_at: string
}

export interface PolicyDetail extends Policy {
  rules: PolicyRule[]
}

export interface PolicyEvaluationSummary {
  id: string
  outcome: PolicyOutcome
  effective_outcome: PolicyOutcome
  decision_source: 'policy_rule' | 'workflow_default'
  matched: boolean
  policy_id: string | null
  policy_name: string | null
  rule_id: string | null
  rule_name: string | null
  reason: string
  evaluated_at: string
}

export interface CreatePolicyInput {
  organization_id: string
  name: string
  description?: string
  is_active?: boolean
}

export interface UpdatePolicyInput {
  name?: string
  description?: string
  is_active?: boolean
}

export interface CreateRuleInput {
  name: string
  description?: string
  is_active?: boolean
  priority: number
  condition_type: PolicyConditionType
  condition_params: Record<string, unknown>
  outcome: PolicyOutcome
  reason?: string
}

export interface UpdateRuleInput {
  name?: string
  description?: string
  is_active?: boolean
  priority?: number
  condition_type?: PolicyConditionType
  condition_params?: Record<string, unknown>
  outcome?: PolicyOutcome
  reason?: string
}
