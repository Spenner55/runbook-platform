import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { closeChange } from '../api/changesApi'
import type { CloseChangeInput } from '../types'

export function useCloseChange(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CloseChangeInput) => closeChange(changeId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.change(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.changes })
    },
  })
}
