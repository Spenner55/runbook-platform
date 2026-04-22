import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createRunbook } from '../api/runbooksApi'

export function useCreateRunbook() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: createRunbook,
    onSuccess: async (runbook) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.runbooks(runbook.organization_id),
        }),
        queryClient.setQueryData(queryKeys.runbook(runbook.id), runbook),
      ])
    },
  })
}
