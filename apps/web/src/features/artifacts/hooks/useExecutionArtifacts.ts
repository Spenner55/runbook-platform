import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listExecutionArtifacts } from '../api/artifactsApi'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

export function useExecutionArtifacts(
  executionId: string | null,
  executionStatus: string | null,
) {
  return useQuery({
    queryKey: queryKeys.executionArtifacts(executionId ?? 'missing'),
    enabled: Boolean(executionId),
    queryFn: () => listExecutionArtifacts(executionId ?? ''),
    refetchInterval: () => {
      if (!executionStatus || !ACTIVE_EXECUTION_STATUSES.has(executionStatus)) {
        return false
      }
      return 3000
    },
  })
}
