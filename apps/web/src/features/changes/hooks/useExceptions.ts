import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listExceptions } from '../api/changesApi'

export function useExceptions(changeId: string) {
  return useQuery({
    queryKey: queryKeys.changeExceptions(changeId),
    queryFn: () => listExceptions(changeId),
    enabled: Boolean(changeId),
  })
}
