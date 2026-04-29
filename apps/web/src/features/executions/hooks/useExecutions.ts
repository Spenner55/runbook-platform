import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listExecutions } from '../api/executionsApi'

// NOTE: GET /api/v1/executions/ does not accept a status query parameter.
// We fetch all org-scoped executions and filter client-side. Acceptable for
// demo/testing data volumes; add a backend filter in a future phase if needed.
export function useExecutions(status?: string) {
  return useQuery({
    queryKey: queryKeys.executions(status),
    queryFn: async () => {
      const executions = await listExecutions()
      if (!status) return executions
      return executions.filter((e) => e.status === status)
    },
  })
}
