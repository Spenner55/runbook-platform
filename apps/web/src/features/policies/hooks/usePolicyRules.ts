import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createRule, deleteRule, updateRule } from '../api/policiesApi'
import type { CreateRuleInput, UpdateRuleInput } from '../types'

export function useCreateRule(policyId: string, organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateRuleInput) => createRule(policyId, organizationId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.policy(policyId, organizationId) })
    },
  })
}

export function useUpdateRule(policyId: string, organizationId: string, ruleId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: UpdateRuleInput) => updateRule(policyId, organizationId, ruleId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.policy(policyId, organizationId) })
    },
  })
}

export function useDeactivateRule(policyId: string, organizationId: string, ruleId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deleteRule(policyId, organizationId, ruleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.policy(policyId, organizationId) })
    },
  })
}
