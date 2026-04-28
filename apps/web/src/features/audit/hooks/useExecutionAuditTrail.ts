import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getExecutionAuditTrail } from '../api/auditApi'

const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])

export function useExecutionAuditTrail(input: {
  executionId: string | null
  organizationId: string | null
  executionStatus: string | null
}) {
  return useQuery({
    queryKey: queryKeys.executionAuditTrail(input.executionId ?? 'missing'),
    enabled: Boolean(input.executionId && input.organizationId),
    queryFn: () =>
      getExecutionAuditTrail({
        executionId: input.executionId ?? '',
        organizationId: input.organizationId ?? '',
      }),
    refetchInterval: () => {
      if (!input.executionStatus || !ACTIVE_EXECUTION_STATUSES.has(input.executionStatus)) {
        return false
      }
      return 3000
    },
  })
}
