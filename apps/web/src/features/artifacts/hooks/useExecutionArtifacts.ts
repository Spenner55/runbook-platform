import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listExecutionArtifacts } from '../api/artifactsApi'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

export function useExecutionArtifacts(
  executionId: string | null,
  organizationId: string | null,
  executionStatus: string | null
) {
  return useQuery({
    queryKey: queryKeys.executionArtifacts(organizationId ?? 'missing', executionId ?? 'missing'),
    enabled: Boolean(executionId && organizationId),
    queryFn: () =>
      listExecutionArtifacts(executionId ?? '', {
        organization_id: organizationId ?? '',
      }),
    refetchInterval: () => {
      if (!executionStatus || !ACTIVE_EXECUTION_STATUSES.has(executionStatus)) {
        return false
      }
      return 3000
    },
  })
}
