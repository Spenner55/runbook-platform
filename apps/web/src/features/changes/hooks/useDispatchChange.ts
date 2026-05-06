import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { dispatchChange } from '../api/changesApi'

export function useDispatchChange(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => dispatchChange(changeId),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.change(changeId), updated)
      queryClient.invalidateQueries({ queryKey: queryKeys.changes })
    },
  })
}
