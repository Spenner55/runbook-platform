import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { updatePolicy } from '../api/policiesApi'
import type { UpdatePolicyInput } from '../types'

export function useUpdatePolicy(policyId: string, organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: UpdatePolicyInput) => updatePolicy(policyId, organizationId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.policy(policyId, organizationId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.policies(organizationId) })
    },
  })
}
