import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createFreezeRule } from '../api/freezeRulesApi'
import type { CreateFreezeRuleInput } from '../types'

export function useCreateFreezeRule(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreateFreezeRuleInput) => createFreezeRule(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.freezeRules(organizationId) })
    },
  })
}
