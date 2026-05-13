import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { createV2Draft } from '../api/workflowsApi'

export function useCreateV2Draft(workflowId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => createV2Draft(workflowId ?? ''),
    onSuccess: async (workflow) => {
      queryClient.setQueryData(queryKeys.workflow(workflow.id), workflow)
    },
  })
}
