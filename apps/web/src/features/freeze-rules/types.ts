export type FreezeRuleBehavior = 'block' | 'allow_with_exception'
export type FreezeRuleScopeType = 'all_production' | 'target_type' | 'target_identifier'

export interface FreezeRule {
  id: string
  name: string
  description: string
  is_active: boolean
  behavior: FreezeRuleBehavior
  starts_at: string
  ends_at: string
  scope_type: FreezeRuleScopeType
  target_type: string
  target_identifier: string
  requires_exception_reference: boolean
  created_at: string
  updated_at: string
}

export interface CreateFreezeRuleInput {
  organization_id: string
  name: string
  description?: string
  behavior: FreezeRuleBehavior
  starts_at: string
  ends_at: string
  scope_type: FreezeRuleScopeType
  target_type?: string
  target_identifier?: string
  requires_exception_reference?: boolean
}

export interface UpdateFreezeRuleInput {
  name?: string
  description?: string
  behavior?: FreezeRuleBehavior
  starts_at?: string
  ends_at?: string
  scope_type?: FreezeRuleScopeType
  target_type?: string
  target_identifier?: string
  requires_exception_reference?: boolean
}
