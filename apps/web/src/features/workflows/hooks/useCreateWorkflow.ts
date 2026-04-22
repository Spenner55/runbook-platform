import { useMutation } from '@tanstack/react-query'

import { createWorkflow } from '../api/workflowsApi'

export function useCreateWorkflow() {
  return useMutation({
    mutationFn: createWorkflow,
  })
}
