import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { activateBreakglass } from '../api/changesApi'
import type { ActivateBreakglassInput } from '../types'

export function useActivateBreakglass(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: ActivateBreakglassInput) => activateBreakglass(changeId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.change(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.retroReviewInbox })
    },
  })
}
