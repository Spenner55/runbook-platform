import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { submitVerificationResult } from '../api/changesApi'
import type { SubmitVerificationResultInput } from '../types'

export function useSubmitVerificationResult(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: SubmitVerificationResultInput) =>
      submitVerificationResult(changeId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.changeVerificationPlan(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.change(changeId) })
    },
  })
}
