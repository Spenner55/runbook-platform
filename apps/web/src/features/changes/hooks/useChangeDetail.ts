import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { getChange } from '../api/changesApi'

export function useChangeDetail(changeId: string) {
  return useQuery({
    queryKey: queryKeys.change(changeId),
    queryFn: () => getChange(changeId),
    enabled: Boolean(changeId),
  })
}
