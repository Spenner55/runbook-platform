import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { submitChange } from '../api/changesApi'

export function useSubmitChange(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => submitChange(changeId),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.change(changeId), updated)
      queryClient.invalidateQueries({ queryKey: queryKeys.changes })
    },
  })
}
