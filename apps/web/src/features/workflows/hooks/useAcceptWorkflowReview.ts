import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { acceptWorkflowReview } from '../api/workflowsApi'

export function useAcceptWorkflowReview(workflowId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => acceptWorkflowReview(workflowId ?? ''),
    onSuccess: async (workflow) => {
      queryClient.setQueryData(queryKeys.workflow(workflow.id), workflow)
    },
  })
}
