import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createChange } from '../api/changesApi'
import type { CreateChangeInput } from '../types'

export function useCreateChange() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (input: CreateChangeInput) => createChange(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.changes })
    },
  })
}
