import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createPolicy } from '../api/policiesApi'
import type { CreatePolicyInput } from '../types'

export function useCreatePolicy(organizationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CreatePolicyInput) => createPolicy(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.policies(organizationId) })
    },
  })
}
