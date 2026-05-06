import { apiRequest } from '../../../shared/api/client'
import type { CreateFreezeRuleInput, FreezeRule, UpdateFreezeRuleInput } from '../types'

export interface ListFreezeRulesParams {
  organization_id: string
  is_active?: 'true' | 'false' | 'all'
}

export function listFreezeRules(params: ListFreezeRulesParams) {
  const query = new URLSearchParams({ organization_id: params.organization_id })
  if (params.is_active && params.is_active !== 'all') query.set('is_active', params.is_active)
  return apiRequest<{ results: FreezeRule[] }>(`/api/v1/freeze-rules/?${query}`)
}

function withOrganization(path: string, organizationId: string) {
  const query = new URLSearchParams({ organization_id: organizationId })
  return `${path}?${query}`
}

export function createFreezeRule(input: CreateFreezeRuleInput) {
  const { organization_id, ...body } = input
  return apiRequest<FreezeRule>(withOrganization('/api/v1/freeze-rules/', organization_id), {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateFreezeRule(
  ruleId: string,
  organizationId: string,
  input: UpdateFreezeRuleInput
) {
  return apiRequest<FreezeRule>(
    withOrganization(`/api/v1/freeze-rules/${ruleId}/`, organizationId),
    {
      method: 'PATCH',
      body: JSON.stringify(input),
    }
  )
}

export function deactivateFreezeRule(ruleId: string, organizationId: string) {
  return apiRequest<FreezeRule>(
    withOrganization(`/api/v1/freeze-rules/${ruleId}/deactivate/`, organizationId),
    { method: 'POST' }
  )
}
