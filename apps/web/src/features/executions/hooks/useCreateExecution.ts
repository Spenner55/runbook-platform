import { useMutation } from '@tanstack/react-query'

import { createExecution } from '../api/executionsApi'

export function useCreateExecution() {
  return useMutation({
    mutationFn: createExecution,
  })
}
