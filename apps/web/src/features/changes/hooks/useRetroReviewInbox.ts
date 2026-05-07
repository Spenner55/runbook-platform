import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '../../../shared/lib/queryKeys'
import { listRetroReviewInbox } from '../api/changesApi'

export function useRetroReviewInbox() {
  return useQuery({
    queryKey: queryKeys.retroReviewInbox,
    queryFn: listRetroReviewInbox,
  })
}
