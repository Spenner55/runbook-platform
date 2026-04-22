import { useMutation, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { publishWorkflow } from '../api/workflowsApi'

export function usePublishWorkflow(workflowId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => publishWorkflow(workflowId ?? ''),
    onSuccess: async (workflow) => {
      queryClient.setQueryData(queryKeys.workflow(workflow.id), workflow)
    },
  })
}
