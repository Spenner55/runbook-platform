import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { patchWindow } from '../api/changesApi'
import type { PatchWindowInput } from '../types'

export function usePatchWindow(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: PatchWindowInput) => patchWindow(changeId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.change(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.changePreflight(changeId) })
    },
  })
}
