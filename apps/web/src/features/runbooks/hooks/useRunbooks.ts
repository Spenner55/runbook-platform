import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listRunbooks } from '../api/runbooksApi'

export function useRunbooks(organizationId: string | null) {
  return useQuery({
    queryKey: queryKeys.runbooks(organizationId ?? undefined),
    enabled: Boolean(organizationId),
    queryFn: async () => {
      const runbooks = await listRunbooks()
      return runbooks.filter((runbook) => runbook.organization_id === organizationId)
    },
  })
}
