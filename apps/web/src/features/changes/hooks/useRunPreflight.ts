import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { runPreflight } from '../api/changesApi'

export function useRunPreflight(changeId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => runPreflight(changeId),
    onSuccess: (check) => {
      queryClient.setQueryData(queryKeys.changePreflight(changeId), check)
    },
  })
}
