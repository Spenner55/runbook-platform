import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listExecutions } from '../api/executionsApi'

export function useExecutions(statuses?: string[]) {
  return useQuery({
    queryKey: queryKeys.executions(statuses),
    queryFn: () => listExecutions(statuses),
  })
}
