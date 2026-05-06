import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { deactivateFreezeRule } from '../api/freezeRulesApi'

export function useDeactivateFreezeRule(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) => deactivateFreezeRule(ruleId, organizationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.freezeRules(organizationId) })
    },
  })
}
