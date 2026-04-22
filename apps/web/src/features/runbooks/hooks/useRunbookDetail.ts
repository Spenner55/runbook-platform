import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getRunbook } from '../api/runbooksApi'

export function useRunbookDetail(runbookId: string | null) {
  return useQuery({
    queryKey: queryKeys.runbook(runbookId ?? 'missing'),
    enabled: Boolean(runbookId),
    queryFn: () => getRunbook(runbookId ?? ''),
  })
}
