import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'

import { rejectWorkflowReview } from '../api/workflowsApi'

export function useRejectWorkflowReview(workflowId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => rejectWorkflowReview(workflowId ?? ''),
    onSuccess: async (workflow) => {
      queryClient.setQueryData(queryKeys.workflow(workflow.id), workflow)
    },
  })
}
