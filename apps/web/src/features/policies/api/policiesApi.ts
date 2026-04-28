import { apiRequest } from '../../../shared/api/client'
import type {
  CreatePolicyInput,
  CreateRuleInput,
  Policy,
  PolicyDetail,
  PolicyRule,
  UpdatePolicyInput,
  UpdateRuleInput,
} from '../types'

export interface ListPoliciesParams {
  organization_id: string
  is_active?: 'true' | 'false' | 'all'
}

export function listPolicies(params: ListPoliciesParams) {
  const query = new URLSearchParams({ organization_id: params.organization_id })
  if (params.is_active) query.set('is_active', params.is_active)
  return apiRequest<{ results: Policy[] }>(`/api/v1/policies/?${query}`)
}

function withOrganization(path: string, organizationId: string) {
  const query = new URLSearchParams({ organization_id: organizationId })
  return `${path}?${query}`
}

export function getPolicy(policyId: string, organizationId: string) {
  return apiRequest<PolicyDetail>(withOrganization(`/api/v1/policies/${policyId}/`, organizationId))
}

export function createPolicy(input: CreatePolicyInput) {
  return apiRequest<PolicyDetail>('/api/v1/policies/', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updatePolicy(policyId: string, organizationId: string, input: UpdatePolicyInput) {
  return apiRequest<PolicyDetail>(
    withOrganization(`/api/v1/policies/${policyId}/`, organizationId),
    {
      method: 'PATCH',
      body: JSON.stringify(input),
    }
  )
}

export function createRule(policyId: string, organizationId: string, input: CreateRuleInput) {
  return apiRequest<PolicyRule>(
    withOrganization(`/api/v1/policies/${policyId}/rules/`, organizationId),
    {
      method: 'POST',
      body: JSON.stringify(input),
    }
  )
}

export function updateRule(
  policyId: string,
  organizationId: string,
  ruleId: string,
  input: UpdateRuleInput
) {
  return apiRequest<PolicyRule>(
    withOrganization(`/api/v1/policies/${policyId}/rules/${ruleId}/`, organizationId),
    {
      method: 'PATCH',
      body: JSON.stringify(input),
    }
  )
}

export function deleteRule(policyId: string, organizationId: string, ruleId: string) {
  return apiRequest<void>(
    withOrganization(`/api/v1/policies/${policyId}/rules/${ruleId}/`, organizationId),
    {
      method: 'DELETE',
    }
  )
}
