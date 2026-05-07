import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listRetroReviews } from '../api/changesApi'

export function useRetroReviews(changeId: string) {
  return useQuery({
    queryKey: queryKeys.changeRetroReviews(changeId),
    queryFn: () => listRetroReviews(changeId),
    enabled: Boolean(changeId),
  })
}
