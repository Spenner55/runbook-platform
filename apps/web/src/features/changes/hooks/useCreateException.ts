import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createException } from '../api/changesApi'
import type { CreateExceptionInput } from '../types'

export function useCreateException(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateExceptionInput) => createException(changeId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.changeExceptions(changeId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.change(changeId) })
    },
  })
}
