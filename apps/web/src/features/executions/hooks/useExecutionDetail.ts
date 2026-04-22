import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getExecution } from '../api/executionsApi'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

export function useExecutionDetail(executionId: string | null) {
  return useQuery({
    queryKey: queryKeys.execution(executionId ?? 'missing'),
    enabled: Boolean(executionId),
    queryFn: () => getExecution(executionId ?? ''),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (!status || !ACTIVE_EXECUTION_STATUSES.has(status)) {
        return false
      }
      return 1500
    },
  })
}
